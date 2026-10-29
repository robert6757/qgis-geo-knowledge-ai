# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Verify Dialog
  A dialog for sending and confirming an email verification code.
                              -------------------
        begin                : 2026-10-19
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

import requests

from qgis.PyQt.QtCore import QRegularExpression, QSettings
from qgis.PyQt.QtGui import QRegularExpressionValidator
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
)

from .global_defs import AI_SERVER_DOMAIN, CLIENT_TOKEN_TAG
from .compat import QMessageBoxOK
from .global_utils import get_qgis_proxies


class VerifyDialog(QDialog):
    """Dialog for sending and confirming an email verification code."""

    def __init__(self, email, parent=None):
        super(VerifyDialog, self).__init__(parent)
        self.email = email
        self.setWindowTitle(self.tr("Geo Knowledge AI Email Verification"))
        self.resize(360, 100)

        layout = QVBoxLayout(self)

        tip_layout = QVBoxLayout()
        self.tip_label = QLabel(self.tr("Your verification code is valid for 5 minutes. Please check your inbox or spam folder."))
        self.tip_label.setWordWrap(True)
        tip_layout.addWidget(self.tip_label)

        code_layout = QHBoxLayout()
        code_layout.addWidget(QLabel(self.tr("Verification Code:")))
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText(self.tr("6-digit code"))
        self.code_edit.setMaxLength(6)
        six_digit_regex = QRegularExpression("^[0-9]{6}$")
        self.code_edit.setValidator(QRegularExpressionValidator(six_digit_regex, self))
        code_layout.addWidget(self.code_edit)

        self.btn_verify = QPushButton(self.tr("OK"))
        code_layout.addWidget(self.btn_verify)

        layout.addLayout(tip_layout)
        layout.addLayout(code_layout)

        self.btn_verify.clicked.connect(self.handle_verify_code)

    def _show_error(self, message):
        QMessageBox.critical(self, self.tr("Error"), message, QMessageBoxOK)

    def _show_info(self, message):
        QMessageBox.information(self, self.tr("Success"), message, QMessageBoxOK)

    def handle_verify_code(self):
        code = self.code_edit.text().strip()
        if not code or len(code) != 6 or not code.isdigit():
            self._show_error(self.tr("Please enter a valid 6-digit verification code."))
            return

        url = f"{AI_SERVER_DOMAIN}/ai/v1/verify/email/confirm"
        payload = {"email": self.email, "code": code}
        try:
            response = requests.post(
                url,
                json=payload,
                proxies=get_qgis_proxies(),
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and data.get("code") == 0:
                    client_token = data.get("client_token")
                    if client_token:
                        QSettings().setValue(CLIENT_TOKEN_TAG, client_token)
                        self._show_info(self.tr("Email verified successfully."))
                        self.accept()
                    else:
                        self._show_error(
                            self.tr("Failed to verify email: missing client token.")
                        )
                else:
                    self._show_error(
                        self.tr("Failed to verify email: {error}").format(
                            error=self._extract_response_error(response))
                    )
            else:
                self._show_error(
                    self.tr("Failed to verify email: {error}").format(
                        error=self._extract_response_error(response))
                )
        except Exception as e:
            self._show_error(
                self.tr("Failed to verify email: {error}").format(error=str(e))
            )

    @staticmethod
    def _extract_response_error(response):
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
