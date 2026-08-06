import math
import yaml
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

CABINET_COUNT = 6
FIRST_X = 0.5
TOTAL_WIDTH = 10.0

# True：保证 6 号柜不超过 10m
# False：严格按 2m 间距，会得到 10.5m
USE_STRICT_WIDTH = True

if USE_STRICT_WIDTH:
    SPACING = (TOTAL_WIDTH - FIRST_X) / (CABINET_COUNT - 1)
else:
    SPACING = 2.0

ROW_INSPECT_Y = {
    1: 1.5,
    2: -1.5,
}

ROW_YAW = {
    1: math.pi / 2,
    2: -math.pi / 2,
}


def cabinet_x(cabinet_id: int) -> float:
    return round(FIRST_X + (cabinet_id - 1) * SPACING, 3)


def build_nav_targets():
    targets = {
        "spawn": {
            "x": 0.0,
            "y": 0.0,
            "yaw": 0.0,
        }
    }

    for row_id in [1, 2]:
        for cabinet_id in range(1, CABINET_COUNT + 1):
            point_name = f"row{row_id}_cabinet_{cabinet_id}_front"
            targets[point_name] = {
                "x": cabinet_x(cabinet_id),
                "y": ROW_INSPECT_Y[row_id],
                "yaw": round(ROW_YAW[row_id], 4),
            }

    return targets


def build_scene_profile(targets):
    row1_targets = [
        f"row1_cabinet_{i}_front"
        for i in range(1, CABINET_COUNT + 1)
    ]

    row2_targets = [
        f"row2_cabinet_{i}_front"
        for i in range(1, CABINET_COUNT + 1)
    ]

    scene = {
        "scene": [
            {
                "name": "cabinet_layout",
                "type": "inspection_scene",
                "origin": {
                    "target": "spawn",
                    "x": 0.0,
                    "y": 0.0,
                    "yaw": 0.0,
                },
                "layout": {
                    "row_count": 2,
                    "cabinets_per_row": CABINET_COUNT,
                    "first_cabinet_x": FIRST_X,
                    "spacing": round(SPACING, 3),
                    "total_width": TOTAL_WIDTH,
                    "strict_width": USE_STRICT_WIDTH,
                    "inspection_distance": 0.5,
                    "description": (
                        "There are two rows of cabinets. "
                        "The robot starts from spawn. "
                        "Each cabinet has one front-center inspection target."
                    ),
                },
                "available_targets": {
                    "row1_front_targets": row1_targets,
                    "row2_front_targets": row2_targets,
                    "return_target": "spawn",
                },
                "target_poses": targets,
                "planning_requirements": [
                    "Start from spawn.",
                    "Visit all cabinet front targets.",
                    "Each cabinet front target should be visited exactly once.",
                    "Finally return to spawn.",
                    "Prefer a short and continuous path.",
                    "Do not invent target names.",
                    "Use navigate_to_target(target='...') only.",
                ],
            }
        ]
    }

    return scene


def main():
    targets = build_nav_targets()
    scene = build_scene_profile(targets)

    nav_path = OUT_DIR / "nav_targets.yaml"
    scene_path = OUT_DIR / "cabinet_profile.yaml"

    with nav_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(targets, f, allow_unicode=True, sort_keys=False)

    with scene_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(scene, f, allow_unicode=True, sort_keys=False)

    print(f"Saved navigation targets: {nav_path}")
    print(f"Saved scene profile: {scene_path}")
    print("\nGenerated targets:")

    for name, pose in targets.items():
        print(f"{name}: x={pose['x']}, y={pose['y']}, yaw={pose['yaw']}")


if __name__ == "__main__":
    main()
