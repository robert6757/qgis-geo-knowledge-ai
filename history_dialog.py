# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 History Dialog
  A dialog shows the history of chat.
                              -------------------
        begin                : 2025-10-31
        copyright            : (C) 2025 by phoenix-gis
        email                : phoenixgis@sina.com
        website              : phoenix-gis.cn
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
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QListWidgetItem, QMessageBox

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'history_dialog.ui'))


class HistoryDialog(QDialog, FORM_CLASS):

    def __init__(self, history_manager, parent=None):
        """Constructor."""
        super(HistoryDialog, self).__init__(parent)
        self.setupUi(self)

        self.manager = history_manager
        self.selected_timestamp = 0
        self.btnOpen.clicked.connect(self.handle_open_clicked)
        self.btnCancel.clicked.connect(self.handle_cancel_clicked)
        self.clearBtn.clicked.connect(self.handle_clear_clicked)
        self.listWidget.itemDoubleClicked.connect(self.handle_list_item_dclicked)

        for question_item in self.manager.enum_question():
            list_item = QListWidgetItem()
            list_item.setText(question_item["question"])
            list_item.setData(Qt.UserRole, question_item["timestamp"])
            self.listWidget.addItem(list_item)

    def get_selected_history_timestamp(self):
        return self.selected_timestamp

    def handle_open_clicked(self):
        selected_items = self.listWidget.selectedItems()
        if len(selected_items) > 0:
            self.selected_timestamp = selected_items[0].data(Qt.UserRole)

        super().accept()

    def handle_cancel_clicked(self):
        self.selected_timestamp = 0
        super().close()

    def handle_clear_clicked(self):
        if QMessageBox.Yes != QMessageBox.question(self, self.tr("Delete All Chat History"),
                                                   self.tr("Are you sure you want to delete all chat history?")):
            return

        self.manager.clear_history()
        self.listWidget.clear()

    def handle_list_item_dclicked(self, list_item):
        if list_item is None:
            return

        self.selected_timestamp = list_item.data(Qt.UserRole)
        super().accept()
