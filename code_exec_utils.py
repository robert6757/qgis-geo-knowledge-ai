# -*- coding: utf-8 -*-
"""
/***************************************************************************
                           Code Execution Utilities
   Shared utility functions for loading the code_execution module.
                               -------------------
        begin                : 2026-05-17
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
import sys

from qgis.core import QgsBlockingNetworkRequest
from qgis.PyQt.QtCore import QCoreApplication, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.PyQt.QtWidgets import QMessageBox, QWidget
from global_defs import *

from .compat import *

def get_code_execution_class():
    """
    Dynamically load the CodeExecution class.

    Returns:
        CodeExecution class if available, None otherwise.
    """
    try:
        from .code_execution import CodeExecution
        return CodeExecution
    except ImportError:
        return None

def ensure_code_execution(parent_widget: QWidget = None):
    """
    Try to get CodeExecution class, prompt user to download if missing.

    Args:
        parent_widget: Optional parent widget for dialog. If provided,
                       its tr() method will be used for i18n.

    Returns:
        CodeExecution class if available, None if unavailable or user cancels.
    """
    CodeExecution = get_code_execution_class()
    if CodeExecution is not None:
        return CodeExecution

    # Ask user whether to download
    msg_box = QMessageBox(parent_widget)
    msg_box.setIcon(QMessageBoxQuestion)
    msg_box.setWindowTitle("Geo Knowledge AI")
    msg_box.setText(QCoreApplication.translate("GeoKnowledgeAIDockWidget", """In order to enhance running safety, QGIS disallows automatically running external code (e.g., LLM-generated real-time code).\n\nIf you want to execute code automatically, please press "Yes". The Geo Knowledge AI plugin will download the execution module to start the automated process.\n\nCAUTION: Despite our STRICT restrictions on LLMs, the generated code is not completely reliable. Please check it carefully. We suggest you back up your data and QGIS project before executing code."""))
    yes_btn = msg_box.addButton(QCoreApplication.translate("GeoKnowledgeAIDockWidget","Yes"), QMessageBoxYesRole)
    msg_box.addButton(QCoreApplication.translate("GeoKnowledgeAIDockWidget","No"), QMessageBoxNoRole)
    msg_box.setDefaultButton(yes_btn)
    msg_box.exec()

    if msg_box.clickedButton() != yes_btn:
        return None

    # Download code_execution.py from GitHub
    url = f"{AI_SERVER_DOMAIN}/qgis-plugins/geo-knowledge-ai/code_execution.py"
    plugin_dir = os.path.dirname(__file__)
    target_path = os.path.join(plugin_dir, "code_execution.py")

    try:
        q_request = QNetworkRequest(QUrl(url))
        q_nw = QgsBlockingNetworkRequest()
        err_code = q_nw.get(q_request)
        q_reply = q_nw.reply()
        if err_code == QgsBlockingNetworkRequest.NoError and q_reply:
            content = q_reply.content()
            with open(target_path, 'wb') as f:
                f.write(content.data())
        else:
            raise Exception(f"QgsBlockingNetworkRequest failed with error code: {err_code}")

        # Clear any cached import of this module
        for mod_name in list(sys.modules.keys()):
            if 'code_execution' in mod_name:
                del sys.modules[mod_name]

        CodeExecution = get_code_execution_class()
        if CodeExecution is None:
            QMessageBox.critical(parent_widget, QCoreApplication.translate("GeoKnowledgeAIDockWidget","Error"),
                                 QCoreApplication.translate("GeoKnowledgeAIDockWidget","Failed to load the downloaded code execution module"))
            return None
        return CodeExecution

    except Exception as e:
        QMessageBox.critical(parent_widget, QCoreApplication.translate("GeoKnowledgeAIDockWidget","Error"),
                             QCoreApplication.translate("GeoKnowledgeAIDockWidget","Failed to download code execution module: {}").format(str(e)))
        return None