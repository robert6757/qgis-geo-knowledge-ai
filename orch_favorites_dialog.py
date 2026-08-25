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
import re

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QListWidgetItem, QMenu, QAction, QFileDialog, QMessageBox, QLabel, QLineEdit
from qgis.core import QgsSettings
from .compat import *
from .global_defs import USER_TOKEN_PARAMS_TAG
from .orch_favorites_manager import OrchFavoritesManager

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'orch_favorites_dialog.ui'))

class OrchFavoritesDialog(QDialog, FORM_CLASS):

    def __init__(self, manager : OrchFavoritesManager, parent=None):
        """Constructor."""
        super(OrchFavoritesDialog, self).__init__(parent)
        self.setupUi(self)

        # Make textEditDetail span two columns so token inputs line up below it.
        self.gridLayout_2.removeWidget(self.textEditDetail)
        self.gridLayout_2.addWidget(self.textEditDetail, 1, 0, 1, 2)

        self.manager = manager
        self.token_input_widgets = []
        self.token_line_edits = {}

        self.btnOK.clicked.connect(self.handle_ok_clicked)
        self.btnCancel.clicked.connect(self.handle_cancel_clicked)
        self.listWidgetFavoritesList.itemClicked.connect(self.handle_list_item_clicked)
        self.listWidgetFavoritesList.itemDoubleClicked.connect(self.handle_list_item_dclicked)
        self.lineEditFilter.textChanged.connect(self.handle_filter_text_changed)
        self.listWidgetFavoritesList.setContextMenuPolicy(CustomContextMenu)
        self.listWidgetFavoritesList.customContextMenuRequested.connect(self.handle_list_context_menu)

        self.all_favorites = []
        for item in self.manager.enum_favorites():
            source = item.get("source", "local")
            display_text = item["task_plan"].original_task
            if source == "server":
                display_text = self.tr("[Server]") + display_text
            else:
                display_text = self.tr("[Local]") + display_text
            self.all_favorites.append({
                "chat_id": item["chat_id"],
                "original_task": item["task_plan"].original_task,
                "source": source
            })
            list_item = QListWidgetItem()
            list_item.setText(display_text)
            list_item.setData(UserRole, item["chat_id"])
            list_item.setData(UserRole + 1, source)
            self.listWidgetFavoritesList.addItem(list_item)

    def get_selected_favorite_chat_id(self):
        return self.selected_chat_id

    def _save_token_to_settings(self, token_name):
        """Persist the token value for token_name to QGIS settings."""
        line_edit = self.token_line_edits.get(token_name)
        if line_edit is None:
            return
        user_token = line_edit.text().strip()
        gSetting = QgsSettings()
        gSetting.setValue(USER_TOKEN_PARAMS_TAG + f"/{token_name}", user_token)

    def _check_tokens_filled(self):
        """Return the first empty token name, or None if all are filled."""
        for token_name, line_edit in self.token_line_edits.items():
            if not line_edit.text().strip():
                return token_name
        return None

    def _show_token_missing_warning(self, token_name):
        """Show a warning telling the user which auth token is missing."""
        QMessageBox.warning(
            self,
            self.tr("Missing Auth Token"),
            self.tr("Please enter the auth token for '{0}' before continuing.").format(token_name),
            QMessageBoxOK
        )

    def _clear_token_input_widgets(self):
        """Remove any previously created token input rows."""
        for widgets in self.token_input_widgets:
            for widget in widgets:
                self.gridLayout_2.removeWidget(widget)
                widget.deleteLater()
        self.token_input_widgets = []
        self.token_line_edits = {}

    def handle_ok_clicked(self):
        selected_items = self.listWidgetFavoritesList.selectedItems()
        if len(selected_items) > 0:
            self.selected_chat_id = selected_items[0].data(UserRole)

        empty_token = self._check_tokens_filled()
        if empty_token is not None:
            self._show_token_missing_warning(empty_token)
            return

        super().accept()

    def handle_cancel_clicked(self):
        self.selected_chat_id = 0
        super().close()

    def handle_list_item_clicked(self, list_item):
        if list_item is None:
            return

        chat_id = list_item.data(UserRole)
        favorite = self.manager.retrieve_favorite(chat_id, inject_variables=False)
        if favorite is None or favorite.get("task_plan") is None:
            self.textEditDetail.setPlainText("")
            self._clear_token_input_widgets()
            return

        task_plan = favorite["task_plan"]
        detail_lines = [task_plan.original_task]

        sub_task_id = 1
        for sub_task in task_plan.sub_tasks:
            detail_lines.append("")
            detail_lines.append(f"{sub_task_id}.{sub_task.name}")
            detail_lines.append(f"{sub_task.description}")
            sub_task_id += 1

        self.textEditDetail.setPlainText("\n".join(detail_lines))

        self._clear_token_input_widgets()
        detail_text = "\n".join(detail_lines)
        token_names = list(dict.fromkeys(re.findall(r"\[AUTH_TOKEN:(.*?)\]", detail_text)))
        base_row = self.gridLayout_2.rowCount()
        for idx, token_name in enumerate(token_names):
            label = QLabel(f"{token_name} Auth Token: ", self)
            line_edit = QLineEdit(self)
            line_edit.setPlaceholderText(self.tr("Enter token"))

            gSetting = QgsSettings()
            saved_token = gSetting.value(USER_TOKEN_PARAMS_TAG + f"/{token_name}", "")
            if saved_token:
                line_edit.setText(saved_token)

            line_edit.editingFinished.connect(
                lambda name=token_name: self._save_token_to_settings(name)
            )

            row = base_row + idx
            self.gridLayout_2.addWidget(label, row, 0)
            self.gridLayout_2.addWidget(line_edit, row, 1)
            self.token_input_widgets.append((label, line_edit))
            self.token_line_edits[token_name] = line_edit

    def handle_list_item_dclicked(self, list_item):
        if list_item is None:
            return

        self.selected_chat_id = list_item.data(UserRole)

        empty_token = self._check_tokens_filled()
        if empty_token is not None:
            self._show_token_missing_warning(empty_token)
            return

        super().accept()

    def handle_filter_text_changed(self, text):
        """Filter favorites list based on the text in the filter line edit."""
        filter_text = text.lower()
        self.listWidgetFavoritesList.clear()

        for item in self.all_favorites:
            if not filter_text or filter_text in item["original_task"].lower():
                source = item.get("source", "local")
                display_text = item["original_task"]
                if source == "server":
                    display_text = self.tr("[Server]") + display_text
                else:
                    display_text = self.tr("[Local]") + display_text
                list_item = QListWidgetItem()
                list_item.setText(display_text)
                list_item.setData(UserRole, item["chat_id"])
                list_item.setData(UserRole + 1, source)
                self.listWidgetFavoritesList.addItem(list_item)

    def handle_list_context_menu(self, pos):
        """Show context menu for the favorites list to remove/export/import a favorite."""
        list_item = self.listWidgetFavoritesList.itemAt(pos)

        menu = QMenu(self)

        import_action = QAction("Import", self)
        import_action.triggered.connect(self.import_favorite_item)
        menu.addAction(import_action)

        if list_item is not None:
            self.listWidgetFavoritesList.setCurrentItem(list_item)

            export_action = QAction("Export", self)
            export_action.triggered.connect(lambda: self.export_favorite_item(list_item))
            menu.addAction(export_action)

            source = list_item.data(UserRole + 1)
            if source != "server":
                remove_action = QAction("Remove", self)
                remove_action.triggered.connect(lambda: self.remove_favorite_item(list_item))
                menu.addAction(remove_action)

        menu.exec(self.listWidgetFavoritesList.viewport().mapToGlobal(pos))

    def export_favorite_item(self, list_item):
        """Export a favorite task plan to a JSON file."""
        chat_id = list_item.data(UserRole)
        favorite = self.manager.retrieve_favorite(chat_id, inject_variables=True)
        if favorite is None or favorite.get("task_plan") is None:
            return

        original_task = favorite["task_plan"].original_task or "task_plan"
        default_name = re.sub(r'[^\w\-_. ]+', '', original_task).strip().replace(' ', '_')[:50] or "task_plan"
        default_name += ".json"

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export Task Plan"),
            default_name,
            self.tr("JSON files (*.json)")
        )
        if not filepath:
            return

        if self.manager.export_task_plan_to_json(filepath, chat_id):
            QMessageBox.information(self, self.tr("Tip"),
                                    self.tr("Task plan exported successfully."),
                                    QMessageBoxOK)
        else:
            QMessageBox.warning(self, self.tr("Error"),
                              self.tr("Failed to export task plan."),
                              QMessageBoxOK)

    def import_favorite_item(self):
        """Import a task plan from a JSON file and add it to favorites."""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import Task Plan"),
            "",
            self.tr("JSON files (*.json)")
        )
        if not filepath:
            return

        new_chat_id = self.manager.import_task_plan_from_json(filepath)
        if new_chat_id is None:
            QMessageBox.warning(self, self.tr("Error"),
                              self.tr("Failed to import task plan. Please check the file format."),
                              QMessageBoxOK)
            return

        favorite = self.manager.retrieve_favorite(new_chat_id, inject_variables=False)
        if favorite is None or favorite.get("task_plan") is None:
            return

        original_task = favorite["task_plan"].original_task
        source = favorite.get("source", "local")
        self.all_favorites.append({
            "chat_id": new_chat_id,
            "original_task": original_task,
            "source": source
        })

        display_text = original_task
        if source == "server":
            display_text = self.tr("[Server]") + display_text
        else:
            display_text = self.tr("[Local]") + display_text
        list_item = QListWidgetItem()
        list_item.setText(display_text)
        list_item.setData(UserRole, new_chat_id)
        list_item.setData(UserRole + 1, source)
        self.listWidgetFavoritesList.addItem(list_item)
        self.listWidgetFavoritesList.setCurrentItem(list_item)
        self.handle_list_item_clicked(list_item)

        QMessageBox.information(self, self.tr("Tip"),
                                self.tr("Task plan imported successfully."),
                                QMessageBoxOK)

    def remove_favorite_item(self, list_item):
        """Remove a favorite by its list item and update the manager/list."""
        chat_id = list_item.data(UserRole)
        reply = QMessageBox.question(
            self,
            self.tr("Confirm Delete"),
            self.tr("Are you sure you want to remove this favorite task?"),
            QMessageBoxYes | QMessageBoxNo,
            QMessageBoxNo
        )
        if reply != QMessageBoxYes:
            return

        if self.manager.remove_favorite(chat_id):
            self.all_favorites = [
                item for item in self.all_favorites if item["chat_id"] != chat_id
            ]
            row = self.listWidgetFavoritesList.row(list_item)
            self.listWidgetFavoritesList.takeItem(row)
            self.textEditDetail.setPlainText("")
            self._clear_token_input_widgets()
