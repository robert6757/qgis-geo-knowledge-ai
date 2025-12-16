# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 History Manager
  A manager class provides functions for managing visit history.
                              -------------------
        begin                : 2025-10-31
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
from PyQt5.QtCore import QStandardPaths

class HistoryManager:

    def __init__(self):
        self.history_file = self.__get_history_file_path()
    def put_history(self, timestamp: int, pre_timestamp:int, question: str, answer: str):
        """add new history"""
        histories = self._load_histories()

        # add new item if the timestamp not found.
        histories.append({
            'timestamp': timestamp,
            'pre_timestamp': pre_timestamp,
            'question': question,
            'answer': answer
        })

        self._save_histories(histories)

    def remove_history(self, timestamp: int):
        """remove history by timestamp"""
        histories = self._load_histories()

        new_histories = [item for item in histories if item['timestamp'] != timestamp]

        if len(new_histories) != len(histories):
            self._save_histories(new_histories)
            return True
        return False
    def retrieve_history(self, timestamp):
        """retrieve the history chat base on timestamp."""
        histories = self._load_histories()
        for item in histories:
            if item['timestamp'] == timestamp:
                return item
        return None
    def enum_question(self):
        """enumerate all question sorted by timestamp."""
        histories = self._load_histories()
        sorted_histories = sorted(histories, key=lambda x: x['timestamp'], reverse=True)
        return [item for item in sorted_histories]
    def clear_history(self):
        """clear all history"""
        try:
            if os.path.exists(self.history_file):
                os.remove(self.history_file)
                return True
            return True
        except OSError:
            return False
    def _load_histories(self):
        """load history from file."""
        if not os.path.exists(self.history_file):
            return []

        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    def _save_histories(self, histories):
        """save history to file."""
        try:
            # make sure the directory is existing.
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)

            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(histories, f, ensure_ascii=False, indent=2)
        except IOError:
            pass
    def __get_history_file_path(self):
        """get the history file path"""
        temp_dir = QStandardPaths.writableLocation(QStandardPaths.TempLocation)
        return os.path.join(temp_dir, "qgis-geo-knowledge-ai-plugin.dat")
