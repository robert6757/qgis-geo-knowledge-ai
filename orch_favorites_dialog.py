# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Orchestration Favorites Dialog
  This is a dialog box that displays and loads the Orchestration favorites.
                              -------------------
        begin                : 2026-08-19
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
from qgis.PyQt.QtWidgets import QListWidgetItem
from .compat import *
from .orch_favorites_manager import OrchFavoritesManager

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'orch_favorites_dialog.ui'))

class OrchFavoritesDialog(QDialog, FORM_CLASS):

    def __init__(self, manager : OrchFavoritesManager, parent=None):
        """Constructor."""
        super(OrchFavoritesDialog, self).__init__(parent)
        self.setupUi(self)

        self.manager = manager
        self.btnOK.clicked.connect(self.handle_ok_clicked)
        self.btnCancel.clicked.connect(self.handle_cancel_clicked)
        self.listWidgetFavoritesList.itemDoubleClicked.connect(self.handle_list_item_dclicked)

        for item in self.manager.enum_favorites():
            list_item = QListWidgetItem()
            list_item.setText(item["task_plan"].original_task)
            list_item.setData(UserRole, item["chat_id"])
            self.listWidgetFavoritesList.addItem(list_item)

    def get_selected_favorite_timestamp(self):
        return self.selected_timestamp

    def handle_ok_clicked(self):
        selected_items = self.listWidgetFavoritesList.selectedItems()
        if len(selected_items) > 0:
            self.selected_timestamp = selected_items[0].data(UserRole)

        super().accept()

    def handle_cancel_clicked(self):
        self.selected_timestamp = 0
        super().close()

    def handle_list_item_dclicked(self, list_item):
        if list_item is None:
            return

        self.selected_timestamp = list_item.data(UserRole)
        super().accept()
