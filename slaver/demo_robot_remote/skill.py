from mcp.server.fastmcp import FastMCP
import os
import json
import asyncio
import websockets
import yaml


MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

mcp = FastMCP(
    name="robots",
    stateless_http=True,
    host="0.0.0.0",
    port=MCP_PORT
)

CONFIG_PATH = os.getenv("ROBOT_TARGET_CONFIG", "./robot_targets.yaml")


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG = load_config(CONFIG_PATH)

ROBOT_NAME = CONFIG.get("robot_name", "unknown_robot")
ROBOT_API_BASE = CONFIG.get("robot_api_base", "ws://127.0.0.1:5000")
TARGET_MAP = CONFIG.get("targets", {})


def normalize_ws_url(url: str) -> str:
    """
    Normalize robot API base url to websocket url.

    Valid examples:
    - ws://172.24.2.250:5000
    - http://172.24.2.250:5000
    - ws://172.24.2.250:5000/robot_control

    Final output:
    - ws://172.24.2.250:5000
    """

    url = url.strip()

    if url.startswith("http://"):
        url = "ws://" + url[len("http://"):]
    elif url.startswith("https://"):
        url = "wss://" + url[len("https://"):]

    if url.endswith("/robot_control"):
        url = url[: -len("/robot_control")]

    return url.rstrip("/")


def parse_robot_response(raw: str):
    """
    Robot websocket response may be:
    - JSON object string
    - JSON string containing another JSON string
    - plain text
    """

    try:
        parsed = json.loads(raw)

        if isinstance(parsed, str):
            try:
                return json.loads(parsed)
            except Exception:
                return parsed

        return parsed

    except Exception:
        return raw


async def call_robot_api(command: str, payload: dict) -> dict:
    """
    Call real robot websocket API.

    Robot API protocol from robot_api_server.py:

    quick_arrival:
    {"robot_id":"1","cmd_type":"2","robot_control":"10","path_id":"3","path_position_id":"8"}

    stop_current_task:
    {"robot_id":"1","cmd_type":"2","robot_control":"4"}

    search_path_info:
    {"robot_id":"1","cmd_type":"3","get_robot_info":"1"}

    search_path_position_info:
    {"robot_id":"1","cmd_type":"3","get_robot_info":"2","path_id":"2"}
    """

    url = normalize_ws_url(ROBOT_API_BASE)

    request = {
        "robot_id": "1"
    }

    if command == "quick_arrival":
        request.update({
            "cmd_type": "2",
            "robot_control": "10",
            "path_id": str(payload["path_id"]),
            "path_position_id": str(payload["path_position_id"])
        })

    elif command == "stop_current_task":
        request.update({
            "cmd_type": "2",
            "robot_control": "4"
        })

    elif command == "search_path_info":
        request.update({
            "cmd_type": "3",
            "get_robot_info": "1"
        })

    elif command == "search_path_position_info":
        request.update({
            "cmd_type": "3",
            "get_robot_info": "2",
            "path_id": str(payload["path_id"])
        })

    else:
        raise ValueError(f"Unsupported robot command: {command}")

    async with websockets.connect(url, open_timeout=5) as websocket:
        await websocket.send(json.dumps(request, ensure_ascii=False))
        raw_response = await asyncio.wait_for(websocket.recv(), timeout=30)

    return {
        "success": True,
        "url": url,
        "request": request,
        "raw_response": raw_response,
        "parsed_response": parse_robot_response(raw_response)
    }


@mcp.tool()
async def quick_arrival(path_id: str, path_position_id: str) -> tuple[str, dict]:
    payload = {
        "path_id": str(path_id),
        "path_position_id": str(path_position_id)
    }

    try:
        robot_response = await call_robot_api("quick_arrival", payload)

        result = (
            f"{ROBOT_NAME} quick_arrival command sent successfully. "
            f"path_id={path_id}, path_position_id={path_position_id}"
        )
        print(result)

        return result, {
            "success": True,
            "robot_name": ROBOT_NAME,
            "command": "quick_arrival",
            "path_id": path_id,
            "path_position_id": path_position_id,
            "robot_response": robot_response
        }

    except Exception as e:
        error_msg = (
            f"{ROBOT_NAME} quick_arrival failed. "
            f"path_id={path_id}, path_position_id={path_position_id}, error={str(e)}"
        )
        print(error_msg)

        return error_msg, {
            "success": False,
            "robot_name": ROBOT_NAME,
            "command": "quick_arrival",
            "path_id": path_id,
            "path_position_id": path_position_id,
            "error": str(e)
        }


@mcp.tool()
async def navigate_to_target(target: str) -> tuple[str, dict]:
    if target not in TARGET_MAP:
        error_msg = (
            f"{ROBOT_NAME} unknown target: {target}. "
            f"Available targets: {list(TARGET_MAP.keys())}"
        )
        print(error_msg)

        return error_msg, {
            "success": False,
            "robot_name": ROBOT_NAME,
            "target": target,
            "available_targets": list(TARGET_MAP.keys())
        }

    path_info = TARGET_MAP[target]

    result, data = await quick_arrival(
        path_id=path_info["path_id"],
        path_position_id=path_info["path_position_id"]
    )

    data["target"] = target
    return result, data


@mcp.tool()
async def stop_current_task() -> tuple[str, dict]:
    try:
        robot_response = await call_robot_api("stop_current_task", {})

        result = f"{ROBOT_NAME} stop_current_task command sent successfully."
        print(result)

        return result, {
            "success": True,
            "robot_name": ROBOT_NAME,
            "command": "stop_current_task",
            "robot_response": robot_response
        }

    except Exception as e:
        error_msg = f"{ROBOT_NAME} stop_current_task failed: {str(e)}"
        print(error_msg)

        return error_msg, {
            "success": False,
            "robot_name": ROBOT_NAME,
            "command": "stop_current_task",
            "error": str(e)
        }


@mcp.tool()
async def list_targets() -> tuple[str, dict]:
    result = f"{ROBOT_NAME} available targets: {list(TARGET_MAP.keys())}"
    print(result)

    return result, {
        "success": True,
        "robot_name": ROBOT_NAME,
        "targets": TARGET_MAP
    }


@mcp.tool()
async def search_path_info() -> tuple[str, dict]:
    """
    Query all saved paths from robot system.
    Use this tool when the user wants to know path_id, path name, or available robot paths.
    """

    try:
        robot_response = await call_robot_api("search_path_info", {})

        result = f"{ROBOT_NAME} search_path_info command sent successfully."
        print(result)

        return result, {
            "success": True,
            "robot_name": ROBOT_NAME,
            "command": "search_path_info",
            "robot_response": robot_response
        }

    except Exception as e:
        error_msg = f"{ROBOT_NAME} search_path_info failed: {str(e)}"
        print(error_msg)

        return error_msg, {
            "success": False,
            "robot_name": ROBOT_NAME,
            "command": "search_path_info",
            "error": str(e)
        }


@mcp.tool()
async def search_path_position_info(path_id: str) -> tuple[str, dict]:
    """
    Query all positions in a saved path from robot system.
    Use this tool when the user wants to know path_position_id, point name, or point coordinates in a path.

    Args:
        path_id: Existing path id in robot system.
    """

    payload = {
        "path_id": str(path_id)
    }

    try:
        robot_response = await call_robot_api("search_path_position_info", payload)

        result = (
            f"{ROBOT_NAME} search_path_position_info command sent successfully. "
            f"path_id={path_id}"
        )
        print(result)

        return result, {
            "success": True,
            "robot_name": ROBOT_NAME,
            "command": "search_path_position_info",
            "path_id": path_id,
            "robot_response": robot_response
        }

    except Exception as e:
        error_msg = (
            f"{ROBOT_NAME} search_path_position_info failed. "
            f"path_id={path_id}, error={str(e)}"
        )
        print(error_msg)

        return error_msg, {
            "success": False,
            "robot_name": ROBOT_NAME,
            "command": "search_path_position_info",
            "path_id": path_id,
            "error": str(e)
        }


if __name__ == "__main__":
    print(f"Starting MCP skill server for {ROBOT_NAME}")
    print(f"Config path: {CONFIG_PATH}")
    print(f"Robot API base: {ROBOT_API_BASE}")
    print(f"Available targets: {list(TARGET_MAP.keys())}")
    mcp.run(transport="streamable-http")