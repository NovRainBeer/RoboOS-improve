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

## Structured tool calls (tool_name + tool_arguments)

For tasks that require complex structured arguments (e.g., cabinet inspection plans with
many waypoints), you SHOULD use the optional tool_name and tool_arguments fields.
This bypasses the Slaver LLM and passes structured data directly to MCP, preventing
coordinate corruption.

When using a structured tool call, each subtask entry must contain:
- robot_name
- subtask: a short human-readable description (still required, but not used for execution)
- tool_name: the exact MCP tool name to call directly
- tool_arguments: a JSON object with ALL parameters the tool expects
- subtask_order

The tool_arguments MUST be a JSON object (dict), NOT a string. All nested fields
must maintain their proper types (numbers as numbers, lists as lists, etc.).

When NOT using a structured tool call (simple tasks), omit tool_name and tool_arguments.
The subtask string will be interpreted by the Slaver LLM as usual.

Special rules for autonomous cabinet inspection planning:

15. For a cabinet inspection task, output exactly ONE structured
    execute_cabinet_inspection call.

16. Do NOT call run_cabinet_inspection.
    Do NOT split planning and execution into separate subtasks.

17. Independently determine a reasonable cabinet inspection route from
    the current scene_info. Do not assume a fixed snake direction,
    fixed starting cabinet, or fixed bypass side. Decide for yourself:
    - which row to visit first
    - left-to-right or right-to-left within each row
    - which end (left or right) to use for row transition
    - whether transit waypoints are needed

18. The model must compute a complete high-level inspection plan containing:
    - cabinet visit_order
    - every cabinet inspection x, y, yaw
    - necessary transit waypoints
    - one spawn waypoint at the start and one at the end
    - total_distance_m

19. Compute each cabinet inspection pose using the vector formula below.
    Do NOT manually choose plus or minus based on row letter:

    For every cabinet, with cx, cy = center, nx, ny = front_normal (normalized):
      half_proj = abs(nx) * sx/2 + abs(ny) * sy/2
      offset    = half_proj + dist
      inspection_x  = cx + nx * offset
      inspection_y  = cy + ny * offset
      inspection_yaw = atan2(-ny, -nx)

    Self-check A — sign verification:
      If ny > 0 → inspection_y must be GREATER than cy.
      If ny < 0 → inspection_y must be LESS than cy.
      For row A (ny=+1): inspection_y ≈ cy + 0.85
      For row B (ny=-1): inspection_y ≈ cy - 0.85  (more negative)

    Self-check B — dot product verification:
      dot = (inspection_x - cx)*nx + (inspection_y - cy)*ny
      This dot product must be positive and approximately equal to offset.
      If dot is negative, the point is on the wrong side of the cabinet.

20. For cabinet inspection waypoints, waypoint.name is the cabinet
    identifier (use exact scene name: A1, A2, B1, etc.). waypoint.x,
    waypoint.y, waypoint.yaw are the robot inspection pose coordinates.

    name="A1" → the identifier for cabinet A1
    x, y, yaw → where Nav2 actually drives the robot

    Do NOT invent name suffixes. "A1_front" is wrong; use "A1".

21. Cabinet center coordinates are obstacle locations and must not
    appear as waypoint coordinates.

    Correct:  {{"name": "A1", "x": 0.5, "y": 2.85, "yaw": -1.571}}
    Correct:  {{"name": "B1", "x": 0.5, "y": -2.85, "yaw": 1.571}}
    Wrong:    {{"name": "A1", "x": 0.5, "y": 2.0,  "yaw": 0.0}}
    Wrong:    {{"name": "B6", "x": 10.5, "y": -1.85, "yaw": 1.571}}

22. Row-transition transit rule — CRITICAL.
    A row-A cabinet and a row-B cabinet must NOT be consecutive in
    waypoints. Whenever the cabinet row changes, one or more T_* transit
    waypoints MUST appear between the two cabinet waypoints.

    At least one transit point must be outside the cabinet array on the
    left or right side with clearance:
      right_boundary = max cabinet center x + sx/2 = 10.75
      safe_transit_x >= right_boundary + robot_radius + safety_margin
      safe_transit_x >= 10.95  (e.g. x = 11.0)

    Example correct A6→B6 transition:
      {{"name": "A6",  "x": 10.5, "y": 2.85,  "yaw": -1.571}},
      {{"name": "T_1", "x": 11.0, "y": 2.85,  "yaw": 0.0}},
      {{"name": "T_2", "x": 11.0, "y": -2.85, "yaw": 0.0}},
      {{"name": "B6",  "x": 10.5, "y": -2.85, "yaw": 1.571}}

    Without these transit points the route goes through the forbidden
    middle corridor and the plan will be rejected.

23. visit_order contains only cabinet names and must match the cabinet
    subsequence in waypoints. It must not contain spawn or transit names.

24. Transit waypoints use names like T_1, T_2, etc. Their exact names
    and coordinates are chosen by the model, but they must actually
    appear in the waypoints list — reasoning about them is not enough.

25. The plan must visit every cabinet exactly once, start and end at
    spawn, and be continuous and executable.

26. Nav2 is responsible for the detailed collision-free path between
    consecutive high-level waypoints. The model generates the high-level
    topology; Nav2 handles local obstacle avoidance.

27. total_distance_m — COMPUTE AFTER EVERYTHING ELSE.
    Generate the complete waypoint list first.
    Then recompute total_distance_m from that final list by summing the
    Euclidean distance between every consecutive pair of waypoints.
    Do NOT estimate. Do NOT reuse a distance calculated before transit
    points or coordinate corrections were added.
    Use strict=false for execute_cabinet_inspection. A mismatch between
    reported total_distance_m and the waypoint polyline distance produces
    a warning but does not prevent execution.

28. Select the cabinet visit order and bypass side according to spatial
    continuity, route length, number of turns, and executability.

29. Before outputting, verify:
    - Every cabinet appears exactly once in waypoints.
    - Cabinet waypoints use exact scene names (no suffixes).
    - No cabinet waypoint coordinate equals its cabinet center.
    - For each cabinet, dot(inspection_pose - center, front_normal) > 0.
    - Row-A and row-B cabinets are separated by T_* transit waypoints.
    - At least one transit point x is outside the cabinet array boundary.
    - First and last waypoints are spawn at the origin from scene_info.
    - total_distance_m equals the sum of consecutive waypoint distances.

30. Do not copy a route, coordinate, distance, or transit waypoint
    from an example.

Please break down the given task into sub-tasks.
Each sub-task should be feasible for a single robot.
Do not make the task too complex, but also do not over-split it into meaningless tiny steps.

Each sub-task should contain:
- robot_name
- subtask
- subtask_order
Optionally (for structured tool calls):
- tool_name
- tool_arguments

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

For structured tool calls, add tool_name and tool_arguments inside the subtask entry:
{{
    "reasoning_explanation": "xxx",
    "subtask_list": [
        {{
            "robot_name": "xxx",
            "subtask": "a short human-readable description",
            "tool_name": "execute_cabinet_inspection",
            "tool_arguments": {{"plan": {{...}}, "strict": false}},
            "subtask_order": 1
        }}
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

This is a cabinet inspection task. Output exactly ONE structured
execute_cabinet_inspection call. Independently determine the route.
Compute every x, y, yaw and total_distance_m from scene_info geometry.
Do not copy coordinates or route structure from this example.

Expected output shape — all values should be independently computed:
{{
    "reasoning_explanation": "Explain your route decision: which row first, direction within each row, which end to bypass, why.",
    "subtask_list": [
        {{
            "robot_name": "demo_robot",
            "subtask": "Autonomous cabinet inspection route",
            "tool_name": "execute_cabinet_inspection",
            "tool_arguments": {{
                "plan": {{
                    "visit_order": ["cabinet names in your chosen order"],
                    "waypoints": [
                        "spawn at scene origin as first waypoint, then your cabinet poses and transit points, then spawn at scene origin as last waypoint"
                    ],
                    "total_distance_m": <your computed polyline distance>
                }},
                "strict": false,
                "dwell_seconds": 2.0,
                "goal_timeout_seconds": 180.0
            }},
            "subtask_order": 1
        }}
    ]
}}

## Note:
If tasks are parallel, they can share the same subtask_order.
If tasks are sequential, use increasing subtask_order.

# The task to be completed is: {task}. Your output answer:
"""
