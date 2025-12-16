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
from qgis.PyQt.QtWidgets import QDialog, QMessageBox

from qgis.core import QgsSettings

from .global_defs import *

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
        self.btnApply.clicked.connect(self.handle_click_apply)
        self.btnHelp.clicked.connect(self.handle_click_help)

        gSetting = QgsSettings()
        email = gSetting.value(USER_EMAIL_TAG)
        if email:
            self.lineEdit.setText(email)

        multi_turn = gSetting.value(MULTI_TURN_TAG, "2")
        self.cbChatTurn.setCurrentText(multi_turn)
    def handle_click_ok(self):
        email = self.lineEdit.text()

        gSetting = QgsSettings()
        gSetting.setValue(USER_EMAIL_TAG, email)

        # multi-turn
        chat_turn = self.cbChatTurn.currentText()
        gSetting.setValue(MULTI_TURN_TAG, chat_turn)

        super().accept()

    def handle_click_cancel(self):
        super().reject()

    def handle_click_help(self):
        url = "https://www.phoenix-gis.cn/"
        webbrowser.open(url)

    def handle_click_apply(self):
        email = self.lineEdit.text().strip()

        # check email validation.
        if not email:
            QMessageBox.warning(self, self.tr("Warning"),
                                self.tr("Please enter your email address."),
                                QMessageBox.Ok)
            return

        if "@" not in email or "." not in email:
            QMessageBox.warning(self, self.tr("Warning"),
                                self.tr("Please enter a valid email address."),
                                QMessageBox.Ok)
            return

        try:
            # send email to server
            response = requests.post(
                AI_SERVER_DOMAIN + "/ai/v1/vip/apply",
                json={"email": email},
                timeout=2
            )

            # check response
            if response.status_code == 200:
                QMessageBox.information(self, self.tr("Tip"),
                                        self.tr(
                                            "Your request has been received. We'll get back to you by email within 24 hours. Please check your inbox later."),
                                        QMessageBox.Ok)
            else:
                QMessageBox.warning(self, self.tr("Error"),
                                    self.tr("Failed to submit your request. Please try again later."),
                                    QMessageBox.Ok)

        except requests.exceptions.RequestException as e:
            QMessageBox.critical(self, self.tr("Error"),
                                 self.tr("Network error. Please check your connection and try again."),
                                 QMessageBox.Ok)