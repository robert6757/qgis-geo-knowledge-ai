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
import re
import uuid
from dataclasses import asdict
from .compat import *
from .orch_manager import TaskPlan, SubTask
from qgis.core import QgsApplication, QgsBlockingNetworkRequest, QgsSettings
from qgis.PyQt.QtCore import QUrl, QUrlQuery
from qgis.PyQt.QtNetwork import QNetworkRequest

from .global_defs import AI_SERVER_DOMAIN, USER_TOKEN_PARAMS_TAG

class OrchFavoritesManager:

    FAVORITES_ENUM_URL = "/ai/v1/orch/favorites/enum"
    FAVORITES_GET_URL = "/ai/v1/orch/favorites/get"

    def __init__(self):
        self.favorites_file = self.__get_favorites_file_path()
        # Maps randomly generated chat_id for server favorites to their
        # original_task name, so retrieve_favorite can fetch the full plan.
        self._remote_chat_id_map = {}

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

    def retrieve_favorite(self, chat_id, inject_auth_tokens):
        """retrieve the favorite orchestration plan base on chat_id.

        First try to find it in local storage. If not found, treat chat_id
        as the server-side favorite name (original_task) and fetch it from
        the remote server. Server favorites do not contain chat_id, so a
        random UUID is generated to build the local-style item.
        """
        favorites = self._load_favorites()
        for item in favorites:
            if item['chat_id'] == chat_id:
                item['task_plan'] = self._deserialize_task_plan(item.get('task_plan'))
                if inject_auth_tokens:
                    self._inject_auth_tokens(item['task_plan'])
                return item

        # Local not found, try to fetch from server by name.
        # For server favorites generated in enum_favorites, the chat_id is a
        # random UUID mapped to the original_task name.
        remote_name = self._remote_chat_id_map.get(chat_id)
        if not remote_name:
            return None

        remote_favorite = self._fetch_remote_favorite_by_name(remote_name)
        if not remote_favorite:
            return None

        if inject_auth_tokens:
            self._inject_auth_tokens(remote_favorite['task_plan'])
        return remote_favorite

    def enum_favorites(self):
        """enumerate all favorites from local storage and remote server.

        Local items are tagged with source='local'; remote items are tagged
        with source='server'. Remote favorites have a randomly generated
        chat_id because the server does not provide one.
        """
        local_favorites = self._load_favorites()
        for item in local_favorites:
            item['task_plan'] = self._deserialize_task_plan(item.get('task_plan'))
            item['source'] = 'local'

        remote_favorites = self._fetch_remote_favorites()

        # To ensure the output is neat, sorting is used here.
        local_favorites.sort(key=lambda item: item.get('task_plan', TaskPlan(original_task='')).original_task or '')
        remote_favorites.sort(key=lambda item: item.get('task_plan', TaskPlan(original_task='')).original_task or '')

        return local_favorites + remote_favorites

    def _inject_auth_tokens(self, task_plan):
        """Scan original_task and sub-task descriptions for [AUTH_TOKEN:name]
        placeholders and replace them with the values stored in QGIS settings."""
        if task_plan is None:
            return

        gSetting = QgsSettings()

        text_fields = [task_plan.original_task]
        text_fields.extend(st.description for st in task_plan.sub_tasks)

        token_names = set()
        for text in text_fields:
            token_names.update(re.findall(r"\[AUTH_TOKEN:(.*?)\]", text or ""))

        for token_name in token_names:
            saved_token = gSetting.value(USER_TOKEN_PARAMS_TAG + f"/{token_name}", "")
            if not saved_token:
                continue
            placeholder = f"[AUTH_TOKEN:{token_name}]"
            task_plan.original_task = task_plan.original_task.replace(placeholder, saved_token)
            for st in task_plan.sub_tasks:
                st.description = st.description.replace(placeholder, saved_token)

    def _fetch_remote_favorites(self):
        """fetch favorite names from the server and build favorite items.

        The server's /enum endpoint returns a list of original_task strings.
        For each name, a random chat_id is generated and the task_plan is
        reconstructed from the original_task string only (sub_tasks remain
        empty until the full plan is retrieved via retrieve_favorite).
        """
        url = AI_SERVER_DOMAIN.rstrip('/') + self.FAVORITES_ENUM_URL
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Accept", b"application/json")

        blocking_request = QgsBlockingNetworkRequest()
        err_code = blocking_request.get(request)
        if err_code != QgsBlockingNetworkRequest.ErrorCode.NoError:
            print(f"Failed to fetch remote favorites: {err_code}")
            return []

        reply = blocking_request.reply()
        if reply is None:
            return []

        try:
            content = bytes(reply.content().data()).decode('utf-8')
            names = json.loads(content)
            if not isinstance(names, list):
                return []
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as e:
            print(f"Error parsing remote favorites: {e}")
            return []

        # Rebuild the chat_id -> original_task mapping each time we enumerate
        # remote favorites, because the generated UUIDs are not persistent.
        self._remote_chat_id_map.clear()
        results = []
        for name in names:
            if not isinstance(name, str):
                continue
            chat_id = str(uuid.uuid4())
            self._remote_chat_id_map[chat_id] = name
            task_plan = TaskPlan(original_task=name)
            results.append({
                'chat_id': chat_id,
                'task_plan': task_plan,
                'source': 'server'
            })
        return results

    def _fetch_remote_favorite_by_name(self, name):
        """fetch a single favorite from the server by name.

        The server expects a 'name' query parameter which can be the
        original_task. A random chat_id is generated because the server
        response does not contain one.
        """
        url = QUrl(AI_SERVER_DOMAIN.rstrip('/') + self.FAVORITES_GET_URL)
        url_query = QUrlQuery()
        url_query.addQueryItem('name', name)
        url.setQuery(url_query)

        request = QNetworkRequest(url)
        request.setRawHeader(b"Accept", b"application/json")

        blocking_request = QgsBlockingNetworkRequest()
        err_code = blocking_request.get(request)
        if err_code != QgsBlockingNetworkRequest.ErrorCode.NoError:
            print(f"Failed to fetch remote favorite '{name}': {err_code}")
            return None

        reply = blocking_request.reply()
        if reply is None:
            return None

        try:
            content = bytes(reply.content().data()).decode('utf-8')
            data = json.loads(content)
            if not isinstance(data, dict):
                return None

            task_plan = self._deserialize_task_plan(data)
            if task_plan is None:
                return None

            chat_id = str(uuid.uuid4())
            return {
                'chat_id': chat_id,
                'task_plan': task_plan,
                'source': 'server'
            }
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as e:
            print(f"Error parsing remote favorite '{name}': {e}")
            return None

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
        favorite = self.retrieve_favorite(chat_id, inject_auth_tokens=True)
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
