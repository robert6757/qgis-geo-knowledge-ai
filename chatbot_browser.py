"""
/***************************************************************************
                               Chatbot Browser
 A class inherits from QTextBrowser to display chatbot content.

        begin                : 2025-10-09
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

import webbrowser
import re
import queue
import threading
import time

from PyQt5.QtCore import QByteArray, Qt, QUrl, pyqtSignal, QTimer, QThread
from PyQt5.QtGui import QTextDocument, QImage, QMouseEvent
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt5.QtWidgets import QTextBrowser

class ConsumerThread(QThread):
    data_received = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, queue, stop_event, interval_ms=100):
        super().__init__()
        self.queue = queue
        self.stop_event = stop_event
        self.interval = interval_ms / 1000.0
        self.batch_data = [] # save cache data.
        self.last_emit_time = time.time()  # the last time for emitting.

    def run(self):
        while not self.stop_event.is_set():
            try:
                item = self.queue.get(timeout=0.1)
            except queue.Empty:
                self._check_and_emit()
                continue

            if item is None:
                break

            self.batch_data.append(item)
            self.queue.task_done()

            # do pending items.
            while True:
                try:
                    more = self.queue.get_nowait()
                    if more is None:
                        self._flush_and_finish()
                        return
                    self.batch_data.append(more)
                    self.queue.task_done()
                except queue.Empty:
                    break

            self._check_and_emit()

        # clear all before exit.
        self._check_and_emit(force=True)
        self.finished.emit()

    def _check_and_emit(self, force=False):
        """check time, emit data_received signal"""
        if not self.batch_data:
            return

        current_time = time.time()
        if force or (current_time - self.last_emit_time >= self.interval):
            # time for emit, and wait for next time.
            self.data_received.emit(''.join(self.batch_data))
            self.batch_data.clear()
            self.last_emit_time = current_time

    def _flush_and_finish(self):
        if self.batch_data:
            self.data_received.emit(''.join(self.batch_data))
            self.batch_data.clear()
        self.queue.task_done()
        self.finished.emit()


class ChatbotBrowser(QTextBrowser):
    show_setting_dlg = pyqtSignal()
    trigger_feedback = pyqtSignal(int)
    trigger_repeat = pyqtSignal()
    trigger_exec_code = pyqtSignal(str)
    trigger_copy_code = pyqtSignal(str)
    trigger_exec_processing = pyqtSignal(str)
    trigger_repeat_with_cot = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.markdown_content = ""
        self.auto_scroll_to_bottom = True
        self.setMouseTracking(True)
        self.show_feedback = True

        # drawing queue
        self.drawing_queue = queue.Queue()
        self.stop_event = threading.Event()

        self.drawing_consumer = ConsumerThread(self.drawing_queue, self.stop_event)
        self.drawing_consumer.data_received.connect(self._do_append_markdown)
        self.drawing_consumer.finished.connect(self._on_consumer_finished)

        # Use a dictionary to cache downloaded images to prevent multiple downloads
        self.image_cache = {}

        # pending loading parameters.
        self.pending_images = set()
        self.img_loading_network = QNetworkAccessManager(self)
        self.img_loading_network.finished.connect(self._on_image_downloaded)

        self.anchorClicked.connect(self.handle_click_chatbot_anchor)

        self.feedback_text = self.tr(
            "Was this answer helpful? [Yes](agent://feedback/5) | [No](agent://feedback/1) | [Repeat](agent://repeat) | [Chain of Thought](agent://cot/1)")
        self.exec_code_text = "\n\n" + self.tr(
            "[Execute Code](agent://execute/code/{index}) | [Copy Code](agent://execute/copycode/{index})") + "\n\n"
        self.exec_processing_text = "[{processing_id}](agent://execute/processing/{processing_id})"
        self.tail_splited_line = "\n\n---------\n\n"

        self.python_code_block_list = []

        # self.temp_file_path = f'd:/output/geo_knowledge_ai_output_{time.time()}.txt'

    def loadResource(self, type, name):
        """
        Overrides the standard loadResource method to handle network requests for images.
        """
        if type == QTextDocument.ImageResource and name.scheme() in ('http', 'https'):
            url_string = name.toString()
            # Check if the image is already in the cache
            if url_string in self.image_cache:
                return self.image_cache[url_string]

            # Check whether in pending list.
            if url_string in self.pending_images:
                return None

            self._download_image_async(url_string)
            return None
        elif type == QTextDocument.ImageResource and name.scheme() in ('qtres'):
            res_path = name.toString().replace("qtres://", ":")
            res_image = QImage(res_path)
            return res_image.scaled(16, 16, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

        # Do not load unknown format of resource.
        return None

    def append_markdown(self, content: str, scroll_to_bottom=True, in_gui_thread=False):
        # because self.auto_scroll_to_bottom will be stopped by itself,
        # so we only assign self.auto_scroll_to_bottom when it is True.
        if self.auto_scroll_to_bottom:
            self.auto_scroll_to_bottom = scroll_to_bottom

        if in_gui_thread:
            self._do_append_markdown(content)
        else:
            # add to consumer queue.
            self.drawing_queue.put(content)

        # debug. save to temp file.
        # with open(self.temp_file_path, 'a', encoding='utf-8') as f:
        #     f.write(content)

    def _do_append_markdown(self, content: str):

        # self.iface.messageBar().pushMessage(content)

        # save current scroll value.
        scrollbar = self.verticalScrollBar()
        current_scroll_value = scrollbar.value()

        self.markdown_content += content

        # clean all html tags
        self.markdown_content = self.clean_html_tag(self.markdown_content)

        # update markdown content
        self.setMarkdown(self.markdown_content)

        if self.auto_scroll_to_bottom:
            self.scroll_to_bottom()
        else:
            # resume scroll bar value and disable auto scrolling to bottom.
            scrollbar.setValue(current_scroll_value)

    def pre_process_markdown(self):
        # resume auto scroll to bottom.
        self.auto_scroll_to_bottom = True
        self.show_feedback = True
        self.markdown_content = ""
        self.setMarkdown("")
        self.pending_images.clear()
        self.python_code_block_list.clear()
        self.stop_event.clear()
        self.drawing_consumer.start()

        # self.temp_file_path = f'd:/output/geo_knowledge_ai_output_{time.time()}.txt'

    def post_process_markdown(self, show_feedback=True):
        self.show_feedback = show_feedback
        self.drawing_queue.put(None)
        self.drawing_consumer.wait()

        # Check Result!
        # self.iface.messageBar().pushMessage(self.markdown_content)

    def replace_failed_images_with_links(self, markdown_text):
        # Markdown format: ![alt](url)
        pattern = r'!\[([^\]]*)\]\(([^)]+)\)'

        def replace_match(match):
            alt_text = match.group(1)
            url = match.group(2)

            if url in self.image_cache and self.image_cache[url] is None:
                # replace to href.
                return f'[{alt_text}]({url})'
            else:
                # keep strings.
                return match.group(0)

        return re.sub(pattern, replace_match, markdown_text)

    def clean_html_tag(self, markdown_text):
        # wellknown HTML tag.
        html_tags = r'div|span|p|a|br|hr|img|table|tr|td|th|ul|ol|li|b|i|u|header|footer|section|canvas|svg'

        # remove these tags.
        pattern = rf'</?(?:{html_tags})\b[^>]*>'

        return re.sub(pattern, '', markdown_text)

    def clear(self):
        self.markdown_content = ""
        self.setMarkdown("")
        self.image_cache.clear()
        self.auto_scroll_to_bottom = True
        self.pending_images.clear()
        self.stop_event.set()
        self.drawing_consumer.wait()

    def scroll_to_bottom(self):
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def wheelEvent(self, event):
        # forbid auto scroll to bottom
        self.auto_scroll_to_bottom = False
        super().wheelEvent(event)

    def handle_click_chatbot_anchor(self, link: QUrl):
        path = link.path()

        if link.scheme() == "agent":
            # use agent to process.
            process_name = link.host()
            if process_name == "applyvip":
                self.show_setting_dlg.emit()
            elif process_name == "feedback":
                self.trigger_feedback.emit(int(link.path()[1:]))
            elif process_name == "repeat":
                self.trigger_repeat.emit()
            elif process_name == "execute":
                if path.startswith("/code/"):
                    code_index = int(path.split("/")[-1])
                    self.trigger_exec_code.emit(self.python_code_block_list[code_index - 1])
                elif path.startswith("/copycode/"):
                    code_index = int(path.split("/")[-1])
                    self.trigger_copy_code.emit(self.python_code_block_list[code_index - 1])
                elif path.startswith("/processing/"):
                    processing_id = path.split("/")[-1]
                    self.trigger_exec_processing.emit(processing_id)
            elif process_name == "cot":
                self.trigger_repeat_with_cot.emit()
            return

        # open web browser
        url_str = link.url()
        webbrowser.open(url_str)

    def convert_upl_to_markdown_image(self, markdown_text):
        # regex: [upl-image-preview ...]
        pattern = r'\[upl-image-preview[^\]]*?url=([^\s\]]+)[^\]]*\]'
        converted_text = re.sub(pattern, r'\n\n![Image](\1)', markdown_text, flags=re.IGNORECASE)
        return converted_text

    def mousePressEvent(self, event: QMouseEvent):
        # forbid auto scroll to bottom
        self.auto_scroll_to_bottom = False

        try:
            # Check if clicked on an image
            cursor = self.cursorForPosition(event.pos())
            if cursor:
                char_format = cursor.charFormat()
                if char_format.isValid():
                    image_format = char_format.toImageFormat()
                    if image_format.isValid():
                        image_name = image_format.name()
                        if image_name and not image_name.startswith("qtres://"):
                            # If clicked on an image, handle it
                            self._handle_image_click(image_name)
                            return
        except Exception as e:
            # show error message.
            error_msg = f"Error in mousePressEvent: {e}"
            self.iface.messageBar().pushMessage(error_msg)

        # Otherwise, call parent's mousePressEvent
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        # check hyperlink first.
        anchor = self.anchorAt(event.pos())

        if anchor:
            # use hand cursor on hyperlink text.
            self.viewport().setCursor(Qt.PointingHandCursor)
        else:
            # whether moving on image.
            try:
                cursor = self.cursorForPosition(event.pos())
                if cursor:
                    char_format = cursor.charFormat()
                    if char_format.isValid():
                        image_format = char_format.toImageFormat()
                        if image_format.isValid():
                            image_name = image_format.name()
                            if image_name and not image_name.startswith("qtres://"):
                                # use hand cursor on image.
                                self.viewport().setCursor(Qt.PointingHandCursor)
                                super().mouseMoveEvent(event)
                                return
            except Exception as e:
                error_msg = f"Error in mouseMoveEvent: {e}"
                self.iface.messageBar().pushMessage(error_msg)

            # use default cursor.
            self.viewport().setCursor(Qt.ArrowCursor)

        super().mouseMoveEvent(event)

    def _handle_image_click(self, image_url):
        """
        Handle click on an image. Try to extract the original URL from the image.
        """
        try:
            # The image_url might be a QUrl or a string
            if isinstance(image_url, QUrl):
                url_str = image_url.toString()
            else:
                url_str = str(image_url)

            # Check if it's a network URL
            if url_str.startswith(('http://', 'https://')):
                # Open the image in browser
                webbrowser.open(url_str)
            else:
                # Try to find the original URL in the markdown content
                # Look for markdown image syntax with this URL
                pattern = r'!\[[^\]]*\]\(([^)]+)\)'
                matches = re.findall(pattern, self.markdown_content)

                for match in matches:
                    if url_str in match or match in url_str:
                        webbrowser.open(match)
                        return
        except Exception as e:
            # show error message.
            error_msg = f"Error in _handle_image_click: {e}"
            self.iface.messageBar().pushMessage(error_msg)

    def _download_image_async(self, url_string):
        if url_string in self.pending_images:
            return

        self.pending_images.add(url_string)

        request = QNetworkRequest(QUrl(url_string))
        request.setTransferTimeout(3000)
        self.img_loading_network.get(request)

    def _on_image_downloaded(self, reply):
        """deal with downloaded image."""
        url_string = reply.url().toString()

        # remove from pending list.
        if url_string in self.pending_images:
            self.pending_images.remove(url_string)

        # deal with errors.
        error = reply.error()
        if error != QNetworkReply.NoError:
            self._handle_download_error(url_string, reply.errorString())
            reply.deleteLater()
            return

        # read data into memory.
        image_data = reply.readAll()
        if image_data.isEmpty():
            self._handle_download_error(url_string, "Empty response")
            reply.deleteLater()
            return

        # load data as image.
        image = QImage()
        image.loadFromData(image_data)

        # shrink the large image
        available_width = self.size().width()
        if image.width() > available_width:
            scaled_image = image.scaledToWidth(available_width, Qt.SmoothTransformation)
        else:
            scaled_image = image

        # save to cache.
        self.image_cache[url_string] = scaled_image
        reply.deleteLater()

    def _handle_download_error(self, url_string, error_msg):
        """deal with errors"""
        # save None to the image_cache
        self.image_cache[url_string] = None

        # show error on message bar.
        error_msg_display = f"Error loading image: {url_string}: {error_msg}"
        self.iface.messageBar().pushMessage(error_msg_display)

    def _on_consumer_finished(self):
        # waiting for all Qt events have been finished.
        QTimer.singleShot(500, self._finalize_markdown_display)

    def _finalize_markdown_display(self):
        # waiting for all images has been loaded
        if len(self.pending_images) > 0:
            QTimer.singleShot(500, self._finalize_markdown_display)
            return

        # add feedback
        if self.show_feedback:
            self.markdown_content += "\n\n" + self.feedback_text

        # add execute button after the python code block.
        self.python_code_block_list, self.markdown_content = self._extract_code_and_add_execute_tag_after(
            self.markdown_content)
        _, self.markdown_content = self._extract_processing_and_add_execute_tag(self.markdown_content)

        self.markdown_content += self.tail_splited_line

        # deal with upl-image-preview block.
        self.markdown_content = self.convert_upl_to_markdown_image(self.markdown_content)

        # replace failed image with links.
        self.markdown_content = self.replace_failed_images_with_links(self.markdown_content)

        current_scroll_value = self.verticalScrollBar().value()

        # finally update markdown
        self.setMarkdown(self.markdown_content)

        if self.auto_scroll_to_bottom:
            self.scroll_to_bottom()
        else:
            self.verticalScrollBar().setValue(current_scroll_value)

    def _extract_code_and_add_execute_tag_after(self, text: str):
        """find the largest python code block from text, and add executing text."""
        pattern = r'```(?:python|py)\s*\n?(.*?)```'

        matches = list(re.finditer(pattern, text, re.DOTALL))
        if not matches:
            return [], text

        ret_code_list = []
        for match in matches:
            ret_code_list.append(match.group(1).strip())

        # in order to use a correct end_pos, I have to reverse the loop.
        for i in reversed(range(len(matches))):
            match = matches[i]
            end_pos = match.end()

            # generate execution tag.
            exec_block_with_index = self.exec_code_text.replace("{index}", str(i + 1))

            # add block.
            text = text[:end_pos] + exec_block_with_index + text[end_pos:]

        return ret_code_list, text

    def _extract_processing_and_add_execute_tag(self, text: str):
        """
        add executing tag with processing id.
        ignore the code block area.
        """
        # code block
        code_block_pattern = r'```.*?```'

        # eg. native:buffer
        colon_string_pattern = r'`[a-zA-Z0-9_-]+:[a-zA-Z0-9_-]+`'

        # find all the code blocks.
        code_blocks = list(re.finditer(code_block_pattern, text, re.DOTALL))

        ret_string_list = []

        if code_blocks:
            non_code_positions = []

            current_pos = 0
            for code_block in sorted(code_blocks, key=lambda x: x.start()):
                if current_pos < code_block.start():
                    non_code_positions.extend(range(current_pos, code_block.start()))
                current_pos = code_block.end()

            # deal with the last block.
            if current_pos < len(text):
                non_code_positions.extend(range(current_pos, len(text)))

            for pos in non_code_positions:
                if pos < len(text):
                    remaining_text = text[pos:]
                    match = re.match(colon_string_pattern, remaining_text)
                    if match:
                        matched_string = match.group(0)
                        end_pos = pos + len(matched_string)
                        if all(p in non_code_positions for p in range(pos, end_pos)):
                            if matched_string not in ret_string_list:
                                ret_string_list.append(matched_string)

        else:
            # find in the whole text.
            matches = re.findall(colon_string_pattern, text)
            ret_string_list = list(set(matches))  # 去重

        insert_positions = []

        if not code_blocks:
            for match in re.finditer(colon_string_pattern, text):
                insert_positions.append((match.end(), match.group(0)))
        else:
            current_pos = 0
            non_code_ranges = []

            for code_block in sorted(code_blocks, key=lambda x: x.start()):
                if current_pos < code_block.start():
                    non_code_ranges.append((current_pos, code_block.start()))
                current_pos = code_block.end()

            if current_pos < len(text):
                non_code_ranges.append((current_pos, len(text)))

            for start, end in non_code_ranges:
                non_code_text = text[start:end]
                for match in re.finditer(colon_string_pattern, non_code_text):
                    actual_start = start + match.start()
                    actual_end = start + match.end()
                    matched_string = match.group(0)
                    insert_positions.append((actual_end, matched_string))

        # find processing from end to start.
        for i, (end_pos, matched_string) in enumerate(sorted(insert_positions, key=lambda x: x[0], reverse=True), 1):
            # skip some ignored tags.
            if matched_string.startswith("`EPSG:"):
                continue

            processing_id = matched_string.replace("`", "")

            # generate executing tag.
            # eg. [native:buffer](agent://execute/processing/native:buffer)
            exec_block = self.exec_processing_text.replace("{processing_id}", processing_id)

            text = text[:end_pos - len(matched_string)] + exec_block + text[end_pos:]

        return ret_string_list, text
