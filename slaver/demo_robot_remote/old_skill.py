from mcp.server.fastmcp import FastMCP
import subprocess
import math
import yaml
import time
from pathlib import Path

import rclpy
from rclpy.parameter import Parameter
from geometry_msgs.msg import PoseStamped, Quaternion
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult

mcp = FastMCP(
    name="robots",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",
    port=8000,
)

TOPIC_NAME = "/cmd_vel"
ODOM_TOPIC = "/odom"
ROS_SETUP = "source /opt/ros/humble/setup.bash"

# fallback 目标点；如果存在 nav_target_position.yaml，会被文件覆盖
KNOWN_TARGETS = {
    "spawn": {"x": 0.0, "y": 0.0, "yaw": 0.0},
    "kitchenTable": {"x": 3.0, "y": 2.0, "yaw": 0.0},
    "servingTable": {"x": 3.0, "y": -1.0, "yaw": 1.57},
    "customTable": {"x": 0.0, "y": 1.0, "yaw": 1.57},
    "user": {"x": 0.5, "y": -0.5, "yaw": 0.0},
    "home": {"x": 4.0, "y": 1.5, "yaw": 0.0}
}

NAV_TARGET_FILE = Path(__file__).with_name("nav_targets.yaml")


def _load_nav_targets() -> dict:
    if NAV_TARGET_FILE.exists():
        try:
            with open(NAV_TARGET_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict) and data:
                print(f"Loaded navigation targets from {NAV_TARGET_FILE}")
                return data
        except Exception as e:
            print(f"Failed to load {NAV_TARGET_FILE}: {e}")
    print("Using built-in KNOWN_TARGETS")
    return KNOWN_TARGETS.copy()

NAV_TARGETS = _load_nav_targets()

ROBOT_STATUS = {
    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
    "orientation": {"yaw": 0.0},
    "semantic_position": "spawn", #逻辑上确认到达的点
    "semantic_position_estimate": None,
    "holding": None,
    "status": "idle",
    "last_linear_cmd": 0.0,
    "last_angular_cmd": 0.0,
}

_NAVIGATOR = None

def _canonical_target_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _resolve_target_name(target: str) -> str | None:
    canon = _canonical_target_name(target)
    mapping = {_canonical_target_name(k): k for k in NAV_TARGETS.keys()}
    return mapping.get(canon)


def _yaw_to_quaternion(yaw: float) -> Quaternion:
    q = Quaternion()
    q.x = 0.0
    q.y = 0.0
    q.z = math.sin(yaw / 2.0)
    q.w = math.cos(yaw / 2.0)
    return q

def _get_navigator() -> BasicNavigator:
    global _NAVIGATOR
    if _NAVIGATOR is None:
        if not rclpy.ok():
            rclpy.init()
        _NAVIGATOR = BasicNavigator()
        _NAVIGATOR.set_parameters(
            [Parameter("use_sim_time", value=True)]
        )
        _NAVIGATOR.waitUntilNav2Active()
    return _NAVIGATOR

def _run_bash(
    cmd: str,
    check: bool = True,
    silence: bool = False,
    capture: bool = False,
    timeout: float | None = None,
):
    kwargs = {}
    if silence:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    if timeout is not None:
        kwargs["timeout"] = timeout
    return subprocess.run(["bash", "-lc", cmd], check=check, **kwargs)

# 这个辅助函数生成一个ROS命令，用于发布一个全零的Twist消息，确保机器人停止移动。
def _zero_twist_cmd() -> str:
    return f'''
{ROS_SETUP} && \
ros2 topic pub --times 5 -r 20 {TOPIC_NAME} geometry_msgs/msg/Twist \
"{{linear: {{x: 0.0, y: 0.0, z: 0.0}}, angular: {{x: 0.0, y: 0.0, z: 0.0}}}}"
'''

def _read_odom_once() -> dict | None:
    cmd = f'''{ROS_SETUP} && \
ros2 topic echo --once {ODOM_TOPIC}
'''
    try:
        proc = _run_bash(cmd, check=True, capture=True, timeout = 2.5)
        text = (proc.stdout or "").strip()
        if not text:
            return None
        
        docs = list(yaml.safe_load_all(text))
        if not docs:
            return None
        return docs[0]
    except Exception as e:
        print(f"Error reading odom: {e}")
        return None
    
def _quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)

def _canonical_target_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())

def _resolve_target_name(target: str) -> str | None:
    canon = _canonical_target_name(target)
    mapping = {_canonical_target_name(k): k for k in NAV_TARGETS.keys()}
    return mapping.get(canon)

def _nearest_semantic_position(x: float, y: float, radius: float = 0.6) -> str | None:
    best_name = None
    best_dist = None
    for name, pose in NAV_TARGETS.items():
        dx = x - float(pose["x"])
        dy = y - float(pose["y"])
        dist = math.hypot(dx, dy)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_name = name
    if best_dist is not None and best_dist <= radius:
        return best_name
    return None

def _sync_state_from_odom() -> None:
    odom = _read_odom_once()
    if odom is None:
        return

    pose = odom["pose"]["pose"]
    pos = pose["position"]
    ori = pose["orientation"]

    x = float(pos["x"])
    y = float(pos["y"])
    z = float(pos["z"])
    yaw = _quaternion_to_yaw(
        float(ori["x"]),
        float(ori["y"]),
        float(ori["z"]),
        float(ori["w"]),
    )

    ROBOT_STATUS["position"] = {
        "x": round(x, 3),
        "y": round(y, 3),
        "z": round(z, 3),
    }
    ROBOT_STATUS["orientation"] = {
        "yaw": round(yaw, 3),
    }

    ROBOT_STATUS["semantic_position_estimate"] = _nearest_semantic_position(x, y)
    #semantic = _nearest_semantic_position(x, y)
    #if semantic is not None:
    #    ROBOT_STATUS["semantic_position"] = semantic

def _state_reply(message: str):
    return message, {
        "position": ROBOT_STATUS["position"],
        "orientation": ROBOT_STATUS["orientation"],
        "semantic_position": ROBOT_STATUS["semantic_position"],
        "semantic_position_estimate": ROBOT_STATUS.get("semantic_position_estimate"),
        "navigation_goal": ROBOT_STATUS.get("navigation_goal"),
        "holding": ROBOT_STATUS["holding"],
        "status": ROBOT_STATUS["status"],
    }
    
@mcp.tool()
async def get_robot_state() -> tuple[str, dict]:
    """
    Get the current robot state for planning and debugging.
    Returns the current semantic position, holding state, and motion status.
    """
    _sync_state_from_odom()
    msg = (
        f"Robot state: position={ROBOT_STATUS['position']}, "
        f"orientation={ROBOT_STATUS['orientation']}, "
        f"semantic_position={ROBOT_STATUS['semantic_position']}, "
        f"holding={ROBOT_STATUS['holding']}, status={ROBOT_STATUS['status']}"
    )
    print(msg)
    return _state_reply(msg)

@mcp.tool()
async def stop_motion() -> tuple[str, dict]:
    """
    Stop the mobile base immediately by publishing a zero Twist command.
    """
    ROBOT_STATUS["status"] = "stopping"
    try:
        _run_bash(_zero_twist_cmd(), check=True, silence=True)
        ROBOT_STATUS["status"] = "idle"
        ROBOT_STATUS["last_linear_cmd"] = 0.0
        ROBOT_STATUS["last_angular_cmd"] = 0.0
        _sync_state_from_odom()
        msg = "Robot motion stopped successfully."
        print(msg)
        return _state_reply(msg)
    
    except Exception as e:
        ROBOT_STATUS["status"] = "error"
        raise RuntimeError(f"Failed to stop robot motion: {str(e)}") from e

@mcp.tool()
async def rotate_in_place(direction: str, duration: float, angular_speed: float) -> tuple[str, dict]:
    """
    Rotate the mobile base in place for a short duration.
    Args:
        direction: "left" or "right"
        duration: rotation time in seconds
        angular_speed: angular speed in rad/s
    """
    direction = direction.lower().strip()
    if direction not in ["left", "right"]:
        raise ValueError("direction must be 'left' or 'right'")

    duration = max(0.1, min(float(duration), 5.0))
    angular_speed = max(0.1, min(abs(float(angular_speed)), 1.2))
    wz = angular_speed if direction == "left" else -angular_speed
    times = max(1, int(round(duration * 10)))

    rotate_cmd = f'''
{ROS_SETUP} && \
ros2 topic pub --times {times} -r 10 {TOPIC_NAME} geometry_msgs/msg/Twist \
"{{linear: {{x: 0.0, y: 0.0, z: 0.0}}, angular: {{x: 0.0, y: 0.0, z: {wz}}}}}"
'''

    ROBOT_STATUS["status"] = "rotating"
    ROBOT_STATUS["last_linear_cmd"] = 0.0
    ROBOT_STATUS["last_angular_cmd"] = wz

    try:
        _run_bash(rotate_cmd, check=True, silence=True)
        _run_bash(_zero_twist_cmd(), check=True, silence=True)

        ROBOT_STATUS["status"] = "idle"
        ROBOT_STATUS["last_angular_cmd"] = 0.0
        _sync_state_from_odom()

        msg = (
            f"Rotate {direction} success, duration={duration}, "
            f"angular_speed={angular_speed}"
        )
        print(msg)
        return _state_reply(msg)

    except Exception as e:
        ROBOT_STATUS["status"] = "error"
        raise RuntimeError(f"Failed to rotate robot: {e}") from e


@mcp.tool()
async def navigate_to_target(target: str) -> tuple[str, dict]:
    """
    Navigate the robot to a named target.
    """
    if not isinstance(target, str) or not target.strip():
        raise ValueError("target must be a non-empty string")

    resolved = _resolve_target_name(target.strip())
    if resolved is None:
        known = ", ".join(NAV_TARGETS.keys())
        ROBOT_STATUS["status"] = "error"
        raise ValueError(f"Unknown target '{target}'. Available targets: {known}")

    goal_cfg = NAV_TARGETS[resolved]
    goal_x = float(goal_cfg["x"])
    goal_y = float(goal_cfg["y"])
    goal_yaw = float(goal_cfg["yaw"])

    nav = _get_navigator()

    goal_pose = PoseStamped()
    goal_pose.header.frame_id = "map"
    goal_pose.header.stamp = nav.get_clock().now().to_msg()
    goal_pose.pose.position.x = goal_x
    goal_pose.pose.position.y = goal_y
    goal_pose.pose.position.z = 0.0
    goal_pose.pose.orientation = _yaw_to_quaternion(goal_yaw)

    ROBOT_STATUS["status"] = "navigating"
    ROBOT_STATUS["navigation_goal"] = resolved

    try:
        print(f"[NAV2] Sending goal to {resolved}: x={goal_x}, y={goal_y}, yaw={goal_yaw}")
        nav.goToPose(goal_pose)

        while not nav.isTaskComplete():
            _sync_state_from_odom()
            time.sleep(0.2)

        result = nav.getResult()
        _sync_state_from_odom()

        if result == TaskResult.SUCCEEDED:
            ROBOT_STATUS["status"] = "idle"
            ROBOT_STATUS["semantic_position"] = resolved
            ROBOT_STATUS["navigation_goal"] = None
            msg = (
                f"Navigation to {resolved} succeeded. "
                f"Current pose={ROBOT_STATUS['position']}, "
                f"orientation={ROBOT_STATUS['orientation']}"
            )
            print(msg)
            return _state_reply(msg)

        if result == TaskResult.CANCELED:
            ROBOT_STATUS["status"] = "canceled"
            ROBOT_STATUS["navigation_goal"] = None
            raise RuntimeError(f"Navigation to {resolved} was canceled")

        ROBOT_STATUS["status"] = "error"
        ROBOT_STATUS["navigation_goal"] = None
        raise RuntimeError(f"Navigation to {resolved} failed with result={result}")

    except Exception as e:
        if ROBOT_STATUS["status"] not in ("canceled", "error"):
            ROBOT_STATUS["status"] = "error"
        ROBOT_STATUS["navigation_goal"] = None
        raise RuntimeError(f"Failed to navigate to {resolved}: {e}") from e
    
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
