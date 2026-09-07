# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Setting Dialog
  A dialog that allows the user to modify global parameters.
                              -------------------
        begin                : 2025-10-10
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
import requests
import webbrowser

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QFileDialog

from qgis.core import QgsSettings

from .global_defs import *
from .compat import *

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'setting_dialog.ui'))

class SettingDialog(QDialog, FORM_CLASS):

    def __init__(self, iface, parent=None):
        """Constructor."""
        super(SettingDialog, self).__init__(parent)
        self.setupUi(self)

        self.iface = iface

        self.btnOK.clicked.connect(self.handle_click_ok)
        self.btnCancel.clicked.connect(self.handle_click_cancel)
        self.btnHelp.clicked.connect(self.handle_click_help)
        self.btnSelFolder.clicked.connect(self.handle_click_select_folder)
        self.labelEnterprise.linkActivated.connect(self.handle_label_enterprise_link_clicked)

        gSetting = QgsSettings()
        email = gSetting.value(USER_EMAIL_TAG)
        if email:
            self.lineEdit.setText(email)

        temp_folder = gSetting.value(TEMP_FOLDER_TAG)
        if temp_folder:
            self.lineEditTempFolderPath.setText(temp_folder)

        multi_turn = gSetting.value(MULTI_TURN_TAG, "3")
        self.cbChatTurn.setCurrentText(multi_turn)

        self._update_credits_label()

    def _update_credits_label(self):
        """Fetch user info and update the credits label."""
        fallback_text = self.tr("Credits Left: -- (Resets in --).")
        user_id = QgsSettings().value(USER_ID_TAG, "")
        if not user_id:
            self.labelCredits.setText(fallback_text)
            return

        try:
            response = requests.get(
                f"{AI_SERVER_DOMAIN}/ai/v1/userinfo?user_id={user_id}",
                timeout=2
            )
            if response.status_code != 200:
                self.labelCredits.setText(fallback_text)
                return

            data = response.json()
            credits = data.get("credits")
            reset_seconds = data.get("reset_remaining_seconds")
            plan = data.get("plan")
            if credits is None or reset_seconds is None:
                raise ValueError(self.tr("Missing required fields in response"))

            if plan == 0:
                self.groupBox.setTitle(self.tr("Current Plan: Free"))
            elif plan == 1:
                self.groupBox.setTitle(self.tr("Current Plan: Enterprise"))
            else:
                self.groupBox.setTitle(self.tr("Current Plan: --"))

            minutes = reset_seconds // 60
            self.labelCredits.setText(
                self.tr("Credits Left: {credits} (Resets in {minutes}m).").format(
                    credits=max(0, credits), minutes=minutes)
            )
        except Exception:
            self.labelCredits.setText(fallback_text)

    def handle_click_ok(self):
        email = self.lineEdit.text()
        temp_folder = self.lineEditTempFolderPath.text()

        gSetting = QgsSettings()
        gSetting.setValue(USER_EMAIL_TAG, email)
        gSetting.setValue(TEMP_FOLDER_TAG, temp_folder)

        # multi-turn
        chat_turn = self.cbChatTurn.currentText()
        gSetting.setValue(MULTI_TURN_TAG, chat_turn)

        super().accept()

    def handle_click_cancel(self):
        super().reject()

    def handle_click_help(self):
        url = "https://www.geoknowledgeai.com"
        webbrowser.open(url)

    def handle_label_enterprise_link_clicked(self, url):
        webbrowser.open(url)

    def handle_click_select_folder(self):
        # Get the current path from lineEdit as starting directory
        initial_path = self.lineEditTempFolderPath.text()

        temp_folder_path = QFileDialog.getExistingDirectory(
            self, 
            self.tr("Select Temporary Folder"), 
            initial_path
        )
        if not temp_folder_path:
            return
        self.lineEditTempFolderPath.setText(temp_folder_path)
