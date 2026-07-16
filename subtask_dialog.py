# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Subtask Dialog
  A dialog that allows the user to modify subtask in orchestration.
                              -------------------
        begin                : 2026-04-30
        copyright            : (C) 2026 by phoenix-gis
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
import json

from qgis.PyQt import uic

from .compat import *
from .orch_manager import SubTask

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'subtask_dialog.ui'))

class SubtaskDialog(QDialog, FORM_CLASS):

    def __init__(self, subtask: SubTask, parent=None):
        """Constructor."""
        super(SubtaskDialog, self).__init__(parent)
        self.setupUi(self)

        self.btnOK.clicked.connect(self.handle_click_ok)
        self.btnCancel.clicked.connect(self.handle_click_cancel)

        self.modified_prompt = subtask.description

        # update ui
        self.lineEditName.setText(subtask.name)
        self.lineEditStatus.setText(subtask.status.value)
        self.textEditResult.setText(subtask.result)
        self.textEditPrompt.setText(subtask.description)

    def handle_click_ok(self):
        self.modified_prompt = self.textEditPrompt.toPlainText()
        super().accept()

    def handle_click_cancel(self):
        super().reject()

    def get_modified_prompt(self):
        return self.modified_prompt