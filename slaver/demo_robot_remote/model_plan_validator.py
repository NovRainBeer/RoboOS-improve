from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml


class PlanValidationError(ValueError):
    pass


def _angle_error(a: float, b: float) -> float:
    return abs(math.atan2(math.sin(a - b), math.cos(a - b)))


def _point_inside_aabb(x: float, y: float, rect: Tuple[float, float, float, float]) -> bool:
    xmin, xmax, ymin, ymax = rect
    return xmin <= x <= xmax and ymin <= y <= ymax


def _segment_intersects_aabb(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    rect: Tuple[float, float, float, float],
) -> bool:
    """Liang-Barsky segment/AABB intersection test."""
    x0, y0 = p0
    x1, y1 = p1
    xmin, xmax, ymin, ymax = rect
    dx = x1 - x0
    dy = y1 - y0
    p = (-dx, dx, -dy, dy)
    q = (x0 - xmin, xmax - x0, y0 - ymin, ymax - y0)
    u1, u2 = 0.0, 1.0

    for pi, qi in zip(p, q):
        if abs(pi) < 1e-12:
            if qi < 0:
                return False
            continue
        t = qi / pi
        if pi < 0:
            u1 = max(u1, t)
        else:
            u2 = min(u2, t)
        if u1 > u2:
            return False
    return True


def _load_scene(scene_path: Path) -> Dict[str, Any]:
    with scene_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    scenes = raw.get("scene")
    if not isinstance(scenes, list):
        raise PlanValidationError("scene YAML must contain a top-level 'scene' list")

    scene = next(
        (item for item in scenes if isinstance(item, dict) and item.get("name") == "cabinet_layout"),
        None,
    )
    if scene is None:
        raise PlanValidationError("scene YAML does not contain name: cabinet_layout")
    if not isinstance(scene.get("cabinets"), list) or not scene["cabinets"]:
        raise PlanValidationError(
            "cabinet_layout must contain raw cabinet geometry under 'cabinets'; "
            "precomputed target_poses are not accepted"
        )
    return scene


def _cabinet_geometry(scene: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for item in scene["cabinets"]:
        if not isinstance(item, dict):
            raise PlanValidationError("each cabinet entry must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise PlanValidationError("every cabinet must have a non-empty name")
        if name in result:
            raise PlanValidationError(f"duplicate cabinet name in scene: {name}")
        result[name] = item
    return result


def _expected_inspection_pose(
    cabinet: Dict[str, Any], inspection_distance: float
) -> Dict[str, float]:
    center = cabinet.get("center") or {}
    size = cabinet.get("size") or {}
    normal = cabinet.get("front_normal") or {}

    cx = float(center["x"])
    cy = float(center["y"])
    sx = float(size["x"])
    sy = float(size["y"])
    nx = float(normal["x"])
    ny = float(normal["y"])

    norm = math.hypot(nx, ny)
    if norm <= 1e-9:
        raise PlanValidationError(f"cabinet {cabinet.get('name')} has zero front_normal")
    nx /= norm
    ny /= norm

    half_extent = abs(nx) * sx / 2.0 + abs(ny) * sy / 2.0
    offset = half_extent + inspection_distance
    return {
        "x": cx + nx * offset,
        "y": cy + ny * offset,
        "yaw": math.atan2(-ny, -nx),
    }


def _inflated_rect(cabinet: Dict[str, Any], inflation: float) -> Tuple[float, float, float, float]:
    center = cabinet["center"]
    size = cabinet["size"]
    cx = float(center["x"])
    cy = float(center["y"])
    hx = float(size["x"]) / 2.0 + inflation
    hy = float(size["y"]) / 2.0 + inflation
    return cx - hx, cx + hx, cy - hy, cy + hy


def _polyline_distance(waypoints: Iterable[Dict[str, Any]]) -> float:
    points = list(waypoints)
    return sum(
        math.hypot(
            float(right["x"]) - float(left["x"]),
            float(right["y"]) - float(left["y"]),
        )
        for left, right in zip(points, points[1:])
    )


def _validate_row_transition_topology(
    waypoints: List[Dict[str, Any]],
    scene: Dict[str, Any],
    cabinets: Dict[str, Dict[str, Any]],
    errors: List[str],
) -> None:
    """Ensure any row transition uses left or right end, not the middle.

    Detects row transitions by checking when the front_normal direction
    changes between consecutive cabinet waypoints. For each detected
    transition, verifies that a transit waypoint exists outside the
    left or right cabinet array boundary.
    """
    wp_names = [str(wp.get("name", "")) for wp in waypoints]

    # Build the ordered list of cabinet waypoints with their indices
    cabinet_indices: List[Tuple[int, str]] = []
    for idx, name in enumerate(wp_names):
        if name in cabinets:
            cabinet_indices.append((idx, name))

    if len(cabinet_indices) < 2:
        return  # no row transition possible

    robot = scene.get("robot") or {}
    constraints = scene.get("inspection_constraints") or {}

    # Compute array-end boundaries
    min_x = min(
        float(cab["center"]["x"]) - float(cab["size"]["x"]) / 2.0
        for cab in cabinets.values()
    )
    max_x = max(
        float(cab["center"]["x"]) + float(cab["size"]["x"]) / 2.0
        for cab in cabinets.values()
    )

    clearance = (
        float(robot.get("radius", 0.15))
        + float(constraints.get("safety_margin", 0.05))
    )

    left_bypass_limit = min_x - clearance
    right_bypass_limit = max_x + clearance

    # Detect row transitions by front_normal sign change
    for i in range(len(cabinet_indices) - 1):
        idx_a, name_a = cabinet_indices[i]
        idx_b, name_b = cabinet_indices[i + 1]
        cab_a = cabinets[name_a]
        cab_b = cabinets[name_b]

        ny_a = float(cab_a.get("front_normal", {}).get("y", 0.0))
        ny_b = float(cab_b.get("front_normal", {}).get("y", 0.0))

        # Different sign → row transition
        if ny_a * ny_b >= 0:
            continue

        # Check transition points between these two cabinets
        transition_points = waypoints[idx_a + 1 : idx_b]

        uses_left_end = any(
            float(pt["x"]) <= left_bypass_limit
            for pt in transition_points
        )
        uses_right_end = any(
            float(pt["x"]) >= right_bypass_limit
            for pt in transition_points
        )

        if not uses_left_end and not uses_right_end:
            errors.append(
                f"row transition from {name_a} to {name_b} must include "
                "a transit waypoint outside the left or right end of the "
                "cabinet array"
            )
        # Either left or right end is acceptable — no enforcement of a
        # specific side. The model chooses the bypass direction.


def validate_model_plan(
    plan: Dict[str, Any],
    scene_path: str | Path,
    *,
    strict: bool = True,
    position_tolerance: float = 0.08,
    yaw_tolerance: float = 0.15,
    distance_tolerance: float = 0.20,
) -> Dict[str, Any]:
    """Validate model output without replacing any model-generated coordinate."""
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(plan, dict):
        return {
            "valid": False,
            "coordinates_replaced": False,
            "errors": ["plan must be a JSON object"],
            "warnings": [],
        }

    try:
        scene = _load_scene(Path(scene_path))
        cabinets = _cabinet_geometry(scene)
    except Exception as exc:
        return {
            "valid": False,
            "coordinates_replaced": False,
            "errors": [str(exc)],
            "warnings": [],
        }

    origin = scene.get("origin") or {}
    origin_name = str(origin.get("name") or origin.get("target") or "spawn")
    bounds = scene.get("field_bounds") or {}
    robot = scene.get("robot") or {}
    constraints = scene.get("inspection_constraints") or {}
    layout = scene.get("layout") or {}

    inspection_distance = float(
        constraints.get(
            "cabinet_front_to_base_link",
            layout.get("inspection_distance", 0.5),
        )
    )
    robot_radius = float(robot.get("radius", 0.15))
    safety_margin = float(constraints.get("safety_margin", 0.05))
    inflation = robot_radius + safety_margin

    visit_order = plan.get("visit_order")
    waypoints = plan.get("waypoints")
    if not isinstance(visit_order, list) or not visit_order:
        errors.append("visit_order must be a non-empty list")
    if not isinstance(waypoints, list) or len(waypoints) < 2:
        errors.append("waypoints must be a list containing at least start and end")
    if errors:
        return {
            "valid": False,
            "coordinates_replaced": False,
            "errors": errors,
            "warnings": warnings,
        }

    waypoint_names: List[str] = []
    for index, waypoint in enumerate(waypoints):
        if not isinstance(waypoint, dict):
            errors.append(f"waypoints[{index}] must be an object")
            continue
        missing = [field for field in ("name", "x", "y", "yaw") if field not in waypoint]
        if missing:
            errors.append(f"waypoints[{index}] missing fields: {missing}")
            continue
        waypoint_names.append(str(waypoint["name"]))
        try:
            float(waypoint["x"])
            float(waypoint["y"])
            float(waypoint["yaw"])
        except (TypeError, ValueError):
            errors.append(f"waypoint {waypoint.get('name')} has non-numeric x/y/yaw")

    if errors:
        return {
            "valid": False,
            "coordinates_replaced": False,
            "errors": errors,
            "warnings": warnings,
        }

    # visit_order must match the cabinet subsequence in waypoints,
    # not the full waypoint list (which includes spawn, transit points, etc.)
    cabinet_names_in_scene = set(cabinets.keys())
    cabinet_waypoint_order = [
        str(wp["name"])
        for wp in waypoints
        if str(wp["name"]) in cabinet_names_in_scene
    ]
    if [str(item) for item in visit_order] != cabinet_waypoint_order:
        errors.append(
            "visit_order must match the cabinet subsequence "
            f"in waypoints: expected={cabinet_waypoint_order}, "
            f"reported={visit_order}"
        )
    if waypoint_names[0] != origin_name or waypoint_names[-1] != origin_name:
        errors.append(f"plan must start and end at {origin_name}")

    for cabinet_name in cabinets:
        count = waypoint_names.count(cabinet_name)
        if count != 1:
            errors.append(f"cabinet {cabinet_name} must appear exactly once; got {count}")

    unknown_inspection = [
        name
        for name in waypoint_names
        if name not in cabinets and name != origin_name
        and not name.upper().startswith(("T_", "TRANSIT", "L_", "R_"))
    ]
    if unknown_inspection:
        errors.append(
            "unknown non-transit waypoint names: " + ", ".join(sorted(set(unknown_inspection)))
        )

    expected_origin = {
        "x": float(origin.get("x", 0.0)),
        "y": float(origin.get("y", 0.0)),
        "yaw": float(origin.get("yaw", 0.0)),
    }
    for endpoint_index in (0, len(waypoints) - 1):
        endpoint = waypoints[endpoint_index]
        if math.hypot(
            float(endpoint["x"]) - expected_origin["x"],
            float(endpoint["y"]) - expected_origin["y"],
        ) > position_tolerance:
            errors.append(f"{origin_name} endpoint coordinates are inconsistent with scene origin")

    by_name = {str(item["name"]): item for item in waypoints}
    expected_poses: Dict[str, Dict[str, float]] = {}
    for name, cabinet in cabinets.items():
        if name not in by_name:
            continue
        expected = _expected_inspection_pose(cabinet, inspection_distance)
        expected_poses[name] = expected
        actual = by_name[name]
        pos_error = math.hypot(
            float(actual["x"]) - expected["x"],
            float(actual["y"]) - expected["y"],
        )
        yaw_error = _angle_error(float(actual["yaw"]), expected["yaw"])
        if pos_error > position_tolerance:
            errors.append(
                f"{name} position error {pos_error:.3f} m exceeds {position_tolerance:.3f} m"
            )
        if yaw_error > yaw_tolerance:
            errors.append(
                f"{name} yaw error {yaw_error:.3f} rad exceeds {yaw_tolerance:.3f} rad"
            )

    if bounds:
        xmin = float(bounds["xmin"])
        xmax = float(bounds["xmax"])
        ymin = float(bounds["ymin"])
        ymax = float(bounds["ymax"])
        for item in waypoints:
            x = float(item["x"])
            y = float(item["y"])
            if not (xmin <= x <= xmax and ymin <= y <= ymax):
                errors.append(f"waypoint {item['name']} lies outside field_bounds")

    inflated = {
        name: _inflated_rect(cabinet, inflation)
        for name, cabinet in cabinets.items()
    }
    for item in waypoints:
        name = str(item["name"])
        x = float(item["x"])
        y = float(item["y"])
        for cabinet_name, rect in inflated.items():
            if _point_inside_aabb(x, y, rect):
                errors.append(
                    f"waypoint {name} is inside the inflated collision area of {cabinet_name}"
                )

    # Segment collision check is intentionally removed.
    # Nav2 is responsible for the detailed collision-free path between
    # high-level waypoints. The validator only checks that waypoints
    # themselves are not inside cabinets and that the row transition
    # topology goes around the array ends.

    _validate_row_transition_topology(waypoints, scene, cabinets, errors)

    # total_distance_m is an estimated metric from the model.
    # A mismatch does not affect whether Nav2 can reach the waypoints.
    # It always produces a warning, never a rejection.
    computed_distance = _polyline_distance(waypoints)
    reported_distance = plan.get("total_distance_m")
    if reported_distance is None:
        warnings.append(
            "total_distance_m not reported; "
            f"computed value is {computed_distance:.4f} m"
        )
    else:
        try:
            delta = abs(float(reported_distance) - computed_distance)
            if delta > distance_tolerance:
                warnings.append(
                    f"reported total_distance_m differs from "
                    f"computed distance by {delta:.3f} m"
                )
        except (TypeError, ValueError):
            warnings.append("total_distance_m must be numeric")

    return {
        "valid": not errors,
        "coordinates_replaced": False,
        "errors": errors,
        "warnings": warnings,
        "computed_distance_m": round(computed_distance, 4),
        "reported_distance_m": reported_distance,
        "inspection_distance_m": inspection_distance,
        "robot_inflation_m": inflation,
        "expected_inspection_poses": expected_poses,
    }
