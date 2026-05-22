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

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDockWidget, QGridLayout, QApplication, QMessageBox
from qgis.PyQt.QtCore import pyqtSignal
from qgis.core import QgsSettings, QgsProject, Qgis, QgsMapLayer, QgsApplication
from qgis import processing

from .orch_manager import CTOrchManager, TaskPlan, SubTask
from .stream_chat_worker import StreamChatWorker
from .chatbot_browser import ChatbotBrowser
from .setting_dialog import SettingDialog
from .global_defs import *
from .history_manager import HistoryManager
from .history_dialog import HistoryDialog
from .compat import *
from .code_exec_utils import ensure_code_execution

from .subtask_dialog import SubtaskDialog

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
        self.chatbot_browser.trigger_exec_processing.connect(self.handle_click_exec_processing)
        self.chatbot_browser.trigger_orch_subtask_automate.connect(self.handle_click_exec_subtask_automate)
        self.chatbot_browser.trigger_orch_subtask_step.connect(self.handle_click_exec_subtask_step)
        self.chatbot_browser.trigger_orch_subtask_continue.connect(self.handle_click_exec_subtask_continue)
        self.chatbot_browser.trigger_orch_subtask_repeat.connect(self.handle_click_exec_subtask_repeat)
        self.chatbot_browser.trigger_orch_subtask_detail.connect(self.handle_click_exec_subtask_detail)
        self.btnHistory.clicked.connect(self.handle_click_history_btn)
        self.btnScreenCapture.clicked.connect(self.handle_click_screen_capture)
        self.cbSwitchMode.currentIndexChanged.connect(self.handle_update_chat_mode)

        # update chat mode combobox
        gSetting = QgsSettings()
        chat_mode = int(gSetting.value(CHAT_MODE_TAG, "1"))
        self.cbSwitchMode.setCurrentIndex(chat_mode-1)
        if chat_mode == 1:
            # the screen capture supported only in Knowledge Q&A
            self.btnScreenCapture.setEnabled(True)
        else:
            self.btnScreenCapture.setEnabled(False)

        # update screen capture status.
        capture_screen = gSetting.value(CAPTURE_SCREEN_TAG, 'false').lower() == "true"
        if capture_screen:
            self.btnScreenCapture.setChecked(True)
        else:
            self.btnScreenCapture.setChecked(False)

        # use custom function to deal with "Open Links".
        self.chatbot_browser.setOpenLinks(False)

        # 0: Send 1: Terminate
        self.btn_send_or_terminate_tag = 0

        self.chat_id = None
        self.pre_chat_timestamp = 0

        self.recv_raw_content = ""
        self.question_str = ""

        # For Complex Task Orchestration.
        self.orch_manager = None
        self.orch_task_plan = None
        self.orch_current_subtask = None

        # show welcome text
        self.show_welcome_content()

    def closeEvent(self, event):
        self.closingPlugin.emit()
        event.accept()

    def handle_click_send_or_terminate_btn(self):
        # auto agree with the privacy notice when starting the conversation.
        gSetting = QgsSettings()
        gSetting.setValue(PRIVACY_AGREEMENT_TAG, 'true')

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
        if dlg.exec() != Accepted:
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
        self.chatbot_browser.append_markdown(history_item["answer"])
        self.chatbot_browser.post_process_markdown(show_feedback=False)
        self.plainTextEdit.setPlainText(history_item["question"])

    def handle_update_chat_mode(self, index):
        # chat mode: 1:Q&A 2:Search 3:Generating Code 4:Workflow Automation
        chat_mode = index + 1

        gSetting = QgsSettings()
        gSetting.setValue(CHAT_MODE_TAG, str(chat_mode))

        if chat_mode == 1:
            # the screen capture supported only in Knowledge Q&A
            self.btnScreenCapture.setEnabled(True)
        else:
            self.btnScreenCapture.setEnabled(False)

    def handle_click_feedback(self, star: int):
        if not self.chat_id:
            return

        try:
            # send feedback to server
            response = requests.post(
                AI_SERVER_DOMAIN + "/ai/v1/feedback",
                json={"chat_id": self.chat_id, "star": star},
                timeout=2
            )

            # check response
            if response.status_code == 200:
                QMessageBox.information(self, self.tr("Tip"),
                                        self.tr("Thank you for your feedback."),
                                        QMessageBoxOK)
            else:
                QMessageBox.warning(self, self.tr("Error"),
                                    self.tr("Failed to submit your feedback. Please try again later."),
                                    QMessageBoxOK)

        except requests.exceptions.RequestException as e:
            QMessageBox.critical(self, self.tr("Error"),
                                 self.tr("Network error. Please check your connection and try again."),
                                 QMessageBoxOK)

    def handle_click_repeat(self):
        # remove the lasted history.
        histories = self.history_manager.enum_question()
        if histories:
            # remove the lasted chat.
            self.pre_chat_timestamp = histories[0].get("pre_timestamp", 0)
            self.history_manager.remove_history(histories[0].get("timestamp"))
        else:
            self.pre_chat_timestamp = 0

        # repeat chat.
        self._begin_chat()

    def handle_click_exec_code(self, code):
        """run python process as a background task"""
        CodeExecution = ensure_code_execution(parent_widget=self)
        if CodeExecution is None:
            return

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
        msg_box.setIcon(QMessageBoxCritical)
        msg_box.setWindowTitle(error_type)
        msg_box.setText(error)

        auto_fix_btn = msg_box.addButton(self.tr("Auto-Fix"), QMessageBoxAcceptRole)
        msg_box.addButton(QMessageBoxCancel)
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

    def handle_click_exec_processing(self, processing_id: str):
        # use metadata of processing to find the real algorithm id.
        processing_metadata = QgsApplication.processingRegistry().algorithmById(processing_id)

        # try to find C++(native) and Python(qgis) processing.
        if not processing_metadata and processing_id.startswith("native:"):
            _processing_id = processing_id.replace("native:", "qgis:")
            processing_metadata = QgsApplication.processingRegistry().algorithmById(_processing_id)
        if not processing_metadata and processing_id.startswith("qgis:"):
            _processing_id = processing_id.replace("qgis:", "native:")
            processing_metadata = QgsApplication.processingRegistry().algorithmById(_processing_id)
        if not processing_metadata and processing_id.startswith("saga:"):
            _processing_id = processing_id.replace("saga:", "sagang:")
            processing_metadata = QgsApplication.processingRegistry().algorithmById(_processing_id)

        # Fail to find any processing.
        if not processing_metadata:
            self.handle_exec_code_error(self.tr("RuntimeError"), self.tr("Cannot find processing: ") + processing_id)
            return

        processing.execAlgorithmDialog(processing_metadata.id())

    def handle_click_exec_subtask_automate(self):
        if not self.orch_manager:
            return
        self.orch_manager.automate_task_plan()

    def handle_click_exec_subtask_step(self):
        if not self.orch_manager:
            return
        self.orch_manager.step_task_plan()

    def handle_click_exec_subtask_continue(self, subtask_id):
        if not self.orch_manager:
            return

        if self.orch_current_subtask and subtask_id != self.orch_current_subtask.id:
            QMessageBox.warning(self, self.tr("Error"),
                                self.tr("Only the current subtask can be continued."),
                                QMessageBoxOK)
            return

        self.orch_manager.next_sub_task()

    def handle_click_exec_subtask_repeat(self, subtask_id):
        if not self.orch_manager:
            return
        if self.orch_current_subtask and subtask_id != self.orch_current_subtask.id:
            QMessageBox.warning(self, self.tr("Error"),
                                self.tr("Only the current subtask can be repeated."),
                                QMessageBoxOK)
            return

        self.orch_manager.repeat_sub_task()

    def handle_click_exec_subtask_detail(self, subtask_id):
        if not self.orch_manager or not self.orch_task_plan:
            return

        # Find subtask.
        sub_task = next((st for st in self.orch_task_plan.sub_tasks if st.id == subtask_id), None)
        if not sub_task:
            return

        # show Subtask Detail Dialog.
        dlg = SubtaskDialog(sub_task, self.orch_current_subtask)
        dlg.setModal(True)
        dlg.show()
        if dlg.exec() != Accepted:
            return

        if self.orch_current_subtask and subtask_id != self.orch_current_subtask.id:
            QMessageBox.warning(self, self.tr("Warning"),
                                self.tr("Only the current subtask can be repeated."),
                                QMessageBoxOK)
            return

        self.orch_manager.repeat_sub_task(dlg.get_modified_prompt())

    def handle_ensure_code_execution(self):
        if not self.orch_manager or not self.orch_task_plan:
            return
        code_execution = ensure_code_execution(parent_widget=self)
        self.orch_manager.finish_ensure_code_execution(code_execution)

    def handle_click_screen_capture(self, checked):
        gSetting = QgsSettings()
        if checked:
            # use CoT chat mode.
            gSetting.setValue(CAPTURE_SCREEN_TAG, 'true')
        else:
            gSetting.setValue(CAPTURE_SCREEN_TAG, 'false')

    def on_chunks_info_received(self, content):
        """receive the count of references"""
        self.chatbot_browser.append_markdown(content)

    def on_content_received(self, content):
        """receive the streaming message."""
        # append every message to the chatbot browser.
        self.chatbot_browser.append_markdown(content)
        self.recv_raw_content += content

    def recv_orch_content_stream(self, content):
        content += "\n\n"
        self.chatbot_browser.append_markdown(content)
        self.recv_raw_content += content

    def on_orch_decompose_received(self, task_plan: TaskPlan):
        """receive the orch message"""
        task_plan_text = "\n\n" + self.tr("**Task plan:**") + "\n\n"
        for idx, subtask in enumerate(task_plan.sub_tasks):
            task_plan_text += f"{idx + 1}.{subtask.name}"
            task_plan_text += "\n\n"
        self.recv_raw_content += task_plan_text

        # add extra command text.
        command_text = self.tr("[Step-by-Step](agent://orch/substask/step) | [Automate All](agent://orch/substask/automate)")
        content = f"{task_plan_text}{command_text}\n\n"
        self.chatbot_browser.append_markdown(content)

        self.orch_task_plan = task_plan

    def on_orch_start_subtask_received(self, subtask: SubTask):
        """update current subtask."""
        self.orch_current_subtask = subtask

    def on_orch_finish_subtask_received(self, subtask: SubTask):
        """receive the subtask finished message"""
        content = self.tr("[Continue](agent://orch/substask/continue/{subtask_id}) | [Repeat](agent://orch/substask/repeat/{subtask_id}) | [Detail](agent://orch/substask/detail/{subtask_id})")
        content += "\n\n"
        content = content.replace("{subtask_id}", subtask.id)
        self.chatbot_browser.append_markdown(content)

    def on_stream_ended(self):
        self.chatbot_browser.post_process_markdown()
        self.btn_send_or_terminate_tag = 0
        self.btnSendOrTerminate.setText(self.tr("Send"))
        self.btnSendOrTerminate.setEnabled(True)
        self.btnHistory.setEnabled(True)
        self.btnClear.setEnabled(True)
        self.cbSwitchMode.setEnabled(True)
        self.orch_current_subtask = None

        # save to history
        cur_chat_timestamp = int(time.time())
        self.history_manager.put_history(
            cur_chat_timestamp,
            self.pre_chat_timestamp,
            self.question_str,
            self.recv_raw_content)

        # current chat will be the next previous chat.
        self.pre_chat_timestamp = cur_chat_timestamp

    def on_warning_occurred(self, warning_msg):
        warning_msg += "\n\n"
        self.chatbot_browser.append_markdown(warning_msg)

    def on_error_occurred(self, error_msg):
        """deal with errors"""
        # show errors in chatbot.
        self.chatbot_browser.append_markdown(error_msg)
        self.chatbot_browser.post_process_markdown()

        # resume button status.
        self.btn_send_or_terminate_tag = 0
        self.btnSendOrTerminate.setText(self.tr("Send"))
        self.btnSendOrTerminate.setEnabled(True)
        self.btnHistory.setEnabled(True)
        self.btnClear.setEnabled(True)
        self.cbSwitchMode.setEnabled(True)

    def _begin_chat(self):
        # In order to  make the markdown render faster, we have to clear the previous markdown content.
        self.chatbot_browser.clear()
        self.recv_raw_content = ""

        # add question in chatbot
        self.question_str = self.plainTextEdit.toPlainText()
        self.chatbot_browser.pre_process_markdown()
        self.chatbot_browser.append_markdown(self.tr("**Question:") + self.question_str + "**\n\n")
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

        # capture screen
        capture_screen_tag = gSetting.value(CAPTURE_SCREEN_TAG, 'false').lower() == "true"
        capture_screen_url = ''
        if capture_screen_tag:
            capture_screen_url = self.capture_screen(self.chat_id)

        # get qgis basic information in project context.
        workspace_info = self._get_workspace_info()

        histories = []
        if self.pre_chat_timestamp > 0:
            # retrieve previous messages from the conversation history
            multi_turn = int(gSetting.value(MULTI_TURN_TAG, "3"))
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
            "prompt": self.question_str,
            "history": [[item['question'], item['answer']] for item in histories],
            "email": user_email,
            "version": VERSION,
            "user_id": user_id,
            "chat_id": self.chat_id,
            "lang": lang,
            "workspace": workspace_info,
            "screenshot_url": capture_screen_url
        }

        if chat_mode == 4:
            self.orch_current_subtask = None
            self.orch_task_plan = None
            self.orch_manager = CTOrchManager(self.iface, request_data)
            self.orch_manager.report_decompose_stream.connect(self.recv_orch_content_stream)
            self.orch_manager.orch_decompose_finished.connect(self.on_orch_decompose_received)
            self.orch_manager.orch_subtask_started.connect(self.on_orch_start_subtask_received)
            self.orch_manager.orch_subtask_finished.connect(self.on_orch_finish_subtask_received)
            self.orch_manager.report_subtask_stream.connect(self.recv_orch_content_stream)
            self.orch_manager.report_conclusion_stream.connect(self.recv_orch_content_stream)
            self.orch_manager.finish_all_orchestration.connect(self.on_stream_ended)
            self.orch_manager.error_occurred.connect(self.on_error_occurred)
            self.orch_manager.warning_occurred.connect(self.on_warning_occurred)
            self.orch_manager.ensure_code_execution.connect(self.handle_ensure_code_execution)
            self.orch_manager.report_thinking_stream.connect(self.on_content_received)
            self.orch_manager.start()
        else:
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
        self.cbSwitchMode.setEnabled(False)

    def _stop_chat(self):
        if self.chat_worker:
            self.btnSendOrTerminate.setEnabled(False)
            self.chat_worker.exit()
            self.chat_worker.wait(3000)
            self.chat_worker.deleteLater()
            self.chat_worker = None

        if self.orch_manager:
            self.btnSendOrTerminate.setEnabled(False)
            self.orch_manager.report_decompose_stream.disconnect(self.recv_orch_content_stream)
            self.orch_manager.orch_decompose_finished.disconnect(self.on_orch_decompose_received)
            self.orch_manager.orch_subtask_started.disconnect(self.on_orch_start_subtask_received)
            self.orch_manager.orch_subtask_finished.disconnect(self.on_orch_finish_subtask_received)
            self.orch_manager.report_subtask_stream.disconnect(self.recv_orch_content_stream)
            self.orch_manager.report_conclusion_stream.disconnect(self.recv_orch_content_stream)
            self.orch_manager.finish_all_orchestration.disconnect(self.on_stream_ended)
            self.orch_manager.error_occurred.disconnect(self.on_error_occurred)
            self.orch_manager.warning_occurred.disconnect(self.on_warning_occurred)
            self.orch_manager.ensure_code_execution.disconnect(self.handle_ensure_code_execution)
            self.orch_manager.report_thinking_stream.disconnect(self.on_content_received)

            # When a stop event is triggered, the thread will exit automatically.
            self.orch_manager.stop()
            self.orch_manager = None
            self.orch_current_subtask = None
            self.orch_task_plan = None

        self.chatbot_browser.post_process_markdown()
        self.btnSendOrTerminate.setEnabled(True)
        self.btn_send_or_terminate_tag = 0
        self.btnSendOrTerminate.setText(self.tr("Send"))
        self.btnHistory.setEnabled(True)
        self.btnClear.setEnabled(True)
        self.cbSwitchMode.setEnabled(True)

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

    def capture_screen(self, chat_id):
        # 1. save screenshot to temp dir.
        screenshot_path = os.path.join(
            QStandardPaths.writableLocation(TempLocation),
            "qgis-screenshot.png"
        )
        main_window = self.iface.mainWindow()
        pixmap = main_window.grab()
        pixmap.save(screenshot_path)

        # 2. upload to server
        upload_url = f"{AI_SERVER_DOMAIN}/ai/v1/attachment/image"
        image_name = os.path.basename(screenshot_path)

        try:
            with open(screenshot_path, 'rb') as f:
                image_data = f.read()

            params = {
                "chat_id": chat_id,
                "image_name": image_name
            }
            headers = {
                "Content-Type": "image/png"
            }
            response = requests.post(
                upload_url,
                params=params,
                data=image_data,
                headers=headers,
                timeout=5
            )

            if response.status_code != 200:
                return None

            # eg. /ai/v1/attachment/image?image_name=xxx.png
            return response.text.strip()
        except requests.exceptions.RequestException as e:
            self.iface.messageBar().pushMessage(
                "Failed to upload screenshot",
                f"Network：{str(e)}",
                level=Qgis.Critical,
                duration=5
            )
        except Exception as e:
            self.iface.messageBar().pushMessage(
                "Failed to upload screenshot",
                f"{str(e)}",
                level=Qgis.Critical,
                duration=5
            )
        finally:
            # remove screenshot image.
            if os.path.exists(screenshot_path):
                os.remove(screenshot_path)
        return None

    def show_welcome_content(self):
        welcome_str = self.tr("""### Welcome to the Geo Knowledge AI plugin!\n\n**Glad to meet you! 🌍**\n\nI am your GIS AI assistant, providing four agents: **Knowledge Q&A**, **Data Search**, **Code Generation**, and **Workflow Automation**.\n\n Our knowledge base covers global geodata discovery, geoscientific modeling, hydrological and terrain analysis, remote sensing processing, and PyQGIS documentation.\n\nAdditionally, I can guide you through essential tools like GDAL, GRASS, and SAGA to make your spatial analysis more efficient and intelligent.\n\nTip: **Workflow Automation** can handle complex tasks either fully automatically or step-by-step. We suggest backing up your data and QGIS projects before running a workflow.""")

        gSetting = QgsSettings()
        if gSetting.value(PRIVACY_AGREEMENT_TAG, 'false').lower() != "true":
            welcome_str += self.tr("""\n\n———\n\n **First-Time Use**\n\nPlease enter your question in the input box below and click the **Send** button to start the conversation.\n\nTo get a more comprehensive understanding of your question, enable the screenshots ![Screenshot](qtres://plugins/geo_knowledge_ai/image/screencapture2.svg) switch.\n\n\nBy asking a question, you acknowledge that you have read and agreed to the [privacy notice](https://github.com/robert6757/qgis-geo-knowledge-ai/blob/main/README.md).\n\n""")

        self.chatbot_browser.append_markdown(welcome_str, True, in_gui_thread=True)


