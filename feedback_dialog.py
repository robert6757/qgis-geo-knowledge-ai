# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Feedback Dialog
  A dialog for users to submit feedback issues to the server.
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
import requests

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QMessageBox
from .compat import *
from .global_defs import AI_SERVER_DOMAIN

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'feedback_dialog.ui'))


class FeedbackDialog(QDialog, FORM_CLASS):

    def __init__(self, chat_id, parent=None):
        """Constructor."""
        super(FeedbackDialog, self).__init__(parent)
        self.setupUi(self)

        self.chat_id = chat_id
        self.btnSubmit.clicked.connect(self.handle_submit_clicked)
        self.btnCancel.clicked.connect(self.handle_cancel_clicked)

        self.issue = ""
        self.email = ""

    def handle_submit_clicked(self):
        issue = self.textEditIssue.toPlainText().strip()
        email = self.lineEditEmail.text().strip()

        if not issue:
            QMessageBox.warning(self, self.tr("Warning"),
                              self.tr("Please describe your issue before submitting."),
                              QMessageBoxOK)
            return

        self.issue = issue
        self.email = email

        super().accept()

    def handle_cancel_clicked(self):
        super().close()

    def get_feedback(self):
        return self.issue, self.email
