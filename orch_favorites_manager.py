# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Orchestration Favorites Manager
   Provides Orchestration's favorites management
                              -------------------
        begin                : 2026-08-19
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
import os
import uuid
from dataclasses import asdict
from .compat import *
from .orch_manager import TaskPlan, SubTask
from qgis.core import QgsApplication

class OrchFavoritesManager:

    def __init__(self):
        self.favorites_file = self.__get_favorites_file_path()

    def put_favorite(self, chat_id: str, task_plan: TaskPlan):
        """add or update a favorite orchestration plan."""
        favorites = self._load_favorites()

        # update existing item if the chat_id already exists.
        for item in favorites:
            if item['chat_id'] == chat_id:
                item['task_plan'] = self._serialize_task_plan(task_plan)
                self._save_favorites(favorites)
                return

        # add new item if the chat_id not found.
        favorites.append({
            'chat_id': chat_id,
            'task_plan': self._serialize_task_plan(task_plan)
        })

        self._save_favorites(favorites)

    def remove_favorite(self, chat_id: str):
        """remove favorite by chat_id"""
        favorites = self._load_favorites()

        new_favorites = [item for item in favorites if item['chat_id'] != chat_id]

        if len(new_favorites) != len(favorites):
            self._save_favorites(new_favorites)
            return True
        return False

    def retrieve_favorite(self, chat_id):
        """retrieve the favorite orchestration plan base on chat_id."""
        favorites = self._load_favorites()
        for item in favorites:
            if item['chat_id'] == chat_id:
                item['task_plan'] = self._deserialize_task_plan(item.get('task_plan'))
                return item
        return None

    def enum_favorites(self):
        """enumerate all favorites sorted by chat_id."""
        favorites = self._load_favorites()
        for item in favorites:
            item['task_plan'] = self._deserialize_task_plan(item.get('task_plan'))
        return favorites

    def _serialize_task_plan(self, task_plan: TaskPlan):
        """serialize TaskPlan object to a json-serializable dict."""
        if task_plan is None:
            return None

        data = asdict(task_plan)
        data.pop('final_result', None)
        for sub_task in data.get('sub_tasks', []):
            sub_task.pop('status', None)
            sub_task.pop('result', None)
        return data

    def _deserialize_task_plan(self, data):
        """restore TaskPlan object from a dict."""
        if data is None:
            return None

        sub_tasks = []
        for sub_data in data.get('sub_tasks', []):
            sub_tasks.append(SubTask(
                id=sub_data.get('id', ''),
                name=sub_data.get('name', ''),
                description=sub_data.get('description', ''),
                dependencies=sub_data.get('dependencies', []),
                tool_calls=sub_data.get('tool_calls', [])
            ))

        return TaskPlan(
            original_task=data.get('original_task', ''),
            sub_tasks=sub_tasks,
            execution_order=data.get('execution_order', [])
        )

    def _load_favorites(self):
        """load favorites from file."""
        if not os.path.exists(self.favorites_file):
            return []

        try:
            with open(self.favorites_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    def _save_favorites(self, favorites):
        """save favorites to file."""
        try:
            # make sure the directory is existing.
            os.makedirs(os.path.dirname(self.favorites_file), exist_ok=True)

            with open(self.favorites_file, 'w', encoding='utf-8') as f:
                json.dump(favorites, f, ensure_ascii=False, indent=2)
        except IOError:
            pass

    def export_task_plan_to_json(self, filepath: str, chat_id: str):
        """export a favorite task plan to a json file."""
        favorite = self.retrieve_favorite(chat_id)
        if favorite is None or favorite.get("task_plan") is None:
            return False

        try:
            data = asdict(favorite["task_plan"])
            # Drop runtime-only fields to keep the exported plan clean.
            data.pop("final_result", None)
            for sub_task in data.get("sub_tasks", []):
                sub_task.pop("status", None)
                sub_task.pop("result", None)

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except (IOError, TypeError):
            return False

    def import_task_plan_from_json(self, filepath: str):
        """import a single task plan from a json file and add it to favorites."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            task_plan = self._deserialize_task_plan(data)
            if task_plan is None:
                return None

            new_chat_id = str(uuid.uuid4())
            self.put_favorite(new_chat_id, task_plan)
            return new_chat_id
        except (json.JSONDecodeError, IOError, TypeError, KeyError):
            return None

    def __get_favorites_file_path(self):
        """get the favorites file path"""
        profile_dir = QgsApplication.qgisSettingsDirPath()
        plugin_dir = os.path.join(profile_dir, "qgis-geo-knowledge-ai")
        return os.path.join(plugin_dir, "qgis-geo-knowledge-ai-plugin-orch-favorites.dat")
