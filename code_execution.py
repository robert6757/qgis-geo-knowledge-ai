# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Code Execution
  a class implemented executing an external code.
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

from qgis.PyQt.QtCore import pyqtSignal, QObject
import io
import traceback
from contextlib import redirect_stdout

class CodeExecution(QObject):
    """a background task that executes python code，"""

    task_finished = pyqtSignal(str)
    task_error = pyqtSignal(str, str)

    def __init__(self, code, parent_widget, iface):
        super().__init__(parent_widget)
        self.code = code
        self.parent_widget = parent_widget
        self.iface = iface

    def run(self):
        """run this code"""
        try:
            import qgis
            import math
            import re
            import types
            import os
            import sys

            safe_globals = {
                'iface': self.iface,
                'project': qgis.core.QgsProject.instance(),
                'print': print,
                'math': math,
                're': re,
                'os': os,
                'sys': sys,
                'processing': qgis.processing,
                'qgis': qgis,
                'QtCore': qgis.QtCore
            }

            for module in [qgis.core]:
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
