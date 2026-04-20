# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Complex Task Orchestration Manager
  Providing orchestration creation, process, trace and so on.
                              -------------------
        begin                : 2026-04-16
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
import copy
from enum import Enum
from typing import List, Dict, Any
from dataclasses import dataclass, field

from qgis.PyQt.QtCore import QThread, pyqtSignal, QUrl, QObject
from qgis.PyQt.QtNetwork import QNetworkAccessManager

from .compat import *
from .orch_tools import orch_support_tools, orch_execute_tool
from .orch_network import CTOrchNetwork
from .global_defs import *


class TaskStatus(Enum):
    """Enum representing task status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class SubTask:
    """SubTask dataclass representing a subtask."""
    id: str
    name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    dependencies: List[str] = field(default_factory=list)
    tool_calls: List[Dict] = field(default_factory=list)

@dataclass
class TaskPlan:
    """TaskPlan dataclass representing a plan."""
    original_task: str
    sub_tasks: List[SubTask] = field(default_factory=list)
    execution_order: List[str] = field(default_factory=list)
    final_result: str = ""

class CTOrchManager(QThread):

    # finish decomposing signal
    orch_decompose_finished = pyqtSignal(TaskPlan)
    # report error signal.
    error_occurred = pyqtSignal(str)
    # report subtask stream
    report_subtask_stream = pyqtSignal(str)

    def __init__(self, request):
        super().__init__()

        self.request = request
        self.prompt = ""
        self.task_plan = {}
        self.sub_task_results: Dict[str, str] = {}

        self.executing_tool_calls = []
        self.executing_tool_content = ''

        self.network_manager = QNetworkAccessManager()

    def run(self):
        # 1.decompose task
        decompose_subthread = CTOrchNetwork(request_data=self.request, orch_type=1)
        decompose_subthread.content_received.connect(self.on_received_task_plan)
        decompose_subthread.error_occurred.connect(self.on_error_occurred)
        decompose_subthread.start()

        # 2.run all task by order.
        decompose_subthread.wait()
        self.__run_all_subtask()

    def on_received_task_plan(self, content: str):
        self.task_plan = self.__parse_task_plan(content)
        self.orch_decompose_finished.emit(self.task_plan)

    def on_received_subtask_stream(self, content: str):
        json_response = json.loads(content)
        message_data = json_response.get("message", {})
        content = message_data.get("content", "")
        tool_calls_str = message_data.get("tool_calls", '')

        self.executing_tool_calls = self.__parse_tool_calls_from_content(tool_calls_str)
        self.executing_tool_content = content

        self.report_subtask_stream.emit(content)

    def on_error_occurred(self, error: str):
        self.error_occurred.emit(error)

    def __run_all_subtask(self):
        if not self.task_plan:
            self.error_occurred.emit(self.tr("Invalid task plan."))
            return

        self.report_subtask_stream.emit(self.tr("Start executing the task plan..."))

        execution_order = self.task_plan.execution_order

        for task_id in execution_order:
            # find next subtask.
            sub_task = next((st for st in self.task_plan.sub_tasks if st.id == task_id), None)
            if not sub_task:
                error_str = self.tr("[WARNING] Subtask [{}] not found, skip.").format(task_id)
                self.error_occurred.emit(error_str)
                continue

            # Check if all dependencies have been completed.
            unmet_deps = [dep for dep in sub_task.dependencies if dep not in self.sub_task_results]
            if unmet_deps:
                error_str = (self.tr(
                    "[WARNING] The dependency [{}] of subtask [{}] is incomplete. Try to continue execution.")
                             .format(unmet_deps, sub_task.id))
                self.error_occurred.emit(error_str)

            # execute the subtask.
            self.__execute_sub_task(sub_task)

    def __execute_sub_task(self, sub_task: SubTask) -> str:
        """
        execute single subtask

        Args:
            sub_task: object of subtask

        Returns:
            result of subtask
        """
        self.report_subtask_stream.emit(self.tr("Start executing the subtask:") + sub_task.name)

        # clear old variable.
        self.executing_tool_calls = []
        self.executing_tool_content = ""

        # Build the context (containing the results of completed subtasks).
        context = self.__build_context(exclude_task_id=sub_task.id)

        # Execute subtask
        result = self.__chat_with_tools_stream(
            message=sub_task.description,
            context=context
        )

        if result.get("success"):
            # Integration results (including tool execution results)
            final_content = result.get("content", "")
            tool_results = result.get("tool_results", [])

            if tool_results:
                # If any tools are invoked, their results will also be integrated into the final result.
                tool_summary = "\n".join([f"- {tr['tool_name']}: {tr['result']}" for tr in tool_results])
                final_result = f"{final_content}\n\nTool execution result:\n{tool_summary}"
            else:
                final_result = final_content

            # Check if the task is completed
            if self.__check_task_completion(sub_task, final_result):
                sub_task.status = TaskStatus.COMPLETED
                sub_task.result = final_result
                self.sub_task_results[sub_task.id] = final_result
                report_str = self.tr("[Completed] Subtask [{}] executed successfully.").format(sub_task.name)
                self.report_subtask_stream.emit(report_str)
            else:
                sub_task.status = TaskStatus.FAILED
                sub_task.result = f"The execution result did not meet expectations: {final_result}"
                report_str = self.tr("[Failure] The execution result of subtask [{}] did not meet expectations.").format(sub_task.name)
                self.error_occurred.emit(report_str)
        else:
            sub_task.status = TaskStatus.FAILED
            sub_task.result = result.get("error", "Unknown error")
            report_str = self.tr(
                "[Failure] Subtask [{}] failed to execute: [{}]").format(sub_task.name, sub_task.result)
            self.error_occurred.emit(report_str)

        return sub_task.result

    def __chat_with_tools_stream(self, message: str, context: str = "") -> Dict[str, Any]:
            tool_names = orch_support_tools()

            # Build a message containing context information
            content = message
            if context:
                content = f"{context}\n\nCurrent task: {message}"

            all_tool_response = ""
            all_tool_results = []
            max_tool_iterations = 5
            try:
                history = []
                for iteration in range(max_tool_iterations):
                    # use raw request to build the subtask request.
                    sub_task_request = copy.deepcopy(self.request)
                    sub_task_request["tools"] = tool_names
                    sub_task_request["prompt"] = content
                    sub_task_request["history"] = history

                    subtask_subthread = CTOrchNetwork(request_data=sub_task_request, orch_type=1)
                    subtask_subthread.content_received.connect(self.on_received_subtask_stream)
                    subtask_subthread.error_occurred.connect(self.on_error_occurred)
                    subtask_subthread.start()
                    subtask_subthread.wait()

                    if len(self.executing_tool_calls) == 0:
                        # Nothing to do, finish the subtask.
                        break

                    all_tool_response += self.executing_tool_content
                    for tool_call in self.executing_tool_calls:
                        func = tool_call.get("function", {})
                        tool_name = func.get("name", "")
                        arguments = func.get("arguments", {})

                        tool_result = orch_execute_tool(tool_name, arguments)

                        all_tool_results.append({
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "result": tool_result
                        })

                        # remember the result of tools.
                        history.append(f"Tool ID: {tool_call.get('id', '')}\n\n Tool execution result:\n{tool_result}")

                return {
                    "content": all_tool_response,
                    "tool_results": all_tool_results,
                    "success": True
                }

            except Exception as e:
                return {
                    "content": "",
                    "tool_results": [],
                    "success": False,
                    "error": str(e)
                }

    def __check_task_completion(self, sub_task: SubTask, result: str) -> bool:
        """
        判断子任务是否完成

        Args:
            sub_task: 子任务对象
            result: 执行结果

        Returns:
            True 表示完成，False 表示需要重新执行或调整
        """
        # 简单判断：如果结果不为空且没有错误信息，则认为完成
        if not result or result.strip() == "":
            return False

        error_keywords = ["错误", "error", "失败", "failed", "无法", "不能"]
        for keyword in error_keywords:
            if keyword in result.lower():
                # 进一步判断是否真的是错误
                if "计算错误" in result or "请求错误" in result:
                    return False

        return True

    def __build_context(self, exclude_task_id: str = None) -> str:
        """
        构建上下文信息，包含已完成子任务的结果

        Args:
            exclude_task_id: 要排除的子任务 ID（当前正在执行的任务）

        Returns:
            格式化的上下文字符串
        """
        if not self.sub_task_results:
            return ""

        context_parts = ["=== Results of completed subtasks ==="]
        for task_id, result in self.sub_task_results.items():
            if task_id != exclude_task_id:
                context_parts.append(f"[{task_id}]: {result}")
        context_parts.append("=== The above results are for reference only. ===")

        return "\n".join(context_parts)

    def __parse_task_plan(self, plan_json_str: str) -> TaskPlan:
        try:
            json_match = re.search(r'\{[\s\S]*\}', plan_json_str)
            if json_match:
                content = json_match.group()

            plan_data = json.loads(content)

            # build the task_plan object.
            sub_tasks = []
            for task_data in plan_data.get("sub_tasks", []):
                sub_task = SubTask(
                    id=task_data.get("id", str(uuid.uuid4())),
                    name=task_data.get("name", ""),
                    description=task_data.get("description", ""),
                    dependencies=task_data.get("dependencies", [])
                )
                sub_tasks.append(sub_task)

            task_plan = TaskPlan(
                original_task=self.prompt,
                sub_tasks=sub_tasks,
                execution_order=plan_data.get("execution_order", [st.id for st in sub_tasks])
            )
        except Exception as e:
            # Fail to split the complex task. Create a default subtask.
            default_task = SubTask(
                id="task_1",
                name="Run Task",
                description=self.prompt,
                dependencies=[]
            )
            task_plan = TaskPlan(
                original_task=self.prompt,
                sub_tasks=[default_task],
                execution_order=["task_1"]
            )
            return task_plan

        return task_plan

    def __parse_tool_calls_from_content(self, content: str) -> list:
        tool_calls = []

        xml_pattern = r'<function=(\w+)>([\s\S]*?)</function>'
        for match in re.finditer(xml_pattern, content):
            tool_name = match.group(1)
            params_block = match.group(2)

            arguments = {}

            param_matches = re.findall(r'<parameter=(\w+)>([^<]+)</parameter>', params_block)
            if param_matches:
                for param_name, param_value in param_matches:
                    arguments[param_name.strip()] = param_value.strip()
            else:
                params_str = params_block.strip()
                try:
                    arguments = json.loads(params_str)
                except json.JSONDecodeError:
                    for pair in params_str.split(','):
                        if '=' in pair:
                            key, value = pair.split('=', 1)
                            arguments[key.strip()] = value.strip()

            if arguments or tool_name:
                tool_call = {
                    "id": str(uuid.uuid4()),
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": arguments
                    }
                }
                tool_calls.append(tool_call)

        return tool_calls

