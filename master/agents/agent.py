import asyncio
import json
import logging
import os
import re
import threading
import uuid
from collections import defaultdict
from typing import Dict
from .sop_layer import SOPManager

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
        self.sop = SOPManager()

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
            subtasks = reasoning_and_subtasks["subtask_list"]
            if not isinstance(subtasks, list) or not subtasks:
                return False

            worker_list = set()
            for subtask in subtasks:
                if not isinstance(subtask, dict):
                    return False

                robot_name = subtask.get("robot_name")
                if not isinstance(robot_name, str) or not robot_name:
                    return False
                worker_list.add(robot_name)

                # Structured direct-tool calls are optional for normal tasks.
                # When tool_name is present, tool_arguments must remain a JSON object.
                tool_name = subtask.get("tool_name")
                if tool_name is not None:
                    if not isinstance(tool_name, str) or not tool_name.strip():
                        return False
                    if not isinstance(subtask.get("tool_arguments"), dict):
                        return False

                if not isinstance(subtask.get("subtask"), str):
                    return False

            robots_list = set(self.collaborator.read_all_agents_name())
            return worker_list.issubset(robots_list)

        except (TypeError, KeyError):
            return False

    def _check_plan_geometry(self, reasoning_and_subtasks: dict) -> str:
        """Basic geometric sanity checks on the model-generated plan.

        Returns an empty string if the plan looks reasonable, or a
        newline-separated list of errors that should be fed back to the LLM.
        """
        errors: list = []
        subtask_list = reasoning_and_subtasks.get("subtask_list", [])
        for subtask in subtask_list:
            tool_args = subtask.get("tool_arguments") or {}
            plan = tool_args.get("plan") or {}
            waypoints = plan.get("waypoints") or []

            if not waypoints:
                continue

            # Check 1: spawn at start and end
            if str(waypoints[0].get("name", "")) != "spawn":
                errors.append("First waypoint must be spawn.")
            if str(waypoints[-1].get("name", "")) != "spawn":
                errors.append("Last waypoint must be spawn.")

            # Check 2: row-transition transit waypoints
            cabinet_wps = [
                (i, wp) for i, wp in enumerate(waypoints)
                if str(wp.get("name", "")) in {"A1","A2","A3","A4","A5","A6",
                                                 "B1","B2","B3","B4","B5","B6"}
            ]
            for idx in range(len(cabinet_wps) - 1):
                i_a, wp_a = cabinet_wps[idx]
                i_b, wp_b = cabinet_wps[idx + 1]
                name_a = str(wp_a["name"])
                name_b = str(wp_b["name"])
                row_a = name_a[0]
                row_b = name_b[0]
                if row_a != row_b:
                    # Row transition detected
                    gap_wps = waypoints[i_a + 1 : i_b]
                    gap_names = [str(w.get("name", "")) for w in gap_wps]
                    if not gap_wps:
                        errors.append(
                            f"No transit waypoints between {name_a} and {name_b}. "
                            f"A T_* transit point outside the cabinet array end is required."
                        )
                    else:
                        has_end_bypass = any(
                            str(w.get("name", "")).upper().startswith("T_")
                            for w in gap_wps
                        )
                        if not has_end_bypass:
                            errors.append(
                                f"Waypoints between {name_a} and {name_b} "
                                f"({gap_names}) do not include a T_* transit point. "
                                f"Add a T_* waypoint outside the cabinet array boundary."
                            )

            # Check 3: B-row y must be less than center y (ny < 0)
            # A-row y must be greater than center y (ny > 0)
            for wp in waypoints:
                name = str(wp.get("name", ""))
                if not name or name.startswith("T_") or name == "spawn":
                    continue
                try:
                    wy = float(wp["y"])
                except (KeyError, ValueError, TypeError):
                    continue
                if name.startswith("A"):
                    if wy <= 2.0:
                        errors.append(
                            f"{name}: y={wy} is not greater than cabinet center y=2.0. "
                            f"Expected y≈2.85 for row A inspection pose."
                        )
                elif name.startswith("B"):
                    if wy >= -2.0:
                        errors.append(
                            f"{name}: y={wy} is not less than cabinet center y=-2.0. "
                            f"Expected y≈-2.85 for row B inspection pose."
                        )

            # Check 4: distance sanity (rough)
            reported = plan.get("total_distance_m")
            if reported is not None:
                try:
                    reported = float(reported)
                    if reported < 20 or reported > 80:
                        errors.append(
                            f"total_distance_m={reported} is outside expected range "
                            f"(20-80 m for a 12-cabinet inspection). Recompute."
                        )
                except (ValueError, TypeError):
                    errors.append("total_distance_m must be a number.")

        return "\n".join(errors) if errors else ""

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

        # --- Geometry quality retry loop ---
        # After structure passes, validate geometry and retry with feedback.
        geo_attempt = 0
        geo_errors = ""
        geo_max = self.config["model"]["model_retry_planning"]
        while geo_attempt < geo_max:
            geo_errors = self._check_plan_geometry(reasoning_and_subtasks)
            if not geo_errors:
                break
            self.logger.warning(
                f"Geometry attempt {geo_attempt + 1} failed with errors:\n{geo_errors}"
            )
            try:
                response = self.planner.forward_with_feedback(task, geo_errors)
            except Exception:
                response = self.planner.forward(
                    f"{task}\n\nPrevious plan rejected with errors:\n{geo_errors}\nPlease fix."
                )
            reasoning_and_subtasks = self._extract_json(response)
            if not self.reasoning_and_subtasks_is_right(reasoning_and_subtasks):
                self.logger.warning("Structure broke during geometry retry; restarting.")
                response = self.planner.forward(task)
                reasoning_and_subtasks = self._extract_json(response)
            geo_attempt += 1

        if geo_errors:
            self.logger.warning(
                f"Geometry retries exhausted ({geo_max}). "
                f"Proceeding with remaining errors:\n{geo_errors}"
            )

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
                    "order_flag": order_flag,
                    "refresh": refresh,
                }

                # Preserve the model-generated structured call exactly.
                # Do not stringify tool_arguments, otherwise the Slaver model may
                # reinterpret or truncate the complete waypoint plan.
                if tasks.get("tool_name") is not None:
                    tool_args = tasks["tool_arguments"]
                    # Defense: recover if the LLM accidentally stringified tool_arguments.
                    if isinstance(tool_args, str):
                        self.logger.warning(
                            f"tool_arguments was a string, attempting JSON parse: "
                            f"{tool_args[:200]}..."
                        )
                        try:
                            tool_args = json.loads(tool_args)
                        except json.JSONDecodeError as exc:
                            self.logger.error(
                                f"tool_arguments is a non-JSON string and cannot be recovered: {exc}"
                            )
                            raise TypeError(
                                "tool_arguments must be a JSON object, not a plain string"
                            ) from exc
                    if not isinstance(tool_args, dict):
                        raise TypeError(
                            f"tool_arguments must be a dict, got {type(tool_args).__name__}"
                        )
                    subtask_data["tool_name"] = tasks["tool_name"]
                    subtask_data["tool_arguments"] = tool_args
                if refresh:
                    self.collaborator.clear_agent_status(robot_name)
                self.collaborator.send(
                    f"roboos_to_{robot_name}", json.dumps(subtask_data)
                )
                working_robots.append(robot_name)
                self.collaborator.update_agent_busy(robot_name, True)
            self.collaborator.wait_agents_free(working_robots)
        self.logger.info(f"Task_id ({task_id}) [{task}] has been sent to all agents.")