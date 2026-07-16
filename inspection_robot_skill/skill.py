import os
import json
import asyncio
from typing import Any, Dict

import websockets
from mcp.server.fastmcp import FastMCP


# 真实巡检机器人 WebSocket 地址
ROBOT_WS = os.getenv("ROBOT_WS", "ws://10.184.5.91:5000")
ROBOT_ID = os.getenv("ROBOT_ID", "1")

# Skill Server 地址。A 电脑本机运行时也建议监听 0.0.0.0
SKILL_HOST = os.getenv("SKILL_HOST", "0.0.0.0")
SKILL_PORT = int(os.getenv("SKILL_PORT", "8000"))


mcp = FastMCP(
    name="inspection_robot",
    stateless_http=True,
    host=SKILL_HOST,
    port=SKILL_PORT,
)


async def send_robot(payload: Dict[str, Any], timeout: int = 8) -> Dict[str, Any]:
    """
    向巡检机器人 WebSocket 服务发送一条 JSON 指令。
    """
    payload = dict(payload)
    payload["robot_id"] = str(payload.get("robot_id", ROBOT_ID))

    try:
        async with websockets.connect(
            ROBOT_WS,
            open_timeout=5,
            ping_timeout=5,
            close_timeout=3,
        ) as ws:
            await ws.send(json.dumps(payload, ensure_ascii=False))
            reply = await asyncio.wait_for(ws.recv(), timeout=timeout)

        try:
            return json.loads(reply)
        except json.JSONDecodeError:
            return {
                "status": "raw",
                "raw": reply,
                "payload": payload,
            }

    except asyncio.TimeoutError:
        return {
            "status": "error",
            "error": "Robot WebSocket response timed out",
            "robot_ws": ROBOT_WS,
            "payload": payload,
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "robot_ws": ROBOT_WS,
            "payload": payload,
        }


@mcp.tool()
async def get_robot_status() -> Dict[str, Any]:
    """查询机器人当前状态，包括电量、任务状态、当前位置、CPU、内存、避障状态等。"""
    payload = {
        "cmd_type": "3",
        "get_robot_info": "3",
    }
    return await send_robot(payload)


@mcp.tool()
async def get_paths() -> Dict[str, Any]:
    """查询机器人已有巡检路径列表。"""
    payload = {
        "cmd_type": "3",
        "get_robot_info": "1",
    }
    return await send_robot(payload)


@mcp.tool()
async def get_points(path_id: str) -> Dict[str, Any]:
    """查询指定巡检路径下的所有点位。"""
    payload = {
        "cmd_type": "3",
        "get_robot_info": "2",
        "path_id": str(path_id),
    }
    return await send_robot(payload)


@mcp.tool()
async def stop_current_task() -> Dict[str, Any]:
    """停止机器人当前任务。现场异常时优先调用。"""
    payload = {
        "cmd_type": "2",
        "robot_control": "4",
    }
    return await send_robot(payload)


@mcp.tool()
async def return_charge() -> Dict[str, Any]:
    """让机器人返回充电桩。"""
    payload = {
        "cmd_type": "2",
        "robot_control": "5",
    }
    return await send_robot(payload)


@mcp.tool()
async def quick_arrival(path_id: str, path_position_id: str) -> Dict[str, Any]:
    """让机器人快速到达指定点位。需要先确认路径 ID 和点位 ID。"""
    payload = {
        "cmd_type": "2",
        "robot_control": "10",
        "path_id": str(path_id),
        "path_position_id": str(path_position_id),
    }
    return await send_robot(payload)


@mcp.tool()
async def single_point_patrol(path_id: str, path_position_id: str) -> Dict[str, Any]:
    """让机器人到指定点位执行该点检测任务。"""
    payload = {
        "cmd_type": "2",
        "robot_control": "3",
        "path_id": str(path_id),
        "path_position_id": str(path_position_id),
    }
    return await send_robot(payload)


@mcp.tool()
async def auto_patrol(path_id: str, safety_confirm: str = "") -> Dict[str, Any]:
    """
    让机器人按指定路径自动巡检。
    为防止误触发，只有 safety_confirm='SAFE' 时才会真正执行。
    """
    if safety_confirm != "SAFE":
        return {
            "status": "blocked",
            "message": "自动巡检需要 safety_confirm='SAFE'。请先确认现场安全、路线无障碍、急停可用。",
        }

    payload = {
        "cmd_type": "2",
        "robot_control": "1",
        "path_id": str(path_id),
    }
    return await send_robot(payload)


@mcp.tool()
async def continue_patrol(path_id: str) -> Dict[str, Any]:
    """接续巡检。用于自动巡检被停止后继续未完成任务。"""
    payload = {
        "cmd_type": "2",
        "robot_control": "11",
        "path_id": str(path_id),
    }
    return await send_robot(payload)


@mcp.tool()
async def get_latest_patrol_result() -> Dict[str, Any]:
    """查询最新一次巡检结果。"""
    payload = {
        "cmd_type": "3",
        "get_robot_info": "15",
    }
    return await send_robot(payload)


@mcp.tool()
async def get_air_data() -> Dict[str, Any]:
    """查询气体、温湿度传感器数据。"""
    payload = {
        "cmd_type": "1",
        "device_control": "1",
        "device": "1",
    }
    return await send_robot(payload)


@mcp.tool()
async def get_noise_data() -> Dict[str, Any]:
    """查询噪声传感器数据。"""
    payload = {
        "cmd_type": "1",
        "device_control": "1",
        "device": "5",
    }
    return await send_robot(payload)

DEMO_PATH_ID = os.getenv("DEMO_PATH_ID", "7")

DEMO_POINTS = {
    "取物点": os.getenv("POINT_PICKUP", "78"),
    "服务台": os.getenv("POINT_SERVICE", "79"),
    "顾客点": os.getenv("POINT_CUSTOMER", "81"),
    "充电预备": os.getenv("POINT_CHARGE_READY", "82"),
}


@mcp.tool()
async def go_to_named_point(point_name: str) -> Dict[str, Any]:
    """按语义点位名称控制真实巡检机器人快速到达。可用点位：取物点、服务台、顾客点、充电预备。"""
    if point_name not in DEMO_POINTS:
        return {
            "status": "error",
            "error": f"unknown point_name: {point_name}",
            "available_points": list(DEMO_POINTS.keys()),
        }

    return await quick_arrival(
        path_id=DEMO_PATH_ID,
        path_position_id=DEMO_POINTS[point_name],
    )


@mcp.tool()
async def delivery_demo(task: str) -> Dict[str, Any]:
    """
    执行实机配送演示：让小车拿苹果去服务台装盘后去顾客那上交。
    当前机器人没有机械臂，因此不执行真实抓取、放置、递交。
    实际流程：前往取物点，等待人工放置苹果；前往服务台，等待人工装盘；前往顾客点，完成交付；最后返回充电点。
    """
    steps = []

    steps.append({"step": 1, "action": "前往取物点", "target": "点位1"})
    steps.append(await go_to_named_point("取物点"))
    steps.append({"note": "已到达取物点，等待人工放置苹果"})

    steps.append({"step": 2, "action": "前往服务台", "target": "点位2"})
    steps.append(await go_to_named_point("服务台"))
    steps.append({"note": "已到达服务台，等待人工装盘"})

    steps.append({"step": 3, "action": "前往顾客点", "target": "点位4"})
    steps.append(await go_to_named_point("顾客点"))
    steps.append({"note": "已到达顾客点，完成交付"})

    steps.append({"step": 4, "action": "前往充电预备", "target": "充电预备"})
    steps.append(await go_to_named_point("充电预备"))

    steps.append({"step": 5, "action": "回充"})
    steps.append(await return_charge())

    return {
        "status": "success",
        "task": task,
        "message": "实机配送演示流程已下发",
        "steps": steps,
    }

if __name__ == "__main__":
    print("Starting inspection robot skill server")
    print(f"Robot WebSocket: {ROBOT_WS}")
    print(f"Skill server: http://{SKILL_HOST}:{SKILL_PORT}/mcp")
    mcp.run(transport="streamable-http")
