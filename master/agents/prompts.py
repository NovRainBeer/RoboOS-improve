MASTER_PLANNING_PLANNING = """
Please only use {robot_name_list} with skills {robot_tools_info}.
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

## Note:
If tasks are parallel, they can share the same subtask_order.
If tasks are sequential, use increasing subtask_order.

# The task to be completed is: {task}. Your output answer:
"""