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

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem
from .compat import *

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'user_knowledge_dialog.ui'))


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
        self.tableWidgetKnowledge.setColumnCount(3)
        self.tableWidgetKnowledge.setHorizontalHeaderLabels([
            self.tr("File Name"),
            self.tr("Size"),
            self.tr("Status")
        ])
        self.tableWidgetKnowledge.setSelectionBehavior(AbstractItemViewSelectRows)
        self.tableWidgetKnowledge.setSelectionMode(AbstractItemViewSingleSelection)
        self.tableWidgetKnowledge.horizontalHeader().setStretchLastSection(True)

        # Wire up buttons.
        self.btnAddKnowledge.clicked.connect(self.handle_add_knowledge)
        self.btnRemove.clicked.connect(self.handle_remove_knowledge)

    def _format_size(self, size_bytes):
        """Return a human-readable string for the given file size in bytes."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

    def _refresh_table(self):
        """Refresh the table widget to reflect the current knowledge file list."""
        self.tableWidgetKnowledge.setRowCount(len(self.knowledge_files))
        for row, item in enumerate(self.knowledge_files):
            name_item = QTableWidgetItem(item["name"])
            size_item = QTableWidgetItem(self._format_size(item["size"]))
            status_item = QTableWidgetItem(item.get("status", self.tr("Local")))

            name_item.setFlags(name_item.flags() & ~ItemIsEditable)
            size_item.setFlags(size_item.flags() & ~ItemIsEditable)
            status_item.setFlags(status_item.flags() & ~ItemIsEditable)

            self.tableWidgetKnowledge.setItem(row, 0, name_item)
            self.tableWidgetKnowledge.setItem(row, 1, size_item)
            self.tableWidgetKnowledge.setItem(row, 2, status_item)

        self.tableWidgetKnowledge.resizeColumnsToContents()

    def handle_add_knowledge(self):
        """Open a file dialog to add knowledge base documents."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr("Select Knowledge Base Files"),
            "",
            self.file_filter
        )
        if not file_paths:
            return

        for path in file_paths:
            if not os.path.isfile(path):
                continue
            file_name = os.path.basename(path)
            # Skip duplicate entries based on full path.
            if any(f["path"] == path for f in self.knowledge_files):
                continue
            self.knowledge_files.append({
                "name": file_name,
                "path": path,
                "size": os.path.getsize(path),
                "status": self.tr("Local")
            })

        self._refresh_table()

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
