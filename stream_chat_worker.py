# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Stream Chat Worker
 This is subclass of QThread which support stream chat.
                              -------------------
        begin                : 2025-10-01
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

import json
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt5.QtCore import QUrl

from .global_defs import *

class StreamChatWorker(QThread):

    # defines signals.
    # receive chunk signal.
    chunk_received = pyqtSignal(dict)
    # receive references signal.
    chunks_info_received = pyqtSignal(str)
    # receive content signal.
    content_received = pyqtSignal(str)
    # receive stop flag signal, the parameter is the count of chunks.
    stream_ended = pyqtSignal(int)
    # report error signal.
    error_occurred = pyqtSignal(str)

    def __init__(self, request_data, chat_mode: int):
        super().__init__()
        self.request_data = request_data
        self.reply = None
        self.received_chunks = 0
        self.buffer = ""
        # 1: geo knowledge Q&A; 2: generate code with long chain thought
        self.chat_mode = chat_mode
        self.network_manager = None

    def run(self):
        """execute request"""

        self.network_manager = QNetworkAccessManager()

        try:
            url = AI_SERVER_DOMAIN
            if self.chat_mode == 1:
                url += "/ai/v1/chat/stream"
            elif self.chat_mode == 2:
                url += "/ai/v1/code/stream"
            else:
                raise ValueError(f"Unknown chat mode: {self.chat_mode}")

            # create network request.
            request = QNetworkRequest(QUrl(url))
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            request.setRawHeader(b"Accept", b"text/event-stream")

            # send post reqeust.
            json_data = json.dumps(self.request_data).encode('utf-8')
            self.reply = self.network_manager.post(request, json_data)

            # connect read slots.
            self.reply.readyRead.connect(self.on_ready_read, type=Qt.DirectConnection)
            self.reply.finished.connect(self.on_finished, type=Qt.DirectConnection)
            self.reply.errorOccurred.connect(self.on_error, type=Qt.DirectConnection)

            # keep event loop until finish.
            self.exec_()

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
            self.buffer += data

            # read every line.
            lines = self.buffer.split('\n')
            self.buffer = lines[-1]  # contain the last line.

            for line in lines[:-1]:
                line = line.strip()
                if line:
                    self.process_line(line)

        except Exception as e:
            print(f"Read error: {e}")

    def process_line(self, line):
        """deal with every line"""
        if line.startswith('data: '):
            try:
                # remove 'data:'
                json_str = line[6:]
                if json_str.strip():
                    event_data = json.loads(json_str)
                    event_type = event_data.get('type')
                    content = event_data.get('content', '')

                    # emit signals.
                    self.chunk_received.emit(event_data)

                    if event_type == 'chunks':
                        self.chunks_info_received.emit(content)
                    elif event_type == 'content':
                        self.received_chunks += 1
                        self.content_received.emit(content)
                    elif event_type == 'end':
                        self.stream_ended.emit(self.received_chunks)

            except json.JSONDecodeError as e:
                self.error_occurred.emit(f"JSON Error: {str(e)} - Data: {line}")
            except Exception as e:
                self.error_occurred.emit(f"Error: {str(e)}")

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