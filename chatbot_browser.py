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
from threading import Lock

from PyQt5.QtCore import QByteArray, Qt, QUrl, pyqtSignal, QTimer
from PyQt5.QtGui import QTextDocument, QImage, QMouseEvent
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt5.QtWidgets import QTextBrowser


class ChatbotBrowser(QTextBrowser):
    show_setting_dlg = pyqtSignal()
    trigger_feedback = pyqtSignal(int)
    trigger_repeat = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.markdown_content = ""
        self.auto_scroll_to_bottom = True
        self.setMouseTracking(True)

        # Use a dictionary to cache downloaded images to prevent multiple downloads
        self.image_cache = {}

        # pending loading parameters.
        self.pending_images = set()
        self.waiting_timer = QTimer(self)
        self.waiting_timer.timeout.connect(self._finalize_markdown_display)

        self.network_manager = QNetworkAccessManager(self)
        self.network_manager.finished.connect(self._on_image_downloaded)

        # prevent append content in multithread.
        self.content_lock = Lock()

        self.anchorClicked.connect(self.handle_click_chatbot_anchor)

        self.feedback_text = self.tr("Was this answer helpful? [Yes](agent://feedback/5) | [No](agent://feedback/1) | [Repeat](agent://repeat)")
        self.tail_splited_line = "\n\n---------\n\n"
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

        # Do not load unknown format of resource.
        return None

    def append_markdown(self, content: str, scroll_to_bottom=True):
        # acquire lock
        if not self.content_lock.acquire(blocking=False):
            # only append to variable without really drawing it.
            self.markdown_content += content
            return

        try:
            # save current scroll value.
            scrollbar = self.verticalScrollBar()
            current_scroll_value = scrollbar.value()

            self.markdown_content += content

            # clean all html tags
            self.markdown_content = self.clean_html_tag(self.markdown_content)

            # update markdown content
            self.setMarkdown(self.markdown_content)

            if scroll_to_bottom and self.auto_scroll_to_bottom:
                self.scroll_to_bottom()
            else:
                # resume scroll bar value and disable auto scrolling to bottom.
                scrollbar.setValue(current_scroll_value)
                self.auto_scroll_to_bottom = False
        finally:
            # release lock
            self.content_lock.release()

    def pre_process_markdown(self):
        # resume auto scroll to bottom.
        self.auto_scroll_to_bottom = True
        self.pending_images.clear()
        self.waiting_timer.stop()

    def post_process_markdown(self, show_feedback=True):
        # add feedback
        if show_feedback:
            self.markdown_content += "\n\n" + self.feedback_text

        self.markdown_content += self.tail_splited_line

        # deal with upl-image-preview block.
        self.markdown_content = self.convert_upl_to_markdown_image(self.markdown_content)

        # replace failed image with links.
        self.markdown_content = self.replace_failed_images_with_links(self.markdown_content)

        # wait for finalizing.
        self.waiting_timer.start(500)

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
        return re.sub(r'<\/?[a-zA-Z][^>]*>', '', markdown_text)

    def clear(self):
        self.markdown_content = ""
        self.setMarkdown("")
        self.image_cache.clear()
        self.auto_scroll_to_bottom = True
        self.pending_images.clear()
        self.waiting_timer.stop()

    def scroll_to_bottom(self):
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def wheelEvent(self, event):
        # forbid auto scroll to bottom
        self.auto_scroll_to_bottom = False
        super().wheelEvent(event)

    def handle_click_chatbot_anchor(self, link: QUrl):
        if link.scheme() == "agent":
            # use agent to process.
            process_name = link.host()
            if process_name == "applyvip":
                self.show_setting_dlg.emit()
            elif process_name == "feedback":
                self.trigger_feedback.emit(int(link.path()[1:]))
            elif process_name == "repeat":
                self.trigger_repeat.emit()
            return

        # open web browser
        url_str = link.url()
        webbrowser.open(url_str)

    def convert_upl_to_markdown_image(self, markdown_text):
        # regex: [upl-image-preview ...]
        pattern = r'\[upl-image-preview[^\]]*?url=([^\s\]]+)[^\]]*\]'
        converted_text = re.sub(pattern, r'\n\n![Image](\1)', markdown_text, flags=re.IGNORECASE)
        return converted_text

    def get_raw_markdown_content(self):
        self.content_lock.acquire()
        try:
            # return the whole content without feedback and tail text.
            ret_content = self.markdown_content
            ret_content = ret_content.replace(self.feedback_text, "")
            ret_content = ret_content.replace(self.tail_splited_line, "")
            return ret_content
        finally:
            self.content_lock.release()

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
                        if image_name:
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
                            if image_name:
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

        # build request
        request = QNetworkRequest(QUrl(url_string))
        request.setTransferTimeout(1000)
        self.network_manager.get(request)

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

    def _finalize_markdown_display(self):
        if len(self.pending_images) > 0:
            return

        current_scroll_value = self.verticalScrollBar().value()

        self.waiting_timer.stop()

        # finally update markdown
        self.setMarkdown(self.markdown_content)

        if self.auto_scroll_to_bottom:
            self.scroll_to_bottom()
        else:
            self.verticalScrollBar().setValue(current_scroll_value)
