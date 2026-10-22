# -*- coding: utf-8 -*-
"""
/***************************************************************************
                              User Knowledge Base Dialog
  This dialog lets users manage their personal knowledge base documents.
                               -------------------
        begin                : 2026-10-22
        copyright            : (C) 2026 by Geo Knowledge AI
        email                : info@geoknowledgeai.com
        website              : www.geoknowledgeai.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
import time

import requests

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem
from qgis.core import QgsSettings

from .compat import *
from .global_defs import AI_SERVER_DOMAIN, USER_EMAIL_TAG
from .global_utils import get_auth_headers, get_qgis_proxies

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'user_knowledge_dialog.ui'))

class KnowledgeBuildWorker(QThread):
    """Background worker that uploads files and polls the build task status."""

    # Emitted when a file status text needs to be updated.
    # Arguments: file_name, status_text
    status_updated = pyqtSignal(str, str)
    # Emitted when the whole batch finished, succeeded or failed.
    finished_with_message = pyqtSignal(str)

    def __init__(self, file_entries, email, parent=None):
        """
        :param file_entries: List of dicts with keys name, path, size.
        :param email: User email for the knowledge base build request.
        """
        super().__init__(parent)
        self.file_entries = file_entries
        self.email = email
        self._is_running = True

    def run(self):
        build_url = f"{AI_SERVER_DOMAIN}/ai/v1/user/knowledge/build"
        proxies = get_qgis_proxies()
        headers = get_auth_headers()

        file_handles = []
        try:
            files_payload = []
            for entry in self.file_entries:
                path = entry["path"]
                fh = open(path, "rb")
                file_handles.append(fh)
                files_payload.append(
                    ("files", (entry["name"], fh, "application/octet-stream"))
                )

            data = {"email": self.email}

            response = requests.post(
                build_url,
                data=data,
                files=files_payload,
                headers=headers,
                proxies=proxies,
                timeout=30,
            )
        except Exception as e:
            self.finished_with_message.emit(
                self.tr("Failed to start knowledge build: {error}").format(error=str(e))
            )
            return
        finally:
            for fh in file_handles:
                try:
                    fh.close()
                except Exception:
                    pass

        if response.status_code != 200:
            self.finished_with_message.emit(
                self.tr("Failed to start knowledge build: HTTP {code} {text}").format(
                    code=response.status_code, text=response.text[:200]
                )
            )
            return

        try:
            resp_json = response.json()
        except Exception:
            self.finished_with_message.emit(
                self.tr("Failed to parse build response: {text}").format(
                    text=response.text[:200]
                )
            )
            return

        code = resp_json.get("code")
        if code != 0:
            message = resp_json.get("message", "unknown error")
            self.finished_with_message.emit(
                self.tr("Failed to start knowledge build: {message}").format(message=message)
            )
            return

        task_id = resp_json.get("task_id")
        if not task_id:
            self.finished_with_message.emit(
                self.tr("No task_id returned from knowledge build endpoint.")
            )
            return

        for entry in self.file_entries:
            self.status_updated.emit(entry["name"], self.tr("Building..."))

        status_url = f"{AI_SERVER_DOMAIN}/ai/v1/user/knowledge/build/status/{task_id}"
        final_status = None
        final_message = None

        while self._is_running:
            try:
                status_resp = requests.get(
                    status_url,
                    headers=headers,
                    proxies=proxies,
                    timeout=10,
                )
                if status_resp.status_code != 200:
                    final_message = self.tr(
                        "Failed to query task status: HTTP {code}"
                    ).format(code=status_resp.status_code)
                    final_status = "failed"
                    break

                status_json = status_resp.json()
                code = status_json.get("code")
                if code != 0:
                    final_message = self.tr(
                        "Failed to query task status: {message}"
                    ).format(message=status_json.get("message", "unknown error"))
                    final_status = "failed"
                    break

                status = status_json.get("status")
                progress = status_json.get("progress", 0) or 0
                total = status_json.get("total", 0) or 0
                file_statuses = status_json.get("files") or {}

                def _translate_status(value, default_text):
                    if value == "completed":
                        return self.tr("Built")
                    if value == "failed":
                        return self.tr("Failed")
                    if value == "pending":
                        return self.tr("Pending")
                    if value == "running":
                        return self.tr("Building...")
                    return default_text

                if status == "completed":
                    final_status = "completed"
                    kb_root = status_json.get("result", {}).get("user_kb_root", "")
                    final_message = kb_root or ""
                    for entry in self.file_entries:
                        name = entry["name"]
                        file_status = (file_statuses.get(name) or {}).get("status")
                        status_text = _translate_status(
                            file_status, self.tr("Built")
                        )
                        self.status_updated.emit(name, status_text)
                    break
                elif status == "failed":
                    final_status = "failed"
                    final_message = status_json.get(
                        "error",
                        status_json.get("message", self.tr("Unknown error"))
                    )
                    for entry in self.file_entries:
                        name = entry["name"]
                        file_status = (file_statuses.get(name) or {}).get("status")
                        status_text = _translate_status(
                            file_status, self.tr("Failed")
                        )
                        self.status_updated.emit(name, status_text)
                    break
                else:
                    # pending / running
                    if total > 0:
                        overall_text = self.tr("Building {progress}/{total}").format(
                            progress=progress, total=total
                        )
                    else:
                        overall_text = self.tr("Building...")
                    for entry in self.file_entries:
                        name = entry["name"]
                        file_status = (file_statuses.get(name) or {}).get("status")
                        status_text = _translate_status(file_status, overall_text)
                        self.status_updated.emit(name, status_text)
            except Exception as e:
                final_status = "failed"
                final_message = self.tr("Error querying task status: {error}").format(error=str(e))
                break

            time.sleep(2)

        if final_status == "completed":
            self.finished_with_message.emit(
                self.tr("Knowledge base built successfully.") if not final_message else final_message
            )
        elif final_status == "failed":
            self.finished_with_message.emit(
                self.tr("Knowledge build failed: {error}").format(error=final_message)
            )
        else:
            self.finished_with_message.emit(self.tr("Knowledge build stopped."))

    def stop(self):
        self._is_running = False
        self.wait(3000)


class UserKnowledgeDialog(QDialog, FORM_CLASS):

    def __init__(self, parent=None):
        """Constructor."""
        super(UserKnowledgeDialog, self).__init__(parent)
        self.setupUi(self)

        # Supported knowledge base file filters.
        self.file_filter = self.tr("Text, Markdown and PDF files (*.txt *.md *.markdown *.pdf)")

        # Store knowledge base file metadata as list of dicts.
        self.knowledge_files = []

        # Configure the knowledge base table.
        self.tableWidgetKnowledge.setColumnCount(2)
        self.tableWidgetKnowledge.setHorizontalHeaderLabels([
            self.tr("File Name"),
            self.tr("Status")
        ])
        self.tableWidgetKnowledge.setSelectionBehavior(AbstractItemViewSelectRows)
        self.tableWidgetKnowledge.setSelectionMode(AbstractItemViewSingleSelection)
        self.tableWidgetKnowledge.horizontalHeader().setStretchLastSection(True)

        # Wire up buttons.
        self.btnAddKnowledge.clicked.connect(self.handle_add_knowledge)
        self.btnRemove.clicked.connect(self.handle_remove_knowledge)

        # Background worker for server-side knowledge base build.
        self._build_worker = None

        # Load the already built knowledge bases from the server.
        self._load_remote_knowledge_list()

    def _load_remote_knowledge_list(self):
        """Fetch the user's built knowledge bases synchronously."""
        email = self._get_user_email()
        if not email:
            return

        list_url = f"{AI_SERVER_DOMAIN}/ai/v1/user/knowledge/list"
        proxies = get_qgis_proxies()
        headers = get_auth_headers()

        try:
            response = requests.get(
                list_url,
                params={"email": email},
                headers=headers,
                proxies=proxies,
                timeout=30,
            )
            if response.status_code != 200:
                print(
                    f"[UserKnowledgeDialog] remote list failed: HTTP "
                    f"{response.status_code} {response.text[:200]}"
                )
                return

            resp_json = response.json()
        except Exception as e:
            print(f"[UserKnowledgeDialog] remote list failed: {e}")
            return

        code = resp_json.get("code")
        if code != 0:
            message = resp_json.get("message", "unknown error")
            print(f"[UserKnowledgeDialog] remote list failed: {message}")
            return

        file_names = resp_json.get("files") or []
        for entry in file_names:
            if "file_name" not in entry:
                continue
            self.knowledge_files.append({
                "name": entry.get("file_name", ""),
                "status": self.tr("Built"),
            })
        self._refresh_table()

    def _refresh_table(self):
        """Refresh the table widget to reflect the current knowledge file list."""
        self.tableWidgetKnowledge.setRowCount(len(self.knowledge_files))
        for row, item in enumerate(self.knowledge_files):
            name_item = QTableWidgetItem(str(item.get("name", "")))
            status_item = QTableWidgetItem(str(item.get("status", self.tr("Local"))))

            name_item.setFlags(name_item.flags() & ~ItemIsEditable)
            status_item.setFlags(status_item.flags() & ~ItemIsEditable)

            self.tableWidgetKnowledge.setItem(row, 0, name_item)
            self.tableWidgetKnowledge.setItem(row, 1, status_item)

        self.tableWidgetKnowledge.resizeColumnsToContents()

    def _get_user_email(self):
        """Return the configured user email from QGIS settings."""
        return QgsSettings().value(USER_EMAIL_TAG, "")

    def _on_status_updated(self, file_name, status_text):
        """Slot to update a single file status from the worker thread."""
        for idx, item in enumerate(self.knowledge_files):
            if item["name"] == file_name:
                item["status"] = status_text
                status_item = self.tableWidgetKnowledge.item(idx, 1)
                if status_item is None:
                    status_item = QTableWidgetItem()
                    status_item.setFlags(status_item.flags() & ~ItemIsEditable)
                    self.tableWidgetKnowledge.setItem(idx, 1, status_item)
                status_item.setText(status_text)
                break

    def _on_build_finished(self, message):
        """Slot called when the knowledge build worker finishes."""
        if message.startswith("Failed") or message.startswith(self.tr("Failed")):
            QMessageBox.warning(self, self.tr("Knowledge Build"), message, QMessageBoxOK)
        else:
            # message is either a success message or the kb_root path.
            if message and not message.startswith(self.tr("Knowledge base built")):
                for item in self.knowledge_files:
                    item["kb_root"] = message
            QMessageBox.information(
                self,
                self.tr("Knowledge Build"),
                self.tr("Knowledge base built successfully.") if not message else message,
                QMessageBoxOK,
            )
        self._build_worker = None

    def handle_add_knowledge(self):
        """Open a file dialog to add knowledge base documents and submit them to the server."""
        email = self._get_user_email()
        if not email:
            QMessageBox.warning(
                self,
                self.tr("Warning"),
                self.tr("Please set your email in settings before adding knowledge files."),
                QMessageBoxOK,
            )
            return

        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr("Select Knowledge Base Files"),
            "",
            self.file_filter
        )
        if not file_paths:
            return

        new_entries = []
        for path in file_paths:
            if not os.path.isfile(path):
                continue
            file_name = os.path.basename(path)
            entry = {
                "name": file_name,
                "path": path,
                "size": os.path.getsize(path),
                "status": self.tr("Pending"),
            }
            self.knowledge_files.append(entry)
            new_entries.append(entry)

        self._refresh_table()

        if not new_entries:
            return

        self._build_worker = KnowledgeBuildWorker(new_entries, email, self)
        self._build_worker.status_updated.connect(self._on_status_updated)
        self._build_worker.finished_with_message.connect(self._on_build_finished)
        self._build_worker.start()

    def handle_remove_knowledge(self):
        """Remove the currently selected knowledge base file from the list."""
        selected_rows = self.tableWidgetKnowledge.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(
                self,
                self.tr("Tip"),
                self.tr("Please select a file to remove."),
                QMessageBoxOK
            )
            return

        # Remove from bottom to top to keep indices valid.
        for model_index in sorted(selected_rows, reverse=True):
            row = model_index.row()
            if 0 <= row < len(self.knowledge_files):
                del self.knowledge_files[row]

        self._refresh_table()

    def get_knowledge_files(self):
        """Return the current list of knowledge base file paths."""
        return [item["path"] for item in self.knowledge_files]

    def closeEvent(self, event):
        """Ensure the background workers are stopped when the dialog closes."""
        if self._build_worker and self._build_worker.isRunning():
            self._build_worker.stop()
        event.accept()
