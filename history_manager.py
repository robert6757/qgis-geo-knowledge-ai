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
from dataclasses import asdict
from .compat import *
from .orch_manager import TaskPlan, SubTask, TaskStatus

class HistoryManager:

    def __init__(self):
        self.history_file = self.__get_history_file_path()

    def put_history(self, timestamp: int, pre_timestamp:int, question: str, answer: str, task_plan: TaskPlan):
        """add new history"""
        histories = self._load_histories()

        # add new item if the timestamp not found.
        histories.append({
            'timestamp': timestamp,
            'pre_timestamp': pre_timestamp,
            'question': question,
            'answer': answer,
            'task_plan': self._serialize_task_plan(task_plan)
        })

        self._save_histories(histories)

    def _serialize_task_plan(self, task_plan: TaskPlan):
        """serialize TaskPlan object to a json-serializable dict."""
        if task_plan is None:
            return None

        data = asdict(task_plan)
        for sub_task in data.get('sub_tasks', []):
            status = sub_task.get('status')
            if isinstance(status, TaskStatus):
                sub_task['status'] = status.value
        return data

    def _deserialize_task_plan(self, data):
        """restore TaskPlan object from a dict."""
        if data is None:
            return None

        sub_tasks = []
        for sub_data in data.get('sub_tasks', []):
            status_value = sub_data.get('status', TaskStatus.PENDING.value)
            try:
                status = TaskStatus(status_value)
            except ValueError:
                status = TaskStatus.PENDING

            sub_tasks.append(SubTask(
                id=sub_data.get('id', ''),
                name=sub_data.get('name', ''),
                description=sub_data.get('description', ''),
                status=status,
                result=sub_data.get('result', ''),
                dependencies=sub_data.get('dependencies', []),
                tool_calls=sub_data.get('tool_calls', [])
            ))

        return TaskPlan(
            original_task=data.get('original_task', ''),
            sub_tasks=sub_tasks,
            execution_order=data.get('execution_order', []),
            final_result=data.get('final_result', '')
        )

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
                item['task_plan'] = self._deserialize_task_plan(item.get('task_plan'))
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
        temp_dir = QStandardPaths.writableLocation(TempLocation)
        return os.path.join(temp_dir, "qgis-geo-knowledge-ai-plugin.dat")
