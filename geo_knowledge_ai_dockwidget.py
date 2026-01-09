# -*- coding: utf-8 -*-
"""
/***************************************************************************
                      Geo Knowledge AI Dock Widget
  This class provides main docking widget.
                              -------------------
        begin                : 2025-12-15
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
import os
import time
import requests
import uuid
import traceback
import io
from contextlib import redirect_stdout

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDockWidget, QGridLayout, QDialog, QMessageBox, QApplication
from qgis.PyQt.QtCore import pyqtSignal
from qgis.core import QgsSettings, QgsProject, Qgis, QgsMapLayer, QgsApplication

from .stream_chat_worker import StreamChatWorker
from .chatbot_browser import ChatbotBrowser
from .setting_dialog import SettingDialog
from .global_defs import *
from .resources_rc import *
from .history_manager import HistoryManager
from .history_dialog import HistoryDialog
from .code_execution import CodeExecution

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'geo_knowledge_ai_dockwidget_base.ui'))

class GeoKnowledgeAIDockWidget(QDockWidget, FORM_CLASS):
    closingPlugin = pyqtSignal()

    def __init__(self, iface, parent=None):
        """Constructor."""
        super(GeoKnowledgeAIDockWidget, self).__init__(parent)
        self.iface = iface
        self.chat_worker = None
        self.setupUi(self)

        self.chatbot_browser = ChatbotBrowser(iface)
        self.history_manager = HistoryManager()

        chatbot_layout = QGridLayout()
        chatbot_layout.setContentsMargins(0, 0, 0, 0)
        chatbot_layout.addWidget(self.chatbot_browser)
        self.widgetChatbotParent.setLayout(chatbot_layout)

        self.btnSendOrTerminate.clicked.connect(self.handle_click_send_or_terminate_btn)
        self.btnClear.clicked.connect(self.handle_click_clear_btn)
        self.btnSetting.clicked.connect(self.handle_click_setting_btn)
        self.chatbot_browser.show_setting_dlg.connect(self.handle_click_setting_btn)
        self.chatbot_browser.trigger_feedback.connect(self.handle_click_feedback)
        self.chatbot_browser.trigger_repeat.connect(self.handle_click_repeat)
        self.chatbot_browser.trigger_exec_code.connect(self.handle_click_exec_code)
        self.chatbot_browser.trigger_copy_code.connect(self.handle_click_copy_code)
        self.btnHistory.clicked.connect(self.handle_click_history_btn)
        self.btnCoTStatus.toggled.connect(self.handle_update_CoT_status)

        # update CoT status.
        gSetting = QgsSettings()
        chat_mode = int(gSetting.value(CHAT_MODE_TAG, "1"))
        if chat_mode == 1:
            self.btnCoTStatus.setChecked(False)
        else:
            self.btnCoTStatus.setChecked(True)

        # use custom function to deal with "Open Links".
        self.chatbot_browser.setOpenLinks(False)

        # 0: Send 1: Terminate
        self.btn_send_or_terminate_tag = 0

        self.chat_id = None
        self.pre_chat_timestamp = 0

        self.recv_raw_content = ""

    def closeEvent(self, event):
        self.closingPlugin.emit()
        event.accept()

    def handle_click_send_or_terminate_btn(self):
        if self.btn_send_or_terminate_tag == 0:
            self._begin_chat()
        elif self.btn_send_or_terminate_tag == 1:
            self._stop_chat()

    def handle_click_clear_btn(self):
        self.chatbot_browser.clear()
        self.plainTextEdit.clear()
        self.chat_id = None
        self.pre_chat_timestamp = 0
        self.recv_raw_content = ""

    def handle_click_setting_btn(self):
        dlg = SettingDialog(self.iface, parent=self)
        dlg.setModal(True)
        dlg.show()
        dlg.exec()

    def handle_click_history_btn(self):
        dlg = HistoryDialog(self.history_manager)
        dlg.setModal(True)
        dlg.show()
        if dlg.exec() != QDialog.Accepted:
            return

        # retrieve history content
        selected_history_ts = dlg.get_selected_history_timestamp()
        history_item = self.history_manager.retrieve_history(selected_history_ts)
        if history_item is None:
            return

        self.chatbot_browser.clear()
        self.plainTextEdit.clear()
        self.chat_id = None
        self.pre_chat_timestamp = history_item.get("timestamp", 0)
        self.chatbot_browser.pre_process_markdown()
        self.chatbot_browser.append_markdown(history_item["answer"], scroll_to_bottom=False)
        self.chatbot_browser.post_process_markdown(show_feedback=False)
        self.plainTextEdit.setPlainText(history_item["question"])

    def handle_update_CoT_status(self, checked):
        gSetting = QgsSettings()
        if checked:
            # use CoT chat mode.
            gSetting.setValue(CHAT_MODE_TAG, "2")
        else:
            gSetting.setValue(CHAT_MODE_TAG, "1")

    def handle_click_feedback(self, star: int):
        if not self.chat_id:
            return

        try:
            # send feedback to server
            response = requests.post (
                AI_SERVER_DOMAIN + "/ai/v1/feedback",
                json={"chat_id": self.chat_id, "star": star},
                timeout=2
            )

            # check response
            if response.status_code == 200:
                QMessageBox.information(self, self.tr("Tip"),
                                        self.tr("Thank you for your feedback."),
                                        QMessageBox.Ok)
            else:
                QMessageBox.warning(self, self.tr("Error"),
                                    self.tr("Failed to submit your feedback. Please try again later."),
                                    QMessageBox.Ok)

        except requests.exceptions.RequestException as e:
            QMessageBox.critical(self, self.tr("Error"),
                                 self.tr("Network error. Please check your connection and try again."),
                                 QMessageBox.Ok)

    def handle_click_repeat(self):
        # remove the lasted history.
        histories = self.history_manager.enum_question()
        if not histories:
            return

        # remove the lasted chat.
        self.pre_chat_timestamp = histories[0].get("pre_timestamp", 0)
        self.history_manager.remove_history(histories[0].get("timestamp"))

        # repeat chat.
        self._begin_chat()

    def handle_click_exec_code(self, code):
        """run python process as a background task"""
        code_exec = CodeExecution(
            code=code,
            parent_widget=self,
            iface=self.iface
        )

        code_exec.task_finished.connect(self.handle_exec_code_finished)
        code_exec.task_error.connect(self.handle_exec_code_error)

        code_exec.run()

    def handle_exec_code_finished(self, content):
        QMessageBox.information(self, self.tr("Success"), content)

    def handle_exec_code_error(self, error_type, error):
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle(error_type)
        msg_box.setText(error)

        auto_fix_btn = msg_box.addButton(self.tr("Auto-Fix"), QMessageBox.AcceptRole)
        msg_box.addButton(QMessageBox.Cancel)
        msg_box.exec()
        if msg_box.clickedButton() == auto_fix_btn:
            self.handle_auto_fix_error(error)

    def handle_click_copy_code(self, code):
        clipboard = QApplication.clipboard()
        clipboard.setText(code)
        self.iface.messageBar().pushMessage(self.tr("Code Copied Successfully!"))

    def handle_auto_fix_error(self, error_msg):
        # set error_msg as user`s question.
        self.plainTextEdit.setPlainText(error_msg)
        self._begin_chat()

    def on_chunks_info_received(self, content):
        """receive the count of references"""
        self.chatbot_browser.append_markdown(content)

    def on_content_received(self, content):
        """receive the streaming message."""
        # append every message to the chatbot browser.
        self.chatbot_browser.append_markdown(content)
        self.recv_raw_content += content

    def on_stream_ended(self, chunk_count):
        self.chatbot_browser.post_process_markdown()
        self.btn_send_or_terminate_tag = 0
        self.btnSendOrTerminate.setText(self.tr("Send"))
        self.btnSendOrTerminate.setEnabled(True)
        self.btnHistory.setEnabled(True)
        self.btnClear.setEnabled(True)
        self.btnCoTStatus.setEnabled(True)

        # save to history
        cur_chat_timestamp = int(time.time())
        self.history_manager.put_history(
            cur_chat_timestamp,
            self.pre_chat_timestamp,
            self.plainTextEdit.toPlainText(),
            self.recv_raw_content)

        # current chat will be the next previous chat.
        self.pre_chat_timestamp = cur_chat_timestamp

    def on_error_occurred(self, error_msg):
        """deal with errors"""
        # show errors in chatbot.
        self.chatbot_browser.append_markdown(error_msg)

        # resume button status.
        self.btn_send_or_terminate_tag = 0
        self.btnSendOrTerminate.setText(self.tr("Send"))
        self.btnSendOrTerminate.setEnabled(True)
        self.btnHistory.setEnabled(True)
        self.btnClear.setEnabled(True)
        self.btnCoTStatus.setEnabled(True)

    def _begin_chat(self):
        # In order to  make the markdown render faster, we have to clear the previous markdown content.
        self.chatbot_browser.clear()
        self.recv_raw_content = ""

        # add question in chatbot
        question_str = self.plainTextEdit.toPlainText()
        self.chatbot_browser.pre_process_markdown()
        self.chatbot_browser.append_markdown(self.tr("**Question:") + question_str + "**\n\n")
        self.chatbot_browser.append_markdown(self.tr("**Answer:") + "**\n\n")

        gSetting = QgsSettings()

        # uid
        user_id = gSetting.value(USER_ID_TAG, "")

        # email
        user_email = gSetting.value(USER_EMAIL_TAG, "")

        # ui language
        lang = gSetting.value('/locale/userLocale', 'en_US')

        # chat mode
        chat_mode = int(gSetting.value(CHAT_MODE_TAG, "1"))

        # build new chat id.
        self.chat_id = uuid.uuid4().hex

        # get qgis basic information in project context.
        workspace_info = self._get_workspace_info()

        histories = []
        if self.pre_chat_timestamp > 0:
            # retrieve previous messages from the conversation history
            multi_turn = int(gSetting.value(MULTI_TURN_TAG, "1"))
            parent_chat_ts = self.pre_chat_timestamp
            while multi_turn > 0 and parent_chat_ts > 0:
                pre_history = self.history_manager.retrieve_history(parent_chat_ts)
                if not pre_history:
                    break

                histories.append(pre_history)
                parent_chat_ts = pre_history.get("pre_timestamp", 0)
                multi_turn -= 1

        # prepare request body.
        request_data = {
            "prompt": question_str,
            "history": [[item['question'], item['answer']] for item in histories],
            "email": user_email,
            "version": VERSION,
            "user_id": user_id,
            "chat_id": self.chat_id,
            "lang": lang,
            "workspace": workspace_info
        }

        self.chat_worker = StreamChatWorker(request_data, chat_mode)
        self.chat_worker.chunks_info_received.connect(self.on_chunks_info_received)
        self.chat_worker.content_received.connect(self.on_content_received)
        self.chat_worker.stream_ended.connect(self.on_stream_ended)
        self.chat_worker.error_occurred.connect(self.on_error_occurred)
        self.chat_worker.start()

        self.btn_send_or_terminate_tag = 1
        self.btnSendOrTerminate.setText(self.tr("Stop"))
        self.btnHistory.setEnabled(False)
        self.btnClear.setEnabled(False)
        self.btnCoTStatus.setEnabled(False)

    def _stop_chat(self):
        if self.chat_worker:
            self.btnSendOrTerminate.setEnabled(False)
            self.chat_worker.exit()
            self.chat_worker.wait(3000)

        self.chatbot_browser.post_process_markdown()
        self.btnSendOrTerminate.setEnabled(True)
        self.btn_send_or_terminate_tag = 0
        self.btnSendOrTerminate.setText(self.tr("Send"))
        self.btnHistory.setEnabled(True)
        self.btnClear.setEnabled(True)
        self.btnCoTStatus.setEnabled(True)

    def _get_workspace_info(self):
        workspace_info = {}

        # qgis version
        workspace_info["version"] = Qgis.version()

        # get working project
        project = QgsProject.instance()

        # CRS part
        project_crs = project.crs()
        workspace_info["CRSAuthId"] = project_crs.authid()

        # get map canvas parameters.
        map_canvas = self.iface.mapCanvas()
        canvas_extent = map_canvas.extent()
        workspace_info["MapCanvasExtent"] = [
            f"{canvas_extent.xMinimum():.6f}",
            f"{canvas_extent.yMinimum():.6f}",
            f"{canvas_extent.xMaximum():.6f}",
            f"{canvas_extent.yMaximum():.6f}"]

        # enumerate layers in project.
        layers_info = []
        layer_tree_root = project.layerTreeRoot()
        layers = project.mapLayers().values()
        for layer in layers:
            node = layer_tree_root.findLayer(layer.id())
            visible = node.isVisible() if node else False

            layer_info = {}
            layer_info["name"] = f"{layer.name()}"
            layer_info["type"] = f"{layer.type().name}"
            layer_info["visible"] = visible

            crs = layer.crs()
            layer_info["CRSAuthId"] = f"{crs.authid()}"

            # get fields data in vector data.
            if layer.type() == QgsMapLayer.VectorLayer:
                fields_info = []
                fields = layer.fields()
                for field in fields:
                    field_info = {
                        "name": field.name(),
                        "type": field.typeName(),
                        "length": field.length(),
                        "precision": field.precision()
                    }
                    fields_info.append(field_info)
                layer_info["fields"] = fields_info

            # get bands data in raster data.
            elif layer.type() == QgsMapLayer.RasterLayer:
                bands_info = []
                provider = layer.dataProvider()
                if provider:
                    # basic raster variables.
                    layer_info["raster_width"] = provider.xSize()
                    layer_info["raster_height"] = provider.ySize()

                    # extent of data.
                    extent = provider.extent()
                    layer_info["raster_extent"] = [
                        f"{extent.xMinimum():.6f}",
                        f"{extent.yMinimum():.6f}",
                        f"{extent.xMaximum():.6f}",
                        f"{extent.yMaximum():.6f}"
                    ]

                    if provider.xSize() > 0 and provider.ySize() > 0:
                        pixel_size_x = (extent.xMaximum() - extent.xMinimum()) / provider.xSize()
                        pixel_size_y = (extent.yMaximum() - extent.yMinimum()) / provider.ySize()
                        layer_info["pixel_size"] = [
                            f"{pixel_size_x:.6f}",
                            f"{pixel_size_y:.6f}"
                        ]

                    layer_info["origin"] = [
                        f"{extent.xMinimum():.6f}",
                        f"{extent.yMaximum():.6f}"
                    ]

                    band_count = provider.bandCount()
                    for band in range(1, band_count + 1):
                        band_info = {
                            "band_number": band,
                            "band_name": f"Band {band}",
                            "data_type": provider.dataType(band),
                        }
                        color_interp = provider.colorInterpretation(band)
                        if hasattr(color_interp, 'name'):
                            band_info["color_interpretation"] = color_interp.name

                        # In order to shorten time of statistic, use the custom sample size.
                        customSampleSize = int(max(provider.xSize(), provider.ySize()) / 256)
                        stats = provider.bandStatistics(band, sampleSize=customSampleSize)
                        if stats:
                            band_info["minimum"] = stats.minimumValue
                            band_info["maximum"] = stats.maximumValue
                            band_info["mean"] = stats.mean
                            band_info["std_dev"] = stats.stdDev

                        bands_info.append(band_info)

                layer_info["bands"] = bands_info

            layers_info.append(layer_info)
        workspace_info["Layers"] = layers_info

        # get Processing Tools
        processing_tools = []
        registry = QgsApplication.processingRegistry()
        providers = registry.providers()
        for provider in providers:
            processing_tools.append(provider.name())
        workspace_info["ProcessingTools"] = processing_tools

        return workspace_info