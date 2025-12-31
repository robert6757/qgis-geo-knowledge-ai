# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Code Execution
  A QGIS task which provides executing an external code.
                              -------------------
        begin                : 2025-12-31
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

from qgis.core import QgsTask
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtCore import pyqtSignal
import traceback
import io
from contextlib import redirect_stdout

class CodeExecutionTask(QgsTask):
    """a background task that executes python code，"""

    task_finished = pyqtSignal(str)
    task_error = pyqtSignal(str, str)

    def __init__(self, description, code, parent_widget, iface):
        super().__init__(description, QgsTask.CanCancel)
        self.code = code
        self.parent_widget = parent_widget
        self.iface = iface

    def run(self):
        """run in new thread"""
        try:
            import qgis.core
            import qgis.gui
            import qgis.PyQt.QtCore
            import qgis.PyQt.QtWidgets
            import qgis.PyQt.QtGui

            safe_globals = {
                'iface': self.iface,
                'QgsProject': qgis.core.QgsProject,
                'project': qgis.core.QgsProject.instance(),
                'print': print,
            }

            # inject common modules.
            for module in [qgis.core, qgis.gui, qgis.PyQt.QtCore, qgis.PyQt.QtWidgets, qgis.PyQt.QtGui]:
                safe_globals.update(module.__dict__)

            output_buffer = io.StringIO()

            # redirect output stream
            with redirect_stdout(output_buffer):
                exec(self.code, safe_globals)

            output = output_buffer.getvalue()
            output_buffer.close()

            self.task_finished.emit(output)

            return True

        except SyntaxError as e:
            error_type = self.tr("SyntaxError")
            error_msg = f"{type(e).__name__}: {e.msg}\nLine {e.lineno}: {e.text}"
            self.task_error.emit(error_type, error_msg)
            return False

        except Exception as e:
            error_type = self.tr("RuntimeError")
            error_msg = f"{type(e).__name__}: {str(e)}"
            self.task_error.emit(error_type, error_msg)
            return False
