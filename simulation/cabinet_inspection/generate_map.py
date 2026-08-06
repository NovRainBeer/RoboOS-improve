#!/usr/bin/env python3
"""Generate a Nav2 occupancy map from a cabinet scene YAML.

The script writes:
  - cabinet_map.pgm  (P2 grayscale occupancy image)
  - cabinet_map.yaml (Nav2 map_server metadata)

It supports both the older compact layout schema and the newer explicit
`cabinets` schema discussed for RoboOS_multi_car.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

FREE = 254
OCCUPIED = 0


def _load_scene(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "scene" not in data:
        raise ValueError("Scene YAML must contain a top-level 'scene' field")

    scene = data["scene"]
    if isinstance(scene, list):
        if not scene:
            raise ValueError("The 'scene' list is empty")
        scene = scene[0]

    if not isinstance(scene, dict):
        raise ValueError("The scene entry must be a mapping")

    return scene


def _float(d: Dict[str, Any], keys: Iterable[str], default: float) -> float:
    for key in keys:
        if key in d and d[key] is not None:
            return float(d[key])
    return float(default)


def _int(d: Dict[str, Any], keys: Iterable[str], default: int) -> int:
    for key in keys:
        if key in d and d[key] is not None:
            return int(d[key])
    return int(default)


def _parse_bounds(scene: Dict[str, Any]) -> Tuple[float, float, float, float]:
    bounds = scene.get("field_bounds") or scene.get("bounds") or {}
    if bounds:
        xmin = _float(bounds, ("xmin", "min_x"), -1.0)
        xmax = _float(bounds, ("xmax", "max_x"), 12.0)
        ymin = _float(bounds, ("ymin", "min_y"), -4.0)
        ymax = _float(bounds, ("ymax", "max_y"), 4.0)
    else:
        xmin, xmax, ymin, ymax = -1.0, 12.0, -4.0, 4.0

    if not (xmax > xmin and ymax > ymin):
        raise ValueError("Invalid field bounds")
    return xmin, xmax, ymin, ymax


def _parse_cabinets(scene: Dict[str, Any]) -> List[Dict[str, float]]:
    cabinets = scene.get("cabinets")
    parsed: List[Dict[str, float]] = []

    if isinstance(cabinets, list) and cabinets:
        for item in cabinets:
            if not isinstance(item, dict):
                continue
            center = item.get("center") or {}
            size = item.get("size") or {}
            parsed.append(
                {
                    "name": str(item.get("name", f"cabinet_{len(parsed)+1}")),
                    "x": float(center["x"]),
                    "y": float(center["y"]),
                    "size_x": _float(size, ("x", "width"), 0.5),
                    "size_y": _float(size, ("y", "depth"), 0.5),
                }
            )
        if parsed:
            return parsed

    layout = scene.get("layout") or {}
    count = _int(layout, ("cabinets_per_row",), 6)
    first_x = _float(
        layout,
        ("first_cabinet_center_x", "first_cabinet_x"),
        0.5,
    )
    spacing = _float(layout, ("spacing",), 2.0)
    row_a_y = _float(layout, ("row_a_center_y", "row1_center_y"), 2.0)
    row_b_y = _float(layout, ("row_b_center_y", "row2_center_y"), -2.0)
    size = layout.get("cabinet_size") or {}
    size_x = _float(size, ("x", "width"), 0.5)
    size_y = _float(size, ("y", "depth"), 0.5)

    for i in range(count):
        x = first_x + i * spacing
        parsed.append(
            {
                "name": f"A{i+1}",
                "x": x,
                "y": row_a_y,
                "size_x": size_x,
                "size_y": size_y,
            }
        )
    for i in range(count):
        x = first_x + i * spacing
        parsed.append(
            {
                "name": f"B{i+1}",
                "x": x,
                "y": row_b_y,
                "size_x": size_x,
                "size_y": size_y,
            }
        )
    return parsed


def _world_to_grid(
    x: float,
    y: float,
    xmin: float,
    ymin: float,
    resolution: float,
    width: int,
    height: int,
) -> Tuple[int, int]:
    col = int(math.floor((x - xmin) / resolution))
    row_from_bottom = int(math.floor((y - ymin) / resolution))
    row = height - 1 - row_from_bottom
    col = max(0, min(width - 1, col))
    row = max(0, min(height - 1, row))
    return row, col


def _fill_rect(
    grid: List[List[int]],
    xmin_world: float,
    xmax_world: float,
    ymin_world: float,
    ymax_world: float,
    map_xmin: float,
    map_ymin: float,
    resolution: float,
    width: int,
    height: int,
    value: int,
) -> None:
    # Expand very slightly to avoid losing thin edges to flooring.
    eps = resolution * 0.25
    r1, c1 = _world_to_grid(
        xmin_world - eps,
        ymax_world + eps,
        map_xmin,
        map_ymin,
        resolution,
        width,
        height,
    )
    r2, c2 = _world_to_grid(
        xmax_world + eps,
        ymin_world - eps,
        map_xmin,
        map_ymin,
        resolution,
        width,
        height,
    )
    r_min, r_max = sorted((r1, r2))
    c_min, c_max = sorted((c1, c2))

    for row in range(r_min, r_max + 1):
        for col in range(c_min, c_max + 1):
            grid[row][col] = value


def _draw_boundary(
    grid: List[List[int]], thickness_px: int, value: int = OCCUPIED
) -> None:
    if thickness_px <= 0:
        return
    height = len(grid)
    width = len(grid[0])
    t = min(thickness_px, width // 2, height // 2)
    for r in range(height):
        for c in range(width):
            if r < t or r >= height - t or c < t or c >= width - t:
                grid[r][c] = value


def _write_pgm(path: Path, grid: List[List[int]]) -> None:
    height = len(grid)
    width = len(grid[0])
    with path.open("w", encoding="ascii") as f:
        f.write("P2\n")
        f.write("# Generated from cabinet_profile.yaml\n")
        f.write(f"{width} {height}\n")
        f.write("255\n")
        for row in grid:
            f.write(" ".join(str(v) for v in row))
            f.write("\n")


def _write_map_yaml(
    path: Path,
    image_name: str,
    resolution: float,
    xmin: float,
    ymin: float,
) -> None:
    payload = {
        "image": image_name,
        "mode": "trinary",
        "resolution": float(resolution),
        "origin": [float(xmin), float(ymin), 0.0],
        "negate": 0,
        "occupied_thresh": 0.65,
        "free_thresh": 0.25,
    }
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--name", default="cabinet_map")
    parser.add_argument("--resolution", type=float, default=0.05)
    parser.add_argument(
        "--obstacle-margin",
        type=float,
        default=0.0,
        help="Optional extra obstacle thickness in meters. Keep 0 for a physical map; use Nav2 inflation for safety.",
    )
    parser.add_argument(
        "--add-boundary",
        action="store_true",
        help="Draw an occupied border around the map. Enable only when the Gazebo world also has physical walls.",
    )
    parser.add_argument("--boundary-thickness", type=float, default=0.10)
    args = parser.parse_args()

    if args.resolution <= 0:
        raise ValueError("resolution must be positive")

    scene = _load_scene(args.scene)
    xmin, xmax, ymin, ymax = _parse_bounds(scene)
    cabinets = _parse_cabinets(scene)

    width = int(math.ceil((xmax - xmin) / args.resolution))
    height = int(math.ceil((ymax - ymin) / args.resolution))
    grid = [[FREE for _ in range(width)] for _ in range(height)]

    margin = max(0.0, float(args.obstacle_margin))
    for cabinet in cabinets:
        half_x = cabinet["size_x"] / 2.0 + margin
        half_y = cabinet["size_y"] / 2.0 + margin
        _fill_rect(
            grid=grid,
            xmin_world=cabinet["x"] - half_x,
            xmax_world=cabinet["x"] + half_x,
            ymin_world=cabinet["y"] - half_y,
            ymax_world=cabinet["y"] + half_y,
            map_xmin=xmin,
            map_ymin=ymin,
            resolution=args.resolution,
            width=width,
            height=height,
            value=OCCUPIED,
        )

    # --- forbidden middle corridor between cabinet rows ---
    route = scene.get("planning_requirements", {}).get("route_constraints") or {}
    forbidden = route.get("forbidden_middle_corridor")
    if isinstance(forbidden, dict) and forbidden.get("xmin") is not None:
        fxmin = float(forbidden["xmin"])
        fxmax = float(forbidden["xmax"])
        fymin = float(forbidden["ymin"])
        fymax = float(forbidden["ymax"])
        _fill_rect(
            grid=grid,
            xmin_world=fxmin,
            xmax_world=fxmax,
            ymin_world=fymin,
            ymax_world=fymax,
            map_xmin=xmin,
            map_ymin=ymin,
            resolution=args.resolution,
            width=width,
            height=height,
            value=OCCUPIED,
        )
        print(f"Forbidden corridor: x=[{fxmin}, {fxmax}], y=[{fymin}, {fymax}]")

    if args.add_boundary:
        thickness_px = max(1, int(math.ceil(args.boundary_thickness / args.resolution)))
        _draw_boundary(grid, thickness_px)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pgm_path = args.output_dir / f"{args.name}.pgm"
    yaml_path = args.output_dir / f"{args.name}.yaml"

    _write_pgm(pgm_path, grid)
    _write_map_yaml(
        yaml_path,
        image_name=pgm_path.name,
        resolution=args.resolution,
        xmin=xmin,
        ymin=ymin,
    )

    print(f"Scene: {args.scene}")
    print(f"Cabinets: {len(cabinets)}")
    print(f"Bounds: x=[{xmin}, {xmax}], y=[{ymin}, {ymax}]")
    print(f"Resolution: {args.resolution} m/pixel")
    print(f"Image size: {width} x {height} pixels")
    print(f"Generated: {pgm_path}")
    print(f"Generated: {yaml_path}")


if __name__ == "__main__":
    main()
