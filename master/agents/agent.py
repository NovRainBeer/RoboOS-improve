import asyncio
import json
import logging
import os
import re
import threading
import uuid
from collections import defaultdict
from typing import Dict

import yaml
from agents.planner import GlobalTaskPlanner
from flag_scale.flagscale.agent.collaboration import Collaborator


class GlobalAgent:
    def __init__(self, config_path="config.yaml"):
        """Initialize GlobalAgent"""
        self._init_config(config_path)
        self._init_logger(self.config["logger"])
        self.collaborator = Collaborator.from_config(self.config["collaborator"])
        self.planner = GlobalTaskPlanner(self.config)

        self.logger.info(f"Configuration loaded from {config_path} ...")
        self.logger.info(f"Master Configuration:\n{self.config}")

        self._init_scene(self.config["profile"])
        self._start_listener()

    def _init_logger(self, logger_config):
        """Initialize an independent logger for GlobalAgent"""
        self.logger = logging.getLogger(logger_config["master_logger_name"])
        logger_file = logger_config["master_logger_file"]
        os.makedirs(os.path.dirname(logger_file), exist_ok=True)
        file_handler = logging.FileHandler(logger_file)

        if logger_config["master_logger_level"] == "DEBUG":
            self.logger.setLevel(logging.DEBUG)
            file_handler.setLevel(logging.DEBUG)
        elif logger_config["master_logger_level"] == "INFO":
            self.logger.setLevel(logging.INFO)
            file_handler.setLevel(logging.INFO)
        elif logger_config["master_logger_level"] == "WARNING":
            self.logger.setLevel(logging.WARNING)
            file_handler.setLevel(logging.WARNING)
        elif logger_config["master_logger_level"] == "ERROR":
            self.logger.setLevel(logging.ERROR)
            file_handler.setLevel(logging.ERROR)

        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def _init_config(self, config_path="config.yaml"):
        """Initialize configuration"""
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

    def _init_scene(self, scene_config):
        """Initialize scene object"""
        path = scene_config["path"]
        if not os.path.exists(path):
            self.logger.error(f"Scene config file {path} does not exist.")
            raise FileNotFoundError(f"Scene config file {path} not found.")
        with open(path, "r", encoding="utf-8") as f:
            self.scene = yaml.safe_load(f)

        scenes = self.scene.get("scene", [])
        for scene_info in scenes:
            scene_name = scene_info.pop("name", None)
            if scene_name:
                self.collaborator.record_environment(scene_name, json.dumps(scene_info))
            else:
                print("Warning: Missing 'name' in scene_info:", scene_info)

    def _handle_register(self, robot_name: Dict) -> None:
        """Listen for robot registrations."""
        robot_info = self.collaborator.read_agent_info(robot_name)
        self.logger.info(
            f"AGENT_REGISTRATION: {robot_name} \n {json.dumps(robot_info)}"
        )

        channel_r2b = f"{robot_name}_to_RoboOS"
        threading.Thread(
            target=lambda: self.collaborator.listen(channel_r2b, self._handle_result),
            daemon=True,
            name=channel_r2b,
        ).start()

        self.logger.info(
            f"RoboOS has listened to [{robot_name}] by channel [{channel_r2b}]"
        )

    def _handle_result(self, data: str):
        data = json.loads(data)

        robot_name = data.get("robot_name")
        subtask_handle = data.get("subtask_handle")
        subtask_result = data.get("subtask_result")

        if robot_name and subtask_handle and subtask_result:
            self.logger.info(
                f"================ Received result from {robot_name} ================"
            )
            self.logger.info(f"Subtask: {subtask_handle}\nResult: {subtask_result}")
            self.logger.info(
                "===================================================================="
            )
            self.collaborator.update_agent_busy(robot_name, False)

        else:
            self.logger.warning("[WARNING] Received incomplete result data")
            self.logger.info(
                f"================ Received result from {robot_name} ================"
            )
            self.logger.info(f"Subtask: {subtask_handle}\nResult: {subtask_result}")
            self.logger.info(
                "===================================================================="
            )

    def _extract_json(self, input_string):
        """Extract JSON from model output. Supports fenced JSON and raw JSON."""
        if not input_string:
            self.logger.warning("[WARNING] Empty model output.")
            return None

        text = input_string.strip()

        # 1) fenced JSON: ```json ... ```
        m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as e:
                self.logger.warning(f"[WARNING] Failed to parse fenced json:\n{e}")

        # 2) generic fenced block: ``` ... ```
        m = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if m:
            candidate = m.group(1).strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as e:
                self.logger.warning(
                    f"[WARNING] Failed to parse generic fenced block:\n{e}"
                )

        # 3) raw JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 4) fallback: extract outermost {...}
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            candidate = m.group(0).strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as e:
                self.logger.warning(
                    f"[WARNING] Failed to parse extracted braces JSON:\n{e}"
                )

        self.logger.warning(
            f"[WARNING] Could not extract valid JSON from model output:\n{text}"
        )
        return None

    def _group_tasks_by_order(self, tasks):
        """Group tasks by topological order."""
        grouped = defaultdict(list)
        for task in tasks:
            grouped[int(task.get("subtask_order", 0))].append(task)
        return dict(sorted(grouped.items()))

    def _start_listener(self):
        """Start listen in a background thread."""
        threading.Thread(
            target=lambda: self.collaborator.listen(
                "AGENT_REGISTRATION", self._handle_register
            ),
            daemon=True,
        ).start()
        self.logger.info("Started listening for robot registrations...")
        
    def _direct_move_plan(self, task):
        if isinstance(task, list):
            task_text = " ".join(str(x) for x in task)
        else:
            task_text = str(task)

        text = task_text.strip()

        direction = None
        if "前进" in text:
            direction = "forward"
        elif "后退" in text:
            direction = "backward"

        if direction is None:
            return None

        duration_match = re.search(r"(\d+(?:\.\d+)?)\s*秒", text)
        duration = float(duration_match.group(1)) if duration_match else 1.0

        speed_match = re.search(r"速度\s*(\d+(?:\.\d+)?)", text)
        if not speed_match:
            speed_match = re.search(r"(\d+(?:\.\d+)?)\s*米每秒", text)
        speed = float(speed_match.group(1)) if speed_match else 0.1

        duration = max(0.1, min(duration, 10.0))
        speed = max(0.02, min(speed, 0.30))

        robots = self.collaborator.read_all_agents_name()
        if not robots:
            self.logger.error("[ERROR] No robot registered for direct move fallback.")
            return None

        robot_name = robots[0]

        return {
            "reasoning_explanation": (
                f"Direct fallback planner used for a simple mobile base movement task: "
                f"{direction}, {duration}s, {speed}m/s."
            ),
            "subtask_list": [
                {
                    "robot_name": robot_name,
                    "subtask": (
                        f"move_linear(direction='{direction}', "
                        f"duration={duration}, speed={speed})"
                    ),
                    "subtask_order": 1,
                }
            ],
        }

    def reasoning_and_subtasks_is_right(self, reasoning_and_subtasks: dict) -> bool:
        """
        Verify if all robots mentioned in the task decomposition exist in the system registry.
        """
        if not isinstance(reasoning_and_subtasks, dict):
            return False

        if "subtask_list" not in reasoning_and_subtasks:
            return False

        try:
            worker_list = {
                subtask["robot_name"]
                for subtask in reasoning_and_subtasks["subtask_list"]
                if isinstance(subtask, dict) and "robot_name" in subtask
            }

            robots_list = set(self.collaborator.read_all_agents_name())
            return worker_list.issubset(robots_list)

        except (TypeError, KeyError):
            return False

    def publish_global_task(self, task: str, refresh: bool, task_id: str) -> Dict:
        self.logger.info(f"Publishing global task: {task}")

        # 先尝试规则直通：简单前进/后退任务不走 LLM
        reasoning_and_subtasks = self._direct_move_plan(task)

        if reasoning_and_subtasks is None:
            response = self.planner.forward(task)
            reasoning_and_subtasks = self._extract_json(response)
        else:
            response = None

        attempt = 0
        while (not self.reasoning_and_subtasks_is_right(reasoning_and_subtasks)) and (
            attempt < self.config["model"]["model_retry_planning"]
        ):
            self.logger.warning(
                f"Attempt {attempt + 1} failed. Retrying task decomposition..."
            )
            if response is not None:
                self.logger.warning(f"Raw planner response:\n{response}")
            response = self.planner.forward(task)
            reasoning_and_subtasks = self._extract_json(response)
            attempt += 1

        if reasoning_and_subtasks is None:
            self.logger.error(
                f"[ERROR] Planner returned invalid JSON.\nRaw response:\n{response}"
            )
            raise ValueError("Planner returned invalid JSON")

        if not self.reasoning_and_subtasks_is_right(reasoning_and_subtasks):
            self.logger.error(
                "[ERROR] Planner returned unusable subtasks.\n"
                f"Parsed response:\n{reasoning_and_subtasks}"
            )
            raise ValueError("Planner returned unusable subtasks")

        self.logger.info(f"Received reasoning and subtasks:\n{reasoning_and_subtasks}")
        subtask_list = reasoning_and_subtasks.get("subtask_list", [])
        grouped_tasks = self._group_tasks_by_order(subtask_list)

        task_id = task_id or str(uuid.uuid4()).replace("-", "")

        threading.Thread(
            target=asyncio.run,
            args=(self._dispath_subtasks_async(task, task_id, grouped_tasks, refresh),),
            daemon=True,
        ).start()

        return reasoning_and_subtasks

    async def _dispath_subtasks_async(
        self, task: str, task_id: str, grouped_tasks: Dict, refresh: bool
    ):
        order_flag = "false" if len(grouped_tasks.keys()) == 1 else "true"
        for task_count, (order, group_task) in enumerate(grouped_tasks.items()):
            self.logger.info(f"Sending task group {order}:\n{group_task}")
            working_robots = []
            for tasks in group_task:
                robot_name = tasks.get("robot_name")
                subtask_data = {
                    "task_id": task_id,
                    "task": tasks["subtask"],
                    "order": order_flag,
                }
                if refresh:
                    self.collaborator.clear_agent_status(robot_name)
                self.collaborator.send(
                    f"roboos_to_{robot_name}", json.dumps(subtask_data)
                )
                working_robots.append(robot_name)
                self.collaborator.update_agent_busy(robot_name, True)
            self.collaborator.wait_agents_free(working_robots)
        self.logger.info(f"Task_id ({task_id}) [{task}] has been sent to all agents.")