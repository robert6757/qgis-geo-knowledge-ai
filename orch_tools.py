# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 Define Tools for Orchestration
  Define all tools in the subtask for orchestration.
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

def orch_support_tools():
    return ["get_weather", "get_current_time", "calculate_expression", "calculate_random", "get_timestamp"]

def orch_execute_tool(tool_name: str, arguments: dict) -> str:
    """
    Execute orchestration tool in GUI thread.

    Args:
        tool_name: tool name
        arguments: tool arguments

    Returns:
        execute tool result.
    """

    # FIXME.
    # must be in GUI thread

    if tool_name == "get_weather":
        city = arguments.get("city", "未知城市")
        weather_data = {
            "北京": {"temp": 25, "condition": "晴", "humidity": 45},
            "上海": {"temp": 28, "condition": "多云", "humidity": 65},
            "广州": {"temp": 32, "condition": "小雨", "humidity": 80},
            "深圳": {"temp": 30, "condition": "晴", "humidity": 70},
        }
        data = weather_data.get(city, {"temp": 26, "condition": "晴", "humidity": 50})
        return f"{city}当前天气：{data['condition']}，温度：{data['temp']}°C，湿度：{data['humidity']}%"

    elif tool_name == "get_current_time":
        city = arguments.get("city", "未知城市")
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"{city}当前时间：{current_time}"

    elif tool_name == "calculate_expression":
        expression = arguments.get("expression", "")
        try:
            result = eval(expression, {"__builtins__": {}}, {"sqrt": lambda x: x ** 0.5})
            return f"计算结果：{expression} = {result}"
        except Exception as e:
            return f"计算错误：{e}"

    elif tool_name == "calculate_random":
        seed = arguments.get("seed", 0)
        count = arguments.get("count", 1)
        seed = int(seed)
        count = int(count)
        import random
        random.seed(seed)
        if count <= 1:
            random_result = random.random()
        else:
            random_result = [random.random() for _ in range(count)]
        return f"计算结果：{random_result}"

    elif tool_name == "get_timestamp":
        import time
        return f"时间戳：{time.time()}"

    else:
        return f"未知工具：{tool_name}"


