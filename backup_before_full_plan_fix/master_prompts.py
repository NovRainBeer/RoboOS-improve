MASTER_PLANNING_PLANNING = """

Available robot names: {robot_name_list}

Available callable skills:
{robot_tools_info}

You must obey all of the following general rules:
1. robot_name must be exactly one name from {robot_name_list}.
2. Do not invent robot names such as robot1, robot, car_controller, or any other name.
3. subtask must be written as a callable skill invocation using only the exact skill names from the available callable skills.
4. Do not invent new skill names.
5. Skill names and parameter names must be exact and executable.
6. If a task cannot be completed with the available callable skills, return the closest valid decomposition using only the available callable skills.
7. Output robot_name and subtask exactly as executable strings.

Semantic normalization rule for parameter values:
8. You may perform LIMITED semantic normalization only for parameter VALUES, especially location/target names.
9. This means you may map a user-provided phrase or a slightly different wording to the closest valid target/entity mentioned in scene_info or implied by available known targets.
10. Examples of allowed normalization:
   - "customer table" -> "customTable"
   - "custom table" -> "customTable"
   - "kitchen table" -> "kitchenTable"
   - "the place with apple" -> the location in scene_info that contains apple
   - "原点" -> "spawn" if spawn exists in scene_info or known targets
   - "一号柜正面巡检点" -> "row1_cabinet_1_front" if this target exists in scene_info
11. Do NOT invent a new target name if a close valid one already exists.
12. If multiple candidate targets exist, choose the most semantically relevant one from scene_info.
13. If no reasonable semantic match exists, then use the closest valid executable decomposition without inventing unsupported targets.
14. Only parameter VALUES may be semantically approximated. Skill names, parameter names, robot names, and JSON structure must remain strict.

You must also consider the following scene information when decomposing the task:
{scene_info}

Special rules for cabinet path planning tasks:
15. If the task is about cabinet inspection path planning, cabinet route generation, two rows of cabinets, or visiting cabinet front inspection points, then generate a path using cabinet targets from scene_info.
16. For cabinet path planning, use navigate_to_target(target="...") for each cabinet front target.
17. Do not output x, y, yaw directly in the subtask. Coordinates are stored in nav_targets.yaml and will be resolved by navigate_to_target.
18. For cabinet path planning, the robot should start from spawn, visit all cabinet front targets exactly once, and finally return to spawn.
19. Do not invent cabinet target names. Valid cabinet targets must come from scene_info, such as row1_cabinet_1_front.
20. Prefer a short continuous route. A good route is snake-like: row1 cabinet 1 to 6, then row2 cabinet 6 to 1, then return to spawn.
21. These cabinet rules apply only to cabinet path planning tasks. For other tasks, follow the general rules and use the available skills normally.

Please break down the given task into sub-tasks.
Each sub-task should be feasible for a single robot.
Do not make the task too complex, but also do not over-split it into meaningless tiny steps.

Each sub-task should contain:
- robot_name
- subtask
- subtask_order

Provide a short reasoning explanation.

Return ONLY raw JSON.
Do not wrap the output in markdown code fences.
Do not output ```json or ```.
Do not add any explanation outside the JSON.

The output format must be:
{{
    "reasoning_explanation": "xxx",
    "subtask_list": [
        {{"robot_name": "xxx", "subtask": "xxx", "subtask_order": 1}}
    ]
}}

## Examples:
Task: 获取当前机器人状态
Output subtask: get_robot_state()

Task: 让小车前进2秒，速度0.1米每秒
Output subtask: move_linear(direction="forward", duration=2.0, speed=0.1)

Task: 让小车后退1秒，速度0.1米每秒
Output subtask: move_linear(direction="backward", duration=1.0, speed=0.1)

Task: 让小车去 custom table
Output subtask: navigate_to_target(target="customTable")

Task: 让小车去 customer table
Output subtask: navigate_to_target(target="customTable")

Task: 让小车去 row1_cabinet_1_front
Output subtask: navigate_to_target(target="row1_cabinet_1_front")

Task: 让小车从原点出发巡检所有柜子正面点位并返回原点
Output subtasks:
navigate_to_target(target="row1_cabinet_1_front")
navigate_to_target(target="row1_cabinet_2_front")
navigate_to_target(target="row1_cabinet_3_front")
navigate_to_target(target="row1_cabinet_4_front")
navigate_to_target(target="row1_cabinet_5_front")
navigate_to_target(target="row1_cabinet_6_front")
navigate_to_target(target="row2_cabinet_6_front")
navigate_to_target(target="row2_cabinet_5_front")
navigate_to_target(target="row2_cabinet_4_front")
navigate_to_target(target="row2_cabinet_3_front")
navigate_to_target(target="row2_cabinet_2_front")
navigate_to_target(target="row2_cabinet_1_front")
navigate_to_target(target="spawn")

## Note:
If tasks are parallel, they can share the same subtask_order.
If tasks are sequential, use increasing subtask_order.

# The task to be completed is: {task}. Your output answer:
"""
