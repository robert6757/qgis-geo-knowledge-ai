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
    # thinking content signal.
    thinking_received = pyqtSignal(str)
    # receive content signal.
    content_received = pyqtSignal(str)
    # report error signal.
    error_occurred = pyqtSignal(str)
    # private abort signal.
    _abort_network = pyqtSignal()

    def __init__(self, request_data, orch_type: int):
        super().__init__()
        self.request_data = request_data
        self.reply = None
        self.network_manager = None
        # 1: decompose task 2:tool calls 3:conclusion 0: unknown
        self.orch_type = orch_type
        self.buffer = bytearray()
        # Store the final complete response as a list to avoid frequent string concatenation.
        self._final_response = []
        self._abort_network.connect(self._do_abort, type=DirectConnection)

    def run(self):
        """execute request"""

        self.network_manager = QNetworkAccessManager()

        try:
            url = AI_SERVER_DOMAIN
            if self.orch_type == 1:
                url += "/ai/v1/orch/decompose"
            elif self.orch_type == 2:
                url += "/ai/v1/orch/tool/call"
            elif self.orch_type == 3:
                url += "/ai/v1/orch/tool/evaluate"
            elif self.orch_type == 4:
                url += "/ai/v1/orch/conclusion"
            else:
                raise ValueError(f"Unknown orch_type: {self.orch_type}")

            # create network request.
            request = QNetworkRequest(QUrl(url))
            request.setHeader(ContentTypeHeader, "application/json")
            request.setRawHeader(b"Accept", b"text/event-stream")

            # send post reqeust.
            json_data = json.dumps(self.request_data, ensure_ascii=False).encode('utf-8')
            self.reply = self.network_manager.post(request, json_data)

            # connect read slots.
            self.reply.readyRead.connect(self.on_ready_read, type=DirectConnection)
            self.reply.finished.connect(self.on_finished, type=DirectConnection)
            self.reply.errorOccurred.connect(self.on_error, type=DirectConnection)

            # keep event loop until finish.
            self.exec()

        except Exception as e:
            self.error_occurred.emit(self.tr("Network Error:") + str(e))

    def get_raw_response(self):
        return "".join(self._final_response)

    def abort(self):
        self._abort_network.emit()

    def _do_abort(self):
        """Abort the current network request and quit the event loop."""
        if self.reply.isRunning():
            self.reply.abort()

    def on_ready_read(self):
        """deal with raw content - parse SSE events in real-time."""
        if not self.reply or not self.reply.isOpen():
            return

        try:
            raw_data = self.reply.readAll()
            if raw_data.isEmpty():
                return

            self.buffer.extend(bytes(raw_data))

            # Try to decode buffer into string for SSE parsing
            full_str = self.buffer.decode('utf-8')
            # SSE events are separated by double newlines
            parts = full_str.split('\n\n')

            # The last part may be incomplete; keep it in the buffer for next read
            if not full_str.endswith('\n\n'):
                self.buffer = parts[-1].encode('utf-8')
                # Process all complete events (all parts except the last incomplete one)
                complete_events = parts[:-1]
            else:
                self.buffer = bytearray()
                complete_events = parts

            for event_str in complete_events:
                event_str = event_str.strip()
                if not event_str:
                    continue
                # Remove "data: " prefix
                if event_str.startswith('data: '):
                    data_str = event_str[len('data: '):]
                else:
                    data_str = event_str
                try:
                    data_json = json.loads(data_str)
                    # Only emit thinking_received for thinking type
                    if data_json.get('type') == 'thinking':
                        thinking_content = data_json.get('content', '')
                        self.thinking_received.emit(thinking_content)
                    else:
                        # Non-thinking data: append to final response AND emit content_received.
                        self._final_response.append(data_str)
                        self.content_received.emit(data_str)
                except json.JSONDecodeError:
                    # Not a JSON event, skip
                    pass

        except Exception as e:
            print(f"Read error: {e}")

    def on_finished(self):
        """request finished - The final analysis will be provided here."""
        if self.buffer:
            try:
                full_str = self.buffer.decode('utf-8')
                if full_str.startswith('data: '):
                    response_data = full_str[len('data: '):]
                else:
                    response_data = full_str
                self._final_response.append(response_data)
                self.content_received.emit(response_data)
            except Exception as e:
                print(f"Parse error: {e}")

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
        # try to get error message from buffer.
        if self.buffer:
            error_msg = self.buffer.decode('utf-8')
        else:
            error_msg = self.reply.errorString()
        self.error_occurred.emit(error_msg)
        self.quit()