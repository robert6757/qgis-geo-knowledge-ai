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

from qgis.PyQt.QtCore import QThread, pyqtSignal, QCoreApplication, QSemaphore
from qgis.PyQt.QtNetwork import QNetworkAccessManager

from .compat import *
from .orch_tools import SUPPORTED_TOOLS, OrchToolExecutor
from .orch_network import CTOrchNetwork
from .global_defs import *

class TaskStatus(Enum):
    """Enum representing task status."""
    PENDING = "Pending"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"

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

    # report decomposing stream
    report_decompose_stream = pyqtSignal(str)
    # finish decomposing signal
    orch_decompose_finished = pyqtSignal(TaskPlan)
    # start one subtask signal
    orch_subtask_started = pyqtSignal(SubTask)
    # finish one subtask signal
    orch_subtask_finished = pyqtSignal(SubTask)
    # report error signal.
    error_occurred = pyqtSignal(str)
    # report warning signal.
    warning_occurred = pyqtSignal(str)
    # report subtask stream
    report_subtask_stream = pyqtSignal(str)
    # report conclusion stream
    report_conclusion_stream = pyqtSignal(str)
    # finish all orchestration.
    finish_all_orchestration = pyqtSignal()
    # trigger code execution assurance.
    ensure_code_execution = pyqtSignal()
    # report thinking stream
    report_thinking_stream = pyqtSignal(str)

    def __init__(self, iface, request):
        super().__init__()

        self.iface = iface
        self._stop_flag = False
        self.request = request
        self.prompt = ""
        self.sub_task_results: Dict[str, str] = {}
        # 0: automate 1: step
        self.task_plan_execute_type = 0
        # 0: next subtask 1: repeat current subtask
        self.sub_task_execute_type = 0
        # CodeExecution in postprocess.
        self.code_execution = None

        self.network_manager = QNetworkAccessManager()

        # Tool Executor.
        self.request["tools"] = SUPPORTED_TOOLS
        self.tool_executor = OrchToolExecutor(iface)

        # Execution semaphore for controlling subtask execution start.
        self._execution_semaphore = QSemaphore(0)
        self._subtask_execution_semaphore = QSemaphore(0)
        self._ensure_code_exec_semaphore = QSemaphore(0)

        # Track the currently running CTOrchNetwork subthread for abort support.
        self._current_subthread = None

    def run(self):
        # 1.decompose task
        self.report_decompose_stream.emit(self.tr("**Thinking...**"))

        decompose_subthread = CTOrchNetwork(request_data=self.request, orch_type=1)
        decompose_subthread.error_occurred.connect(self.on_network_error_occurred)
        decompose_subthread.thinking_received.connect(self.on_received_thinking_stream)
        self._current_subthread = decompose_subthread
        decompose_subthread.start()
        decompose_subthread.wait()
        self._current_subthread = None

        task_plan, user_info = self.__parse_task_plan(decompose_subthread.get_raw_response())
        if not task_plan:
            self.error_occurred.emit("\n\n" + self.tr("Invalid Task plan!"))
            self._stop_flag = True
            return

        if user_info and user_info["remaining_vip_ticket"]:
            self.report_decompose_stream.emit(self.tr("VIP requests remaining: ")+ str(user_info["remaining_vip_ticket"]))

        self.orch_decompose_finished.emit(task_plan)

        # Wait for execution semaphore to start subtask execution.
        self._execution_semaphore.acquire()

        # make sure CodeExecution is valid.
        self.ensure_code_execution.emit()
        self._ensure_code_exec_semaphore.acquire()

        if self.code_execution is None:
            self.error_occurred.emit(self.tr("Task cannot continue because the code execution module is unavailable!"))
            self._stop_flag = True
            return

        # 2.run all subtask
        if self.task_plan_execute_type == 0:
            self.__run_all_subtask(task_plan)
        elif self.task_plan_execute_type == 1:
            self.__step_all_subtask(task_plan)

        # 3.conclude result
        self.__finalize_result()

    def stop(self):
        self._stop_flag = True

        # Abort the currently running CTOrchNetwork subthread to immediately close the LLM connection.
        if self._current_subthread is not None:
            self._current_subthread.abort()
            self._current_subthread = None

        # Release semaphore to unblock execution.
        while self._execution_semaphore.tryAcquire():
            pass
        self._execution_semaphore.release()

        while self._subtask_execution_semaphore.tryAcquire():
            pass
        self._subtask_execution_semaphore.release()

    def automate_task_plan(self):
        self.task_plan_execute_type = 0

        # Release semaphore to trigger subtask execution.
        self._execution_semaphore.release()

    def step_task_plan(self):
        self.task_plan_execute_type = 1

        # Release semaphore to trigger subtask execution.
        self._execution_semaphore.release()

    def next_sub_task(self):
        self.sub_task_execute_type = 0

        # Drain any extra semaphores to prevent accumulation from repeated clicks
        while self._subtask_execution_semaphore.tryAcquire():
            pass
        # Release semaphore to trigger next subtask execution.
        self._subtask_execution_semaphore.release()

    def repeat_sub_task(self):
        self.sub_task_execute_type = 1

        # Drain any extra semaphores to prevent accumulation from repeated clicks
        while self._subtask_execution_semaphore.tryAcquire():
            pass
        # Release semaphore to trigger repeat subtask execution.
        self._subtask_execution_semaphore.release()

    def finish_ensure_code_execution(self, code_execution):
        self.code_execution = code_execution
        self._ensure_code_exec_semaphore.release()

    def __run_all_subtask(self, task_plan: TaskPlan):
        if self._stop_flag:
            return

        self.report_subtask_stream.emit(self.tr("**Start automated execution of the task plan:**"))

        execution_order = task_plan.execution_order

        for task_id in execution_order:
            if self._stop_flag:
                break

            # find next subtask.
            sub_task = next((st for st in task_plan.sub_tasks if st.id == task_id), None)
            if not sub_task:
                error_str = self.tr("[WARNING] Subtask [{}] not found, skip.").format(task_id)
                self.warning_occurred.emit(error_str)
                continue

            # Check if all dependencies have been completed.
            unmet_deps = [dep for dep in sub_task.dependencies if dep not in self.sub_task_results]
            if unmet_deps:
                error_str = (self.tr(
                    "[WARNING] The dependency [{}] of subtask [{}] is incomplete. Try to continue execution.")
                             .format(unmet_deps, sub_task.id))
                self.warning_occurred.emit(error_str)

            # execute the subtask.
            self.__execute_sub_task(sub_task)

    def __step_all_subtask(self, task_plan: TaskPlan):
        if self._stop_flag:
            return

        self.report_subtask_stream.emit(self.tr("**Start step-by-step execution of the task plan:**"))

        execution_order = task_plan.execution_order

        for sub_task_id in execution_order:
            if self._stop_flag:
                break

            # find next subtask.
            sub_task = next((st for st in task_plan.sub_tasks if st.id == sub_task_id), None)
            if not sub_task:
                error_str = self.tr("[WARNING] Subtask [{}] not found, skip.").format(sub_task_id)
                self.warning_occurred.emit(error_str)
                continue

            # Check if all dependencies have been completed.
            unmet_deps = [dep for dep in sub_task.dependencies if dep not in self.sub_task_results]
            if unmet_deps:
                error_str = (self.tr(
                    "[WARNING] The dependency [{}] of subtask [{}] is incomplete. Try to continue execution.")
                             .format(unmet_deps, sub_task.id))
                self.warning_occurred.emit(error_str)

            self.orch_subtask_started.emit(sub_task)

            # execute the subtask.
            self.__execute_sub_task(sub_task)

            self.orch_subtask_finished.emit(sub_task)

            # Wait for execution semaphore to start next subtask execution.
            self._subtask_execution_semaphore.acquire()

            if self.sub_task_execute_type == 1:
                # Reset the execute type
                self.sub_task_execute_type = 0
                # Remove the result of the current subtask to allow re-execution
                if sub_task_id in self.sub_task_results:
                    del self.sub_task_results[sub_task_id]
                # Insert the current subtask id back into execution_order after current position
                current_index = execution_order.index(sub_task_id)
                execution_order.insert(current_index + 1, sub_task_id)
                # Reset subtask status to pending
                sub_task.status = TaskStatus.PENDING
                sub_task.result = ""

    def on_received_subtask_stream(self, content: str):
        # self.report_subtask_stream.emit(content)
        pass

    def on_network_error_occurred(self, error: str):
        self.error_occurred.emit(error)
        self._stop_flag = True

    def on_received_conclusion(self, conclusion: str):
        try:
            conclusion_json = json.loads(conclusion)
            message_data = conclusion_json.get("message", {})
            self.report_conclusion_stream.emit(message_data.get("content", ""))
        except Exception as e:
            self.error_occurred.emit(str(e))
            self._stop_flag = True

    def on_received_thinking_stream(self, content: str):
        self.report_thinking_stream.emit(content)

    def __execute_sub_task(self, sub_task: SubTask) -> str:
        """
        execute single subtask

        Args:
            sub_task: object of subtask

        Returns:
            result of subtask
        """
        if self._stop_flag:
            return ""

        self.report_subtask_stream.emit(self.tr("Start executing the subtask:") + sub_task.name)

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
            is_completed, error_msg = self.__check_subtask_completion(sub_task, final_result)
            if is_completed:
                sub_task.status = TaskStatus.COMPLETED
                sub_task.result = final_result
                # To improve the focus of subtasks, only final_content is added here.
                self.sub_task_results[sub_task.id] = final_content
                report_str = self.tr("[Completed] Subtask [{}] executed successfully.").format(sub_task.name)
                self.report_subtask_stream.emit(report_str)
            else:
                sub_task.status = TaskStatus.FAILED
                sub_task.result = f"The execution result did not meet expectations: {final_result}."
                report_str = self.tr("[Failure] The execution result of subtask [{}] did not meet expectations. {}").format(sub_task.name, error_msg)
                self.report_subtask_stream.emit(report_str)
        else:
            sub_task.status = TaskStatus.FAILED
            sub_task.result = result.get("error", "Unknown error")
            report_str = self.tr(
                "[Failure] Subtask [{}] failed to execute: [{}]").format(sub_task.name, sub_task.result)
            self.report_subtask_stream.emit(report_str)

        return sub_task.result

    def __chat_with_tools_stream(self, message: str, context: str = "") -> Dict[str, Any]:
            # Build a message containing context information
            if self._stop_flag:
                return {
                    "content": "",
                    "tool_results": [],
                    "success": False,
                    "error": ""
                }

            tool_response = ""
            all_tool_results = []
            max_tool_iterations = 12
            try:
                tool_call_results = []
                for iteration in range(max_tool_iterations):
                    # use raw request to build the subtask request.
                    sub_task_request = copy.deepcopy(self.request)
                    sub_task_request["prompt"] = message
                    sub_task_request["context"] = context
                    sub_task_request["tool_call_results"] = tool_call_results

                    subtask_subthread = CTOrchNetwork(request_data=sub_task_request, orch_type=2)
                    subtask_subthread.content_received.connect(self.on_received_subtask_stream)
                    subtask_subthread.error_occurred.connect(self.on_network_error_occurred)
                    self._current_subthread = subtask_subthread
                    subtask_subthread.start()
                    subtask_subthread.wait()
                    self._current_subthread = None
                    subtask_response_json_str = subtask_subthread.get_raw_response()

                    if self._stop_flag or not subtask_response_json_str:
                        break

                    subtask_response_json = json.loads(subtask_response_json_str)
                    message_data = subtask_response_json.get("message", {})

                    executing_tool_calls = message_data.get("tool_calls") or []
                    executing_tool_content = message_data.get("content", "")

                    tool_response = executing_tool_content
                    if len(executing_tool_calls) == 0:
                        # Nothing to do, finish the subtask.
                        break

                    for tool_call in executing_tool_calls:
                        func = tool_call.get("function", {})
                        tool_name = func.get("name", "")
                        arguments = func.get("arguments", {})
                        if isinstance(arguments, str):
                            # maybe the arguments is string, not json object.
                            try:
                                arguments = json.loads(arguments)
                            except json.JSONDecodeError:
                                arguments = {}

                        result_container = {"result": None}
                        def on_completed(result, rc=result_container):
                            rc["result"] = result

                        def on_error(error, rc=result_container):
                            rc["result"] = error

                        self.tool_executor.execution_completed.connect(on_completed, QueuedConnection)
                        self.tool_executor.execution_error.connect(on_error, QueuedConnection)
                        self.tool_executor.execute_requested.emit(tool_name, arguments)

                        # Waiting for execution to complete
                        while result_container["result"] is None:
                            QCoreApplication.processEvents()

                        self.tool_executor.execution_completed.disconnect(on_completed)
                        self.tool_executor.execution_error.disconnect(on_error)

                        tool_result = result_container["result"]
                        all_tool_results.append({
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "result": tool_result
                        })

                        # remember the result of tools.
                        tool_call_history = []
                        tool_call_history.append(tool_call)
                        tool_call_history.append(tool_result)
                        tool_call_results.append(tool_call_history)

                return {
                    "content": tool_response,
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

    def __check_subtask_completion(self, sub_task: SubTask, result: str) -> (bool, str):
        if self._stop_flag:
            return False, ''

        if not result or result.strip() == "":
            return False, ''

        evaluate_request = copy.deepcopy(self.request)
        evaluate_request["prompt"] = sub_task.description
        evaluate_request["history"] = [[result]]

        evaluate_subthread = CTOrchNetwork(request_data=evaluate_request, orch_type=3)
        evaluate_subthread.error_occurred.connect(self.on_network_error_occurred)
        self._current_subthread = evaluate_subthread
        evaluate_subthread.start()
        evaluate_subthread.wait()
        self._current_subthread = None

        evaluate_result = evaluate_subthread.get_raw_response()
        if not evaluate_result:
            return False, ''

        evaluate_json = json.loads(evaluate_result)
        message_data = evaluate_json.get("message", {})
        content = message_data.get("content", "")
        # If an [ERROR] message appears, the process is considered a failure.
        if "[ERROR]" in content:
            return False, content

        if "[COMPLETED]" in content:
            return True, ''

        return False, content

    def __build_context(self, exclude_task_id: str = None) -> str:
        """
        Build context information, including the results of completed subtasks.

        Args:
            exclude_task_id: Subtask IDs to exclude (currently executing tasks)

        Returns:
            context string
        """
        if not self.sub_task_results:
            return ""

        context_parts = ["=== Results of completed subtasks ==="]
        for task_id, result in self.sub_task_results.items():
            if task_id != exclude_task_id:
                context_parts.append(f"[{task_id}]: {result}")
        context_parts.append("=== The above results are for reference only. ===")

        return "\n".join(context_parts)

    def __parse_task_plan(self, plan_json_str: str) -> (TaskPlan, dict):
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
            return None, None

        return task_plan, plan_data.get("user_info")

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

    def __finalize_result(self):
        """
        Integrate the results of all subtasks to generate the final answer.
        """
        if self._stop_flag:
            return

        if not self.sub_task_results:
            self.error_occurred.emit(self.tr("Error: No subtask execution result."))
            self._stop_flag = True
            return

        self.report_conclusion_stream.emit(self.tr("**Summary of tasks:**"))

        sub_task_request = copy.deepcopy(self.request)

        # put result of subtask as history.
        subtask_results = []
        for task_id, result in self.sub_task_results.items():
            subtask_results.append([f"[{task_id}]: {result}"])
        sub_task_request["history"] = subtask_results

        finalize_subthread = CTOrchNetwork(request_data=sub_task_request, orch_type=4)
        finalize_subthread.content_received.connect(self.on_received_conclusion)
        finalize_subthread.error_occurred.connect(self.on_network_error_occurred)
        self._current_subthread = finalize_subthread
        finalize_subthread.start()
        finalize_subthread.wait()
        self._current_subthread = None

        self.finish_all_orchestration.emit()
