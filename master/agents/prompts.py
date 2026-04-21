MASTER_PLANNING_PLANNING = """
Available robot names: {robot_name_list}

Available callable skills:
{robot_tools_info}

You must obey all of the following rules:
1. robot_name must be exactly one name from {robot_name_list}.
2. Do not invent robot names such as robot1, robot, car_controller, or any other name.
3. subtask must be written as a callable skill invocation using only the exact skill names from the available callable skills.
4. Do not invent new skill names.
5. If a task cannot be completed with the available callable skills, return the closest valid decomposition using only the available callable skills.
6. Output robot_name and subtask exactly as executable strings.

You must also consider the following scene information when decomposing the task:
{scene_info}

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

Task: 让小车左转1秒，角速度0.5弧度每秒
Output subtask: rotate_in_place(direction="left", duration=1.0, angular_speed=0.5)

## Note:
If tasks are parallel, they can share the same subtask_order.
If tasks are sequential, use increasing subtask_order.

# The task to be completed is: {task}. Your output answer:
"""