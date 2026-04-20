# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Network for Orchestration
 This is subclass of QThread which support network for orchestration.
                              -------------------
        begin                : 2026-04-17
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

import json
from qgis.PyQt.QtCore import QThread, pyqtSignal, QUrl
from qgis.PyQt.QtNetwork import QNetworkAccessManager

from .global_defs import *
from .compat import *

class CTOrchNetwork(QThread):

    # defines signals.
    # receive content signal.
    content_received = pyqtSignal(str)
    # report error signal.
    error_occurred = pyqtSignal(str)

    def __init__(self, request_data, orch_type: int):
        super().__init__()
        self.request_data = request_data
        self.reply = None
        self.received_chunks = 0
        self.buffer = ""
        self.network_manager = None
        # 1: decompose task 2:tool calls 3:conclusion 0: unknown
        self.orch_type = orch_type

    def run(self):
        """execute request"""

        self.network_manager = QNetworkAccessManager()

        try:
            url = AI_SERVER_DOMAIN
            if self.orch_type == 1:
                url += "/ai/v1/orch/decompose"
            elif self.orch_type == 2:
                url += "/ai/v1/orch/tools"
            elif self.orch_type == 3:
                url += "/ai/v1/orch/conclusion"
            else:
                raise ValueError(f"Unknown orch_type: {self.orch_type}")

            # create network request.
            request = QNetworkRequest(QUrl(url))
            request.setHeader(ContentTypeHeader, "application/json")
            request.setRawHeader(b"Accept", b"text/event-stream")

            # send post reqeust.
            json_data = json.dumps(self.request_data).encode('utf-8')
            self.reply = self.network_manager.post(request, json_data)

            # connect read slots.
            self.reply.readyRead.connect(self.on_ready_read, type=DirectConnection)
            self.reply.finished.connect(self.on_finished, type=DirectConnection)
            self.reply.errorOccurred.connect(self.on_error, type=DirectConnection)

            # keep event loop until finish.
            self.exec()

        except Exception as e:
            self.error_occurred.emit(self.tr("Network Error:") + str(e))

    def on_ready_read(self):
        """deal with raw content"""
        if not self.reply or not self.reply.isOpen():
            return

        try:
            # read raw content and convert to string.
            raw_data = self.reply.readAll()
            if raw_data.isEmpty():
                return

            data = bytes(raw_data).decode('utf-8')
            if not data.startswith('data: '):
                return

            self.content_received.emit(data[len('data: '):])

        except Exception as e:
            print(f"Read error: {e}")

    def on_finished(self):
        """request finished"""
        if self.reply:
            self.reply.finished.disconnect()
            self.reply.deleteLater()
            self.reply = None
        if self.network_manager:
            self.network_manager.deleteLater()
            self.network_manager = None
        self.quit()

    def on_error(self, error):
        """report error"""
        error_msg = f"Error: {self.reply.errorString()}"
        self.error_occurred.emit(error_msg)
        self.quit()