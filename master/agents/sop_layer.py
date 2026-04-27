
import re
from typing import Optional


class SOPManager:
    def __init__(self):
        self.valid_targets = [
            "kitchenTable",
            "servingTable",
            "customer",
            "user",
            "spawn",
        ]

        # 最小 alias 表：不同叫法 -> 标准目标名
        self.target_aliases = {
            "customer": "customer",
            "顾客": "customer",
            "客人": "customer",
            "customer location": "customer",

            "kitchen table": "kitchenTable",
            "厨房桌": "kitchenTable",
            "kitchentable": "kitchenTable",

            "serving table": "servingTable",
            "服务台": "servingTable",
            "servingtable": "servingTable",

            # 把标准名自己也放进去，方便统一处理
            "kitchenTable": "kitchenTable",
            "servingTable": "servingTable",
            "user": "user",
            "spawn": "spawn",
        }

    # ---------------------------
    # 对外主入口
    # ---------------------------
    def try_handle(self, task, scene_info, robot_name_list, robot_tools_info):
        sop_type = self.route_task(task)

        if sop_type == "state_query":
            return self.build_state_query(task, robot_name_list)

        if sop_type == "nav_single":
            return self.build_nav_single(task, scene_info, robot_name_list)

        if sop_type == "nav_multi":
            return self.build_nav_multi(task, scene_info, robot_name_list)

        return None

    def post_process(self, plan, scene_info, robot_name_list, robot_tools_info):
        return self.validate_plan(plan, scene_info, robot_name_list, robot_tools_info)

    # ---------------------------
    # 1) 路由：判断任务类型
    # ---------------------------
    def route_task(self, task) -> str:
        text = str(task).strip().lower()

        # 状态查询
        if ("状态" in str(task)) or ("现在在哪" in str(task)) or ("当前位置" in str(task)) or ("robot state" in text):
            return "state_query"

        # 多点导航
        if ("依次" in str(task)) or ("然后" in str(task)) or ("最后返回" in str(task)) or ("先" in str(task) and "再" in str(task)):
            return "nav_multi"

        # 单点导航
        if ("去" in str(task)) or ("前往" in str(task)) or ("导航到" in str(task)):
            return "nav_single"

        return "fallback"

    # ---------------------------
    # 2) 目标归一化
    # ---------------------------
    def normalize_target(self, text, scene_info) -> Optional[str]:
        raw_text = str(text).strip()
        normalized_text = self._normalize_text(raw_text)

        # 2.1 先查 alias
        for alias, canonical in self.target_aliases.items():
            if self._normalize_text(alias) in normalized_text:
                return canonical

        # 2.2 再查标准目标名本身
        for target in self.valid_targets:
            if self._normalize_text(target) in normalized_text:
                return target

        # 2.3 最简单的 scene_info 规则：例如“放有苹果的地方”
        scene_str = str(scene_info)

        if ("苹果" in raw_text) or ("apple" in raw_text.lower()):
            # 很简单的规则版：scene_info 里只要提到 apple 在 kitchenTable
            if ("apple" in scene_str and "kitchenTable" in scene_str) or ("苹果" in scene_str and "kitchenTable" in scene_str):
                return "kitchenTable"

        return None

    # ---------------------------
    # 3) 单点导航 SOP
    # ---------------------------
    def build_nav_single(self, task, scene_info, robot_name_list):
        robot_name = self._pick_robot(robot_name_list)
        if robot_name is None:
            return None

        target = self.normalize_target(task, scene_info)
        if target is None:
            return None

        return {
            "reasoning_explanation": f"SOP single-target navigation to {target}.",
            "subtask_list": [
                {
                    "robot_name": robot_name,
                    "subtask": f'navigate_to_target(target="{target}")',
                    "subtask_order": 1,
                }
            ],
        }

    # ---------------------------
    # 4) 多点导航 SOP
    # ---------------------------
    def build_nav_multi(self, task, scene_info, robot_name_list):
        robot_name = self._pick_robot(robot_name_list)
        if robot_name is None:
            return None

        task_text = str(task)
        matches = []

        # 把所有 alias 和标准目标都找出来，按在文本里出现的位置排序
        candidates = []

        for alias, canonical in self.target_aliases.items():
            candidates.append((alias, canonical))

        for target in self.valid_targets:
            candidates.append((target, target))

        for alias, canonical in candidates:
            pattern = re.escape(alias)
            for m in re.finditer(pattern, task_text, flags=re.IGNORECASE):
                matches.append((m.start(), canonical))

        if not matches:
            return None

        matches.sort(key=lambda x: x[0])
        ordered_targets = [x[1] for x in matches]

        # 去掉相邻重复，例如同一个词被 alias 和标准名重复匹配
        dedup_targets = []
        for t in ordered_targets:
            if not dedup_targets or dedup_targets[-1] != t:
                dedup_targets.append(t)

        subtasks = []
        for idx, target in enumerate(dedup_targets, start=1):
            subtasks.append(
                {
                    "robot_name": robot_name,
                    "subtask": f'navigate_to_target(target="{target}")',
                    "subtask_order": idx,
                }
            )

        return {
            "reasoning_explanation": f"SOP multi-target navigation: {' -> '.join(dedup_targets)}.",
            "subtask_list": subtasks,
        }

    # ---------------------------
    # 5) 状态查询 SOP
    # ---------------------------
    def build_state_query(self, task, robot_name_list):
        robot_name = self._pick_robot(robot_name_list)
        if robot_name is None:
            return None

        return {
            "reasoning_explanation": "SOP state query.",
            "subtask_list": [
                {
                    "robot_name": robot_name,
                    "subtask": "get_robot_state()",
                    "subtask_order": 1,
                }
            ],
        }

    # ---------------------------
    # 6) planner 输出验证和修正
    # ---------------------------
    def validate_plan(self, plan, scene_info, robot_name_list, robot_tools_info):
        if not isinstance(plan, dict):
            return plan

        if "subtask_list" not in plan or not isinstance(plan["subtask_list"], list):
            return plan

        valid_robot_names = set(robot_name_list if isinstance(robot_name_list, list) else [])
        valid_skill_names = self._extract_skill_names(robot_tools_info)

        fixed_subtasks = []

        for item in plan["subtask_list"]:
            if not isinstance(item, dict):
                continue

            robot_name = item.get("robot_name")
            subtask = item.get("subtask")
            subtask_order = item.get("subtask_order", 1)

            # 6.1 robot_name 检查
            if robot_name not in valid_robot_names:
                robot_name = self._pick_robot(robot_name_list)

            # 6.2 subtask 必须是字符串
            if not isinstance(subtask, str):
                continue

            # 6.3 提取 skill 名
            skill_name = self._extract_skill_name_from_call(subtask)
            if skill_name is None:
                continue

            # skill 不合法就丢掉
            if valid_skill_names and skill_name not in valid_skill_names:
                continue

            # 6.4 如果是导航任务，修正 target
            if skill_name == "navigate_to_target":
                target_value = self._extract_target_value(subtask)
                if target_value is None:
                    continue

                normalized_target = self.normalize_target(target_value, scene_info)
                if normalized_target is None:
                    continue

                subtask = f'navigate_to_target(target="{normalized_target}")'

            fixed_subtasks.append(
                {
                    "robot_name": robot_name,
                    "subtask": subtask,
                    "subtask_order": subtask_order,
                }
            )

        if not fixed_subtasks:
            return plan

        plan["subtask_list"] = fixed_subtasks
        return plan

    # ---------------------------
    # 工具函数
    # ---------------------------
    def _pick_robot(self, robot_name_list):
        if isinstance(robot_name_list, list) and len(robot_name_list) > 0:
            return robot_name_list[0]
        return None

    def _normalize_text(self, s: str) -> str:
        return "".join(ch.lower() for ch in str(s) if ch.isalnum())

    def _extract_skill_name_from_call(self, subtask: str) -> Optional[str]:
        m = re.match(r"\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", subtask)
        if m:
            return m.group(1)
        return None

    def _extract_target_value(self, subtask: str) -> Optional[str]:
        # 匹配 target="xxx" 或 target='xxx'
        m = re.search(r'target\s*=\s*"([^"]+)"', subtask)
        if m:
            return m.group(1)

        m = re.search(r"target\s*=\s*'([^']+)'", subtask)
        if m:
            return m.group(1)

        return None

    def _extract_skill_names(self, robot_tools_info):
        # 兼容字符串形式，只做最简单提取
        if isinstance(robot_tools_info, str):
            names = set(re.findall(r'"name"\s*:\s*"([^"]+)"', robot_tools_info))
            return names

        # 如果本来就是 list/dict，可以按你项目实际结构再改
        return set()