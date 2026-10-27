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
from qgis.PyQt.QtCore import QDateTime
from qgis.PyQt.QtGui import QIcon, QPixmap
from qgis.PyQt.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QDialog,
)

from qgis.core import QgsSettings

from .global_defs import *
from .compat import *
from .global_utils import get_qgis_proxies, get_auth_headers
from .verify_dialog import VerifyDialog

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
        self.btnSendCode.clicked.connect(self.handle_click_send_code)
        self.btnClearCode.clicked.connect(self.handle_click_clear_code)
        self.btnHelp.clicked.connect(self.handle_click_help)
        self.btnSelFolder.clicked.connect(self.handle_click_select_folder)
        self.btnOutputAuditFilePath.clicked.connect(self.handle_click_select_audit_output_path)
        self.btnExportAuditLogs.clicked.connect(self.handle_click_export_audit_logs)
        self.labelEnterprise.linkActivated.connect(self.handle_label_enterprise_link_clicked)

        gSetting = QgsSettings()
        email = gSetting.value(USER_EMAIL_TAG)
        if email:
            self.lineEdit.setText(email)

        temp_folder = gSetting.value(TEMP_FOLDER_TAG)
        if temp_folder:
            self.lineEditTempFolderPath.setText(temp_folder)

        client_token = gSetting.value(CLIENT_TOKEN_TAG)
        if client_token:
            self._verify_client_token(email, client_token)

        multi_turn = gSetting.value(MULTI_TURN_TAG, "3")
        self.cbChatTurn.setCurrentText(multi_turn)

        self._init_audit_logs_datetime()
        self._update_credits_label(email)

    def _verify_client_token(self, email, client_token):
        """Validate the stored client token with the server."""
        url = f"{AI_SERVER_DOMAIN}/ai/v1/verify/client/token"
        payload = {"token": client_token, "email": email}
        try:
            response = requests.post(
                url,
                json=payload,
                proxies=get_qgis_proxies(),
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and data.get("code") == 0 and data.get("valid"):
                    self.labelVerificationStatus.setPixmap(QPixmap(":/plugins/geo_knowledge_ai/image/verified.svg"))
                    self.labelVerificationStatus.setToolTip(self.tr("Email has been verified."))
        except Exception:
            pass

    def _update_credits_label(self, email):
        """Fetch user info and update the credits label."""
        fallback_text = self.tr("Credits Left: -- (Resets in --).")
        user_id = QgsSettings().value(USER_ID_TAG, "")
        if not user_id:
            self.labelCredits.setText(fallback_text)
            return

        try:
            url = f"{AI_SERVER_DOMAIN}/ai/v1/userinfo?user_id={user_id}"
            if email:
                url += f"&email={email}"
            response = requests.get(
                url,
                proxies=get_qgis_proxies(),
                timeout=10
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
                self.groupBox.setTitle(self.tr("Current Plan: Solo Engineer"))
            elif plan == 2:
                self.groupBox.setTitle(self.tr("Current Plan: Studio"))
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

    def handle_click_clear_code(self):
        """Clear the email and client token locally and notify the server."""
        gSetting = QgsSettings()
        token = gSetting.value(CLIENT_TOKEN_TAG, "")

        # Clear local UI and settings immediately
        self.lineEdit.clear()
        gSetting.setValue(CLIENT_TOKEN_TAG, "")
        gSetting.setValue(USER_EMAIL_TAG, "")
        self.labelVerificationStatus.setPixmap(
            QPixmap(":/plugins/geo_knowledge_ai/image/unverified.svg")
        )
        self.labelVerificationStatus.setToolTip(self.tr("Email not verified."))

        if not token:
            return

        url = f"{AI_SERVER_DOMAIN}/ai/v1/verify/client/token/clear"
        payload = {"token": token}
        try:
            response = requests.post(
                url,
                json=payload,
                proxies=get_qgis_proxies(),
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if not (isinstance(data, dict) and data.get("code") == 0 and data.get("cleared")):
                    error_msg = self._extract_server_error_message(response)
                    QMessageBox.warning(
                        self,
                        self.tr("Error"),
                        self.tr("Server returned: {error}").format(error=error_msg),
                        QMessageBoxOK
                    )
            else:
                error_msg = self._extract_server_error_message(response)
                QMessageBox.critical(
                    self,
                    self.tr("Error"),
                    self.tr("Server returned: {error}").format(error=error_msg),
                    QMessageBoxOK
                )
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr("Server returned: {error}").format(error=str(e)),
                QMessageBoxOK
            )

    def handle_click_send_code(self):
        """Send verification code and open confirmation dialog on success."""
        email = self.lineEdit.text().strip()
        if not email:
            QMessageBox.warning(
                self,
                self.tr("Warning"),
                self.tr("Please enter the email used to purchase the Plan before verifying."),
                QMessageBoxOK
            )
            return

        url = f"{AI_SERVER_DOMAIN}/ai/v1/verify/email/send"
        payload = {"email": email}
        try:
            response = requests.post(
                url,
                json=payload,
                proxies=get_qgis_proxies(),
                timeout=30
            )
            if response.status_code == 200:
                QMessageBox.information(
                    self,
                    self.tr("Success"),
                    self.tr("Verification code sent successfully."),
                    QMessageBoxOK
                )
            else:
                error_msg = self._extract_server_error_message(response)
                QMessageBox.critical(
                    self,
                    self.tr("Error"),
                    self.tr("Failed to send verification code: {error}").format(error=error_msg),
                    QMessageBoxOK
                )
                return
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr("Failed to send verification code: {error}").format(error=str(e)),
                QMessageBoxOK
            )
            return

        verify_dlg = VerifyDialog(email, self)
        if verify_dlg.exec() == Accepted:
            # use the stripped email
            self.lineEdit.setText(email)
            self.labelVerificationStatus.setPixmap(
                QPixmap(":/plugins/geo_knowledge_ai/image/verified.svg")
            )
            self.labelVerificationStatus.setToolTip(self.tr("Email has been verified."))


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

    def _init_audit_logs_datetime(self):
        """Initialize audit logs datetime range: from yesterday to now."""
        now = QDateTime.currentDateTime()
        one_day_ago = now.addDays(-1)
        display_format = "yyyy-MM-dd HH:mm:ss"
        self.dateTimeEditFromAuditLogs.setDisplayFormat(display_format)
        self.dateTimeEditToAuditLogs.setDisplayFormat(display_format)
        self.dateTimeEditFromAuditLogs.setDateTime(one_day_ago)
        self.dateTimeEditToAuditLogs.setDateTime(now)

    def _format_utc_qdatetime(self, qdt):
        """Convert local QDateTime to UTC ISO-8601 string."""
        return qdt.toUTC().toString("yyyy-MM-ddTHH:mm:ssZ")

    def handle_click_select_audit_output_path(self):
        """Choose a .zip file path to save exported audit logs."""
        initial_path = self.lineEditAuditLogsFilePath.text()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Select Audit Logs Export Path"),
            initial_path,
            self.tr("ZIP files (*.zip)")
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".zip"):
            file_path += ".zip"
        self.lineEditAuditLogsFilePath.setText(file_path)

    def _extract_server_error_message(self, response):
        """Extract readable error message from server response."""
        try:
            data = response.json()
            if isinstance(data, dict):
                return (data.get("detail")
                        or data.get("message")
                        or data.get("error")
                        or str(data))
            return response.text
        except Exception:
            return response.text

    def handle_click_export_audit_logs(self):
        """Export workflow audit logs by time range via GET request."""
        email = self.lineEdit.text().strip()
        if not email:
            QMessageBox.warning(
                self,
                self.tr("Warning"),
                self.tr("Please enter the email used to purchase the Plan before exporting."),
                QMessageBoxOK
            )
            return

        output_path = self.lineEditAuditLogsFilePath.text().strip()
        if not output_path:
            QMessageBox.warning(
                self,
                self.tr("Warning"),
                self.tr("Please select the export file path first."),
                QMessageBoxOK
            )
            return

        from_time = self._format_utc_qdatetime(self.dateTimeEditFromAuditLogs.dateTime())
        to_time = self._format_utc_qdatetime(self.dateTimeEditToAuditLogs.dateTime())

        url = f"{AI_SERVER_DOMAIN}/ai/v1/audit/logs/export"
        params = {
            "email": email,
            "from": from_time,
            "to": to_time,
        }

        try:
            response = requests.get(
                url,
                params=params,
                headers=get_auth_headers(),
                proxies=get_qgis_proxies(),
                timeout=60
            )
            if response.status_code != 200:
                error_msg = self._extract_server_error_message(response)
                QMessageBox.critical(
                    self,
                    self.tr("Error"),
                    self.tr("Failed to export audit logs: {error}").format(error=error_msg),
                    QMessageBoxOK
                )
                return

            with open(output_path, "wb") as f:
                f.write(response.content)

            QMessageBox.information(
                self,
                self.tr("Success"),
                self.tr("Audit logs exported successfully to {path}.").format(path=output_path),
                QMessageBoxOK
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr("Failed to export audit logs: {error}").format(error=str(e)),
                QMessageBoxOK
            )
