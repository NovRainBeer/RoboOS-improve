from typing import Any, Dict, Union
import json

import yaml
from agents.prompts import MASTER_PLANNING_PLANNING
from flag_scale.flagscale.agent.collaboration import Collaborator
from openai import AzureOpenAI, OpenAI


class GlobalTaskPlanner:
    """A tool planner to plan task into sub-tasks."""

    def __init__(
        self,
        config: Union[Dict, str] = None,
    ) -> None:
        self.collaborator = Collaborator.from_config(config["collaborator"])

        self.global_model: Any
        self.model_name: str
        self.global_model, self.model_name = self._get_model_info_from_config(
            config["model"]
        )

        self.profiling = config["profiling"]

    def _get_model_info_from_config(self, config: Dict) -> tuple:
        """Get the model info from config."""
        candidate = config["model_dict"]
        if candidate["cloud_model"] in config["model_select"]:
            if candidate["cloud_type"] == "azure":
                model_name = config["model_select"]
                model_client = AzureOpenAI(
                    azure_endpoint=candidate["azure_endpoint"],
                    azure_deployment=candidate["azure_deployment"],
                    api_version=candidate["azure_api_version"],
                    api_key=candidate["azure_api_key"],
                )
            elif candidate["cloud_type"] == "default":
                model_client = OpenAI(
                    base_url=candidate["cloud_server"],
                    api_key=candidate["cloud_api_key"],
                )
                model_name = config["model_select"]
            else:
                raise ValueError(f"Unsupported cloud type: {candidate['cloud_type']}")
            return model_client, model_name
        raise ValueError(f"Unsupported model: {config['model_select']}")

    def _init_config(self, config_path="config.yaml"):
        """Initialize configuration"""
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config

    def display_profiling_info(self, description: str, message: any):
        """
        Outputs profiling information if profiling is enabled.

        :param message: The content to be printed. Can be of any type.
        :param description: A brief title or description for the message.
        """
        if self.profiling:
            module_name = "master"
            print(f" [{module_name}] {description}:")
            print(message)

    def forward(self, task: str) -> str:
        """Get the sub-tasks from the task."""

        all_robots_name = self.collaborator.read_all_agents_name()
        all_robots_info = self.collaborator.read_all_agents_info()
        all_environments_info = self.collaborator.read_environment(name=None)

        content = MASTER_PLANNING_PLANNING.format(
            robot_name_list=all_robots_name,
            robot_tools_info=all_robots_info,
            task=task,
            scene_info=all_environments_info,
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": content},
                ],
            },
        ]

        self.display_profiling_info("messages", messages)

        from datetime import datetime

        start_inference = datetime.now()

        try:
            response = self.global_model.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0,
                top_p=1.0,
                max_tokens=2000,
                seed=42,
            )
        except Exception as e:
            print(" [master] planner exception:")
            print(repr(e))
            raise

        end_inference = datetime.now()

        self.display_profiling_info(
            "inference time",
            f"inference start:{start_inference} end:{end_inference} during:{end_inference-start_inference}",
        )
        self.display_profiling_info("response", response)
        self.display_profiling_info("response.usage", response.usage)

        raw_content = response.choices[0].message.content
        self.display_profiling_info("raw planner content", raw_content)

        try:
            parsed = json.loads(raw_content)
        except Exception:
            # 如果模型没按 JSON 返回，先原样返回，方便排查
            return raw_content

        # all_robots_name 一般就是类似 ["demo_robot"]
        if isinstance(all_robots_name, list):
            valid_robot_names = all_robots_name
        else:
            # 防御式处理，避免某些情况下不是 list
            valid_robot_names = [all_robots_name]

        # 单机器人场景：强制对齐 robot_name
        if len(valid_robot_names) == 1:
            only_robot = valid_robot_names[0]
            for item in parsed.get("subtask_list", []):
                item["robot_name"] = only_robot
        else:
            # 多机器人场景：至少做白名单校验
            for item in parsed.get("subtask_list", []):
                if item.get("robot_name") not in valid_robot_names:
                    raise ValueError(
                        f"Invalid robot_name from planner: {item.get('robot_name')}, "
                        f"valid names are: {valid_robot_names}"
                    )

        # Validate structured tool calls: tool_arguments must be a dict, not a string.
        for item in parsed.get("subtask_list", []):
            tool_name = item.get("tool_name")
            if tool_name is not None:
                tool_args = item.get("tool_arguments")
                if isinstance(tool_args, str):
                    try:
                        item["tool_arguments"] = json.loads(tool_args)
                    except json.JSONDecodeError:
                        raise TypeError(
                            f"tool_arguments for '{tool_name}' is a non-JSON string "
                            f"and cannot be recovered: {str(tool_args)[:200]}"
                        )
                if not isinstance(item.get("tool_arguments"), dict):
                    raise TypeError(
                        f"tool_arguments for '{tool_name}' must be a JSON object, "
                        f"got {type(item.get('tool_arguments')).__name__}"
                    )

        self.display_profiling_info("normalized planner content", parsed)
        return json.dumps(parsed, ensure_ascii=False)

    def forward_with_feedback(self, task: str, feedback_errors: str) -> str:
        """Re-plan with validation feedback appended to the prompt."""
        task_with_feedback = (
            f"{task}\n\n"
            f"Your previous plan was rejected by the validator with these errors:\n"
            f"{feedback_errors}\n\n"
            f"Please regenerate the complete plan, fixing every error listed above. "
            f"Verify every rule before outputting."
        )
        return self.forward(task_with_feedback)