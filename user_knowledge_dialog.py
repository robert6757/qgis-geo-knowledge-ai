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
from qgis.PyQt.QtCore import QCoreApplication, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox, QHeaderView, QTableWidgetItem
from qgis.core import QgsSettings

from .compat import *
from .global_defs import AI_SERVER_DOMAIN, USER_EMAIL_TAG, USER_KNOWLEDGE_TASK_ID_TAG
from .global_utils import get_auth_headers, get_qgis_proxies

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'user_knowledge_dialog.ui'))


def _translate_status(value, default_text):
    """Translate a server-side knowledge build status value to local text."""
    if value == "completed":
        return QCoreApplication.translate("UserKnowledgeDialog", "Built")
    if value == "failed":
        return QCoreApplication.translate("UserKnowledgeDialog", "Failed")
    if value == "pending":
        return QCoreApplication.translate("UserKnowledgeDialog", "Pending")
    if value == "running":
        return QCoreApplication.translate("UserKnowledgeDialog", "Building...")
    return default_text


class KnowledgeTaskStatusWorker(QThread):
    """Background worker that polls the build task status."""

    # Emitted when a file status text needs to be updated.
    # Arguments: file_name, status_text
    status_updated = pyqtSignal(str, str, str)
    # Emitted when the whole batch finished, succeeded or failed.
    finished_with_message = pyqtSignal(str)

    def __init__(self, task_id, parent=None):
        """
        :param task_id: Server-side task id to poll.
        """
        super().__init__(parent)
        self.task_id = task_id
        self._is_running = True

    def run(self):
        status_url = f"{AI_SERVER_DOMAIN}/ai/v1/user/knowledge/build/status/{self.task_id}"
        proxies = get_qgis_proxies()
        headers = get_auth_headers()

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

                if status == "completed":
                    final_status = "completed"
                    kb_root = status_json.get("result", {}).get("user_kb_root", "")
                    final_message = kb_root or ""
                    for name, info in file_statuses.items():
                        file_status = (info or {}).get("status")
                        status_text = _translate_status(
                            file_status, self.tr("Built")
                        )
                        self.status_updated.emit(name, file_status, status_text)
                    break
                elif status == "failed":
                    final_status = "failed"
                    final_message = status_json.get(
                        "error",
                        status_json.get("message", self.tr("Unknown error"))
                    )
                    for name, info in file_statuses.items():
                        file_status = (info or {}).get("status")
                        status_text = _translate_status(
                            file_status, self.tr("Failed")
                        )
                        self.status_updated.emit(name, file_status, status_text)
                    break
                else:
                    # pending / running
                    if total > 0:
                        overall_text = self.tr("Building {progress}/{total}").format(
                            progress=progress, total=total
                        )
                    else:
                        overall_text = self.tr("Building...")
                    for name, info in file_statuses.items():
                        file_status = (info or {}).get("status")
                        status_text = _translate_status(file_status, overall_text)
                        self.status_updated.emit(name, file_status, status_text)
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
        self.wait()


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
        self.tableWidgetKnowledge.setColumnWidth(0, max(400, self.tableWidgetKnowledge.columnWidth(0)))
        header = self.tableWidgetKnowledge.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setMinimumSectionSize(50)

        # Wire up buttons.
        self.btnAddKnowledge.clicked.connect(self.handle_add_knowledge)
        self.btnRemove.clicked.connect(self.handle_remove_knowledge)

        # Background worker for server-side knowledge base build status polling.
        self._status_worker = None

        # Load the already built knowledge bases from the server.
        self._load_remote_knowledge_list()

        # Restore status of any previously unfinished knowledge build task.
        self._restore_historical_task_status()

    def _restore_historical_task_status(self):
        """Query the stored historical task status and update the table.

        If a previous build task id is saved in QSettings, this method fetches
        its current state and reflects each file status in ``tableWidgetKnowledge``.
        If the task is still running (or pending), a status worker is started
        to keep polling. The stored task id is cleared once the task is finished.
        """
        task_id = QgsSettings().value(USER_KNOWLEDGE_TASK_ID_TAG, "")
        if not task_id:
            return

        email = self._get_user_email()
        if not email:
            return

        status_url = f"{AI_SERVER_DOMAIN}/ai/v1/user/knowledge/build/status/{task_id}"
        proxies = get_qgis_proxies()
        headers = get_auth_headers()

        try:
            response = requests.get(
                status_url,
                headers=headers,
                proxies=proxies,
                timeout=10,
            )
            if response.status_code != 200:
                print(
                    f"[UserKnowledgeDialog] historical task status failed: HTTP "
                    f"{response.status_code} {response.text[:200]}"
                )
                QgsSettings().remove(USER_KNOWLEDGE_TASK_ID_TAG)
                return

            status_json = response.json()
        except Exception as e:
            print(f"[UserKnowledgeDialog] historical task status failed: {e}")
            QgsSettings().remove(USER_KNOWLEDGE_TASK_ID_TAG)
            return

        code = status_json.get("code")
        if code != 0:
            message = status_json.get("message", "unknown error")
            print(f"[UserKnowledgeDialog] historical task status failed: {message}")
            QgsSettings().remove(USER_KNOWLEDGE_TASK_ID_TAG)
            return

        task_status = status_json.get("status")
        file_statuses = status_json.get("files") or {}

        existing_names = {item["name"]: idx for idx, item in enumerate(self.knowledge_files)}

        for name, status_info in file_statuses.items():
            file_status = (status_info or {}).get("status")
            status_text = _translate_status(file_status, self.tr("Building..."))

            if name not in existing_names:
                self.knowledge_files.append({
                    "name": name,
                    "status": status_text,
                })

        self._refresh_table()

        if task_status in ("pending", "running"):
            self._start_status_worker(task_id)
        elif task_status in ("completed", "failed"):
            QgsSettings().remove(USER_KNOWLEDGE_TASK_ID_TAG)

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

    def _get_user_email(self):
        """Return the configured user email from QGIS settings."""
        return QgsSettings().value(USER_EMAIL_TAG, "")

    def _update_button_state(self, state):
        """Enable or disable the Add/Remove button based on the selected file status."""
        self.btnRemove.setEnabled(state)
        self.btnAddKnowledge.setEnabled(state)

    def _start_status_worker(self, task_id):
        """Start a background worker to poll the status of the given task."""
        if self._status_worker and self._status_worker.isRunning():
            self._status_worker.stop()

        self._status_worker = KnowledgeTaskStatusWorker(task_id, self)
        self._status_worker.status_updated.connect(self._on_status_updated)
        self._status_worker.finished_with_message.connect(self._on_build_finished)
        self._status_worker.start()

    def _submit_build_request(self, file_entries, email):
        """Upload files and create a knowledge build task in the main thread.

        On success the task id is persisted to QSettings and a status worker is
        started to poll progress. On failure a warning message is shown.
        """
        build_url = f"{AI_SERVER_DOMAIN}/ai/v1/user/knowledge/build"
        proxies = get_qgis_proxies()
        headers = get_auth_headers()

        file_handles = []
        response = None
        try:
            files_payload = []
            for entry in file_entries:
                path = entry["path"]
                fh = open(path, "rb")
                file_handles.append(fh)
                files_payload.append(
                    ("files", (entry["name"], fh, "application/octet-stream"))
                )

            data = {"email": email}

            response = requests.post(
                build_url,
                data=data,
                files=files_payload,
                headers=headers,
                proxies=proxies,
                timeout=30,
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                self.tr("Geo Knowledge AI"),
                self.tr("Failed to start knowledge build: {error}").format(error=str(e)),
                QMessageBoxOK,
            )
            return
        finally:
            for fh in file_handles:
                try:
                    fh.close()
                except Exception as e:
                    print("Error closing file handle: %s" % e)

        if response is None or response.status_code != 200:
            code = response.status_code if response else 0
            server_message = ""
            text = ""
            if response is not None:
                try:
                    resp_json = response.json()
                    server_message = resp_json.get("message", "")
                except Exception:
                    text = response.text[:200]

            failed_status = _translate_status("failed", self.tr("Failed"))
            for entry in file_entries:
                for item in self.knowledge_files:
                    if item["name"] == entry["name"] and item.get("status") not in (
                        self.tr("Built"),
                        self.tr("Failed"),
                    ):
                        item["status"] = failed_status
                        break
            self._refresh_table()

            if server_message:
                QMessageBox.warning(
                    self,
                    self.tr("Geo Knowledge AI"),
                    self.tr("Failed to start knowledge build: {message}").format(
                        message=server_message
                    ),
                    QMessageBoxOK,
                )
            else:
                QMessageBox.warning(
                    self,
                    self.tr("Geo Knowledge AI"),
                    self.tr("Failed to start knowledge build: {text}").format(
                        text=text
                    ),
                    QMessageBoxOK,
                )
            return

        try:
            resp_json = response.json()
        except Exception:
            QMessageBox.warning(
                self,
                self.tr("Geo Knowledge AI"),
                self.tr("Failed to parse build response: {text}").format(
                    text=response.text[:200]
                ),
                QMessageBoxOK,
            )
            return

        code = resp_json.get("code")
        if code != 0:
            message = resp_json.get("message", "unknown error")

            failed_status = _translate_status("failed", self.tr("Failed"))
            for entry in file_entries:
                for item in self.knowledge_files:
                    if item["name"] == entry["name"] and item.get("status") not in (
                        self.tr("Built"),
                        self.tr("Failed"),
                    ):
                        item["status"] = failed_status
                        break
            self._refresh_table()

            QMessageBox.warning(
                self,
                self.tr("Geo Knowledge AI"),
                self.tr("Failed to start knowledge build: {message}").format(message=message),
                QMessageBoxOK,
            )
            return

        task_id = resp_json.get("task_id")
        if not task_id:
            QMessageBox.warning(
                self,
                self.tr("Geo Knowledge AI"),
                self.tr("No task_id returned from knowledge build endpoint."),
                QMessageBoxOK,
            )
            return

        QgsSettings().setValue(USER_KNOWLEDGE_TASK_ID_TAG, task_id)

        for entry in file_entries:
            self._on_status_updated(entry["name"], "pending", _translate_status("pending", ""))

        self._start_status_worker(task_id)

    def _on_status_updated(self, file_name, file_staus, status_text):
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

        # Control the button state based on the task status
        if file_staus == "pending" or file_staus == "running":
            self._update_button_state(False)
        else:
            self._update_button_state(True)

    def _on_build_finished(self, message):
        """Slot called when the knowledge build worker finishes."""
        QgsSettings().remove(USER_KNOWLEDGE_TASK_ID_TAG)
        if message.startswith("Failed") or message.startswith(self.tr("Failed")):
            QMessageBox.warning(self, self.tr("Geo Knowledge AI"), message, QMessageBoxOK)
        else:
            # message is either a success message or the kb_root path.
            if message and not message.startswith(self.tr("Knowledge base built")):
                for item in self.knowledge_files:
                    item["kb_root"] = message
            QMessageBox.information(
                self,
                self.tr("Geo Knowledge AI"),
                self.tr("Knowledge base built successfully.") if not message else message,
                QMessageBoxOK,
            )
        self._status_worker = None
        self._update_button_state(True)

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

        self._submit_build_request(new_entries, email)

    def handle_remove_knowledge(self):
        """Remove the currently selected knowledge base file from the list and server."""
        email = self._get_user_email()
        if not email:
            QMessageBox.warning(
                self,
                self.tr("Warning"),
                self.tr("Please set your email in settings before removing knowledge files."),
                QMessageBoxOK,
            )
            return

        selected_rows = self.tableWidgetKnowledge.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(
                self,
                self.tr("Tip"),
                self.tr("Please select a file to remove."),
                QMessageBoxOK
            )
            return

        reply = QMessageBox.question(
            self,
            self.tr("Confirm Delete"),
            self.tr("Are you sure you want to delete the selected knowledge file?"),
            QMessageBoxYes | QMessageBoxNo,
            QMessageBoxNo,
        )
        if reply != QMessageBoxYes:
            return

        clear_url = f"{AI_SERVER_DOMAIN}/ai/v1/user/knowledge/clear"
        proxies = get_qgis_proxies()
        headers = get_auth_headers()

        rows_to_remove = []
        failed_names = []

        for model_index in sorted(selected_rows, reverse=True):
            row = model_index.row()
            if not (0 <= row < len(self.knowledge_files)):
                continue

            item = self.knowledge_files[row]
            kb_name = item.get("name", "")

            try:
                response = requests.post(
                    clear_url,
                    json={"email": email, "kb_name": kb_name},
                    headers=headers,
                    proxies=proxies,
                    timeout=30,
                )
                if response.status_code == 200:
                    resp_json = response.json()
                    if resp_json.get("code") == 0 and resp_json.get("cleared"):
                        rows_to_remove.append(row)
                    else:
                        failed_names.append(kb_name)
                elif response.status_code == 404:
                    # Knowledge base already absent on the server; safe to remove locally.
                    rows_to_remove.append(row)
                else:
                    failed_names.append(kb_name)
            except Exception as e:
                print(f"[UserKnowledgeDialog] remove knowledge failed for {kb_name}: {e}")
                failed_names.append(kb_name)

        # Remove from bottom to top to keep indices valid.
        for row in sorted(rows_to_remove, reverse=True):
            del self.knowledge_files[row]

        if failed_names:
            QMessageBox.warning(
                self,
                self.tr("Delete Failed"),
                self.tr("Failed to delete the following knowledge base(s):\n{names}").format(
                    names="\n".join(failed_names)
                ),
                QMessageBoxOK,
            )

        self._refresh_table()

    def get_knowledge_files(self):
        """Return the current list of knowledge base file paths."""
        return [item["path"] for item in self.knowledge_files]

    def closeEvent(self, event):
        """Ensure the background workers are stopped when the dialog closes."""
        if self._status_worker and self._status_worker.isRunning():
            self._status_worker.stop()
        event.accept()