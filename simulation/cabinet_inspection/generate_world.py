#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import yaml


def _first_scene(data: dict[str, Any]) -> dict[str, Any]:
    scenes = data.get("scene")
    if isinstance(scenes, list) and scenes:
        return scenes[0]
    if isinstance(scenes, dict):
        return scenes
    raise ValueError("YAML must contain a non-empty 'scene' section")


def _cabinet_specs(scene: dict[str, Any]) -> list[dict[str, Any]]:
    cabinets = scene.get("cabinets")
    if isinstance(cabinets, list) and cabinets:
        return cabinets

    layout = scene.get("layout", {})
    count = int(layout.get("cabinets_per_row", 6))
    first_x = float(layout.get("first_cabinet_center_x", layout.get("first_cabinet_x", 0.5)))
    spacing = float(layout.get("spacing", 2.0))
    row_a_y = float(layout.get("row_a_center_y", 2.0))
    row_b_y = float(layout.get("row_b_center_y", -2.0))
    size = layout.get("cabinet_size", {"x": 0.5, "y": 0.5, "z": 1.8})

    result: list[dict[str, Any]] = []
    for i in range(count):
        x = first_x + i * spacing
        result.append({
            "name": f"A{i + 1}",
            "center": {"x": x, "y": row_a_y},
            "size": size,
            "front_normal": {"x": 0.0, "y": 1.0},
        })
        result.append({
            "name": f"B{i + 1}",
            "center": {"x": x, "y": row_b_y},
            "size": size,
            "front_normal": {"x": 0.0, "y": -1.0},
        })
    return result


def _add_box_model(world: ET.Element, name: str, x: float, y: float, sx: float, sy: float, sz: float) -> None:
    model = ET.SubElement(world, "model", {"name": name})
    ET.SubElement(model, "static").text = "true"
    ET.SubElement(model, "pose").text = f"{x:.4f} {y:.4f} {sz / 2.0:.4f} 0 0 0"

    link = ET.SubElement(model, "link", {"name": "body"})

    collision = ET.SubElement(link, "collision", {"name": "collision"})
    geometry = ET.SubElement(collision, "geometry")
    box = ET.SubElement(geometry, "box")
    ET.SubElement(box, "size").text = f"{sx:.4f} {sy:.4f} {sz:.4f}"

    visual = ET.SubElement(link, "visual", {"name": "visual"})
    geometry = ET.SubElement(visual, "geometry")
    box = ET.SubElement(geometry, "box")
    ET.SubElement(box, "size").text = f"{sx:.4f} {sy:.4f} {sz:.4f}"
    material = ET.SubElement(visual, "material")
    script = ET.SubElement(material, "script")
    ET.SubElement(script, "uri").text = "file://media/materials/scripts/gazebo.material"
    ET.SubElement(script, "name").text = "Gazebo/Grey"


def _add_visual_disc(world: ET.Element, name: str, x: float, y: float) -> None:
    model = ET.SubElement(world, "model", {"name": name})
    ET.SubElement(model, "static").text = "true"
    ET.SubElement(model, "pose").text = f"{x:.4f} {y:.4f} 0.01 0 0 0"
    link = ET.SubElement(model, "link", {"name": "marker"})
    visual = ET.SubElement(link, "visual", {"name": "visual"})
    geometry = ET.SubElement(visual, "geometry")
    cylinder = ET.SubElement(geometry, "cylinder")
    ET.SubElement(cylinder, "radius").text = "0.08"
    ET.SubElement(cylinder, "length").text = "0.02"
    material = ET.SubElement(visual, "material")
    script = ET.SubElement(material, "script")
    ET.SubElement(script, "uri").text = "file://media/materials/scripts/gazebo.material"
    ET.SubElement(script, "name").text = "Gazebo/Red"


def build_world(scene_file: Path, output_file: Path, add_markers: bool) -> None:
    with scene_file.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    scene = _first_scene(data)
    cabinets = _cabinet_specs(scene)

    sdf = ET.Element("sdf", {"version": "1.6"})
    world = ET.SubElement(sdf, "world", {"name": "cabinet_inspection"})

    ET.SubElement(world, "include").append(ET.Element("uri"))
    world[-1][0].text = "model://sun"
    ET.SubElement(world, "include").append(ET.Element("uri"))
    world[-1][0].text = "model://ground_plane"

    physics = ET.SubElement(world, "physics", {"name": "default_physics", "type": "ode"})
    ET.SubElement(physics, "max_step_size").text = "0.001"
    ET.SubElement(physics, "real_time_update_rate").text = "1000"

    gui = ET.SubElement(world, "gui", {"fullscreen": "0"})
    camera = ET.SubElement(gui, "camera", {"name": "user_camera"})
    ET.SubElement(camera, "pose").text = "5.0 -12.0 12.0 0 0.65 1.57"

    inspection = scene.get("inspection_constraints", {})
    distance = float(
        inspection.get(
            "cabinet_front_to_base_link",
            scene.get("layout", {}).get("inspection_distance", 0.5),
        )
    )

    for cabinet in cabinets:
        center = cabinet["center"]
        size = cabinet.get("size", {"x": 0.5, "y": 0.5, "z": 1.8})
        x = float(center["x"])
        y = float(center["y"])
        sx = float(size["x"])
        sy = float(size["y"])
        sz = float(size["z"])
        _add_box_model(world, str(cabinet["name"]), x, y, sx, sy, sz)

        if add_markers:
            normal = cabinet.get("front_normal", {"x": 0.0, "y": 1.0})
            nx = float(normal["x"])
            ny = float(normal["y"])
            marker_x = x + nx * (sx / 2.0 + distance)
            marker_y = y + ny * (sy / 2.0 + distance)
            _add_visual_disc(world, f"marker_{cabinet['name']}", marker_x, marker_y)

    tree = ET.ElementTree(sdf)
    ET.indent(tree, space="  ")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    print(f"Generated: {output_file}")
    print(f"Cabinets: {len(cabinets)}")
    print(f"Inspection markers: {'enabled' if add_markers else 'disabled'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Gazebo cabinet inspection world from scene YAML")
    parser.add_argument("--scene", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--add-markers", action="store_true")
    args = parser.parse_args()
    build_world(args.scene.expanduser().resolve(), args.output.expanduser().resolve(), args.add_markers)


if __name__ == "__main__":
    main()
