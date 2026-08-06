#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quickly test RoboBrain's autonomous inspection-path planning ability.

Modes:
  direct: call the OpenAI-compatible vLLM endpoint directly (recommended for
          isolating the model's planning ability).
  roboos: submit the same task through RoboOS master /publish_task.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests


DIRECT_BASE_URL = os.getenv("ROBOBRAIN_BASE_URL", "http://127.0.0.1:8000")
ROBOOS_URL = os.getenv("ROBOOS_URL", "http://127.0.0.1:5000/publish_task")
TASK_KEY = os.getenv("ROBOOS_TASK_KEY", "task")
TIMEOUT = int(os.getenv("ROBOBRAIN_TIMEOUT", "180"))

# Coordinate convention used by this test:
# - Origin is in the middle of the left side of the central aisle.
# - The two cabinet rows are y=+2 and y=-2, so their separation is 4 m.
# - Cabinet fronts face the central aisle (toward y=0).
# - Inspection points are 0.5 m in front of each cabinet: y=+1.5 / -1.5.
# - Exact 2 m center spacing is retained. This makes cabinet 6 center x=10.5 m;
#   therefore the exact geometry slightly exceeds a nominal 10 m width.
X_VALUES = [0.5 + 2.0 * i for i in range(6)]
EXPECTED_POINTS = {
    **{f"A{i + 1}": (x, 1.5) for i, x in enumerate(X_VALUES)},
    **{f"B{i + 1}": (x, -1.5) for i, x in enumerate(X_VALUES)},
}
ORIGIN = (0.0, 0.0)
OPTIMAL_REFERENCE_M = (
    math.dist(ORIGIN, EXPECTED_POINTS["A1"])
    + math.dist(EXPECTED_POINTS["A1"], EXPECTED_POINTS["A6"])
    + math.dist(EXPECTED_POINTS["A6"], EXPECTED_POINTS["B6"])
    + math.dist(EXPECTED_POINTS["B6"], EXPECTED_POINTS["B1"])
    + math.dist(EXPECTED_POINTS["B1"], ORIGIN)
)

TEST_PROMPT = r"""
你是 RoboOS 中负责移动机器人任务规划的 RoboBrain 模型。现在只测试你的二维空间理解和自主路径规划能力，不执行 Nav2，不调用预设 path_id，也不允许使用人工给定的访问顺序。

【坐标系】
1. 起点/终点为原点 O=(0.0, 0.0)。
2. x 轴沿柜子排列方向向右，y 轴垂直于柜子排布方向。
3. 两排柜子的中心线分别位于 y=+2.0 m 和 y=-2.0 m，两排相距 4.0 m。
4. 上排柜子编号 A1-A6，下排柜子编号 B1-B6。
5. 每个柜子宽 0.5 m。
6. 每排第 1 个柜子的中心 x=0.5 m；相邻柜子中心间距为 2.0 m。因此第 i 个柜子的中心横坐标为 x=0.5+2.0*(i-1)。
7. 两排柜子的正面都朝向中央通道 y=0：上排朝 -y，下排朝 +y。
8. 巡检点必须位于柜子正面正中央前方 0.5 m：上排巡检点 y=+1.5，下排巡检点 y=-1.5。
9. 除柜子本体外，中央通道无其他障碍；机器人可在巡检点之间走直线。
10. 原始描述中的“宽度 10 m”与严格的 2 m 中心间距存在轻微边界冲突：第 6 个柜子中心会到 x=10.5 m。本测试以“第一个中心 0.5 m、中心间距 2 m”为优先约束，不要擅自修改间距。

【任务】
自主计算 12 个巡检点坐标，并规划一条从 O 出发、每个柜子恰好巡视一次、最后返回 O 的近似最短闭合路径。优先采用连续、少折返、总距离较短的路线。不得直接假设固定顺序，必须根据几何布局选择路线。

【输出要求】
只输出一个合法 JSON 对象，不要 Markdown 代码块，不要附加解释，不要输出详细思维过程。格式必须为：
{
  "reasoning_summary": "不超过80字的简要规划依据",
  "layout_conflict": "说明10m宽度与2m间距的冲突及采用的处理",
  "inspection_points": [
    {"name":"A1","x":0.5,"y":1.5},
    ...
  ],
  "visit_order": ["O", "A1", "...", "O"],
  "waypoints": [
    {"name":"O","x":0.0,"y":0.0},
    ...
  ],
  "total_distance_m": 0.0
}

必须满足：
- inspection_points 正好包含 A1-A6、B1-B6，每个一次；
- visit_order 首尾必须为 O，中间正好包含 12 个柜子名，每个一次；
- waypoints 顺序必须与 visit_order 完全一致；
- total_distance_m 按相邻 waypoint 的欧氏距离求和，保留 2 位小数；
- 不得增加不存在的柜子，不得遗漏柜子，不得输出 path_id。
""".strip()


def discover_model(base_url: str) -> str:
    env_model = os.getenv("ROBOBRAIN_MODEL")
    if env_model:
        return env_model
    response = requests.get(f"{base_url.rstrip('/')}/v1/models", timeout=20)
    response.raise_for_status()
    data = response.json()
    models = data.get("data", [])
    if not models:
        raise RuntimeError("No model was returned by /v1/models")
    return models[0]["id"]


def call_direct(base_url: str, temperature: float) -> tuple[str, Any]:
    model = discover_model(base_url)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是移动机器人路径规划器。严格遵守坐标约束并只输出合法 JSON。",
            },
            {"role": "user", "content": TEST_PROMPT},
        ],
        "temperature": temperature,
        "max_tokens": 1800,
    }
    response = requests.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    raw = response.json()
    text = raw["choices"][0]["message"]["content"]
    return text, raw


def call_roboos(url: str) -> tuple[str, Any]:
    payload = {TASK_KEY: TEST_PROMPT}
    response = requests.post(url, json=payload, timeout=TIMEOUT)
    response.raise_for_status()
    try:
        raw = response.json()
        return json.dumps(raw, ensure_ascii=False, indent=2), raw
    except ValueError:
        return response.text, response.text


def extract_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(cleaned[start : i + 1])
                        return obj if isinstance(obj, dict) else None
                    except json.JSONDecodeError:
                        return None
    return None


def calculate_path_distance(waypoints: list[dict[str, Any]]) -> float:
    total = 0.0
    for a, b in zip(waypoints, waypoints[1:]):
        total += math.dist((float(a["x"]), float(a["y"])), (float(b["x"]), float(b["y"])))
    return total


def validate_plan(plan: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    notes: list[str] = []

    required = {
        "reasoning_summary",
        "layout_conflict",
        "inspection_points",
        "visit_order",
        "waypoints",
        "total_distance_m",
    }
    missing = sorted(required - set(plan))
    if not missing:
        score += 1
        notes.append("[PASS] JSON 字段完整")
    else:
        notes.append(f"[FAIL] 缺少字段: {missing}")

    order = plan.get("visit_order", [])
    cabinet_order = order[1:-1] if len(order) >= 2 else []
    expected_names = set(EXPECTED_POINTS)
    if (
        len(order) == 14
        and order[0] == "O"
        and order[-1] == "O"
        and len(cabinet_order) == 12
        and set(cabinet_order) == expected_names
        and len(set(cabinet_order)) == 12
    ):
        score += 1
        notes.append("[PASS] 起终点正确，12 个柜子均恰好访问一次")
    else:
        notes.append(f"[FAIL] visit_order 不合格: {order}")

    points = plan.get("inspection_points", [])
    point_map: dict[str, tuple[float, float]] = {}
    try:
        for p in points:
            point_map[str(p["name"])] = (float(p["x"]), float(p["y"]))
    except (KeyError, TypeError, ValueError):
        point_map = {}

    coordinate_ok = set(point_map) == expected_names
    if coordinate_ok:
        for name, expected in EXPECTED_POINTS.items():
            if math.dist(point_map[name], expected) > 0.05:
                coordinate_ok = False
                break
    if coordinate_ok:
        score += 1
        notes.append("[PASS] 12 个巡检点坐标正确")
    else:
        notes.append("[FAIL] 巡检点名称或坐标错误")

    waypoints = plan.get("waypoints", [])
    waypoint_names = [w.get("name") for w in waypoints if isinstance(w, dict)]
    waypoint_ok = waypoint_names == order and len(waypoints) == 14
    if waypoint_ok:
        try:
            for w in waypoints:
                name = w["name"]
                expected = ORIGIN if name == "O" else EXPECTED_POINTS[name]
                actual = (float(w["x"]), float(w["y"]))
                if math.dist(actual, expected) > 0.05:
                    waypoint_ok = False
                    break
        except (KeyError, TypeError, ValueError):
            waypoint_ok = False
    if waypoint_ok:
        score += 1
        notes.append("[PASS] waypoints 与访问顺序及坐标一致")
    else:
        notes.append("[FAIL] waypoints 与 visit_order 不一致")

    distance_ok = False
    near_optimal = False
    if waypoint_ok:
        calculated = calculate_path_distance(waypoints)
        try:
            reported = float(plan.get("total_distance_m"))
            distance_ok = abs(calculated - reported) <= 0.08
            # The two symmetric serpentine solutions are about 26.16 m.
            near_optimal = calculated <= OPTIMAL_REFERENCE_M + 0.50
            if distance_ok and near_optimal:
                score += 1
                notes.append(
                    f"[PASS] 距离计算正确且接近参考最优: {calculated:.2f} m "
                    f"(参考 {OPTIMAL_REFERENCE_M:.2f} m)"
                )
            else:
                notes.append(
                    f"[FAIL] 距离问题: 模型报告={reported:.2f}, 实算={calculated:.2f}, "
                    f"参考={OPTIMAL_REFERENCE_M:.2f}"
                )
        except (TypeError, ValueError):
            notes.append("[FAIL] total_distance_m 不是有效数字")
    else:
        notes.append("[FAIL] 无法计算路径距离")

    return score, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="RoboBrain path-planning quick test")
    parser.add_argument(
        "--mode",
        choices=["direct", "roboos"],
        default="direct",
        help="direct=直接调用vLLM；roboos=通过RoboOS master提交任务",
    )
    parser.add_argument("--runs", type=int, default=1, help="重复测试次数")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--base-url", default=DIRECT_BASE_URL)
    parser.add_argument("--roboos-url", default=ROBOOS_URL)
    args = parser.parse_args()

    if args.runs < 1:
        print("--runs must be >= 1", file=sys.stderr)
        return 2

    result_dir = Path("robobrain_path_test_results")
    result_dir.mkdir(exist_ok=True)
    scores: list[int] = []

    print(f"Reference near-optimal distance: {OPTIMAL_REFERENCE_M:.2f} m")
    print(f"Mode: {args.mode}; runs: {args.runs}\n")

    for run_idx in range(1, args.runs + 1):
        print(f"========== RUN {run_idx}/{args.runs} ==========")
        started = time.time()
        try:
            if args.mode == "direct":
                text, raw = call_direct(args.base_url, args.temperature)
            else:
                text, raw = call_roboos(args.roboos_url)
        except requests.RequestException as exc:
            print(f"Request failed: {exc}", file=sys.stderr)
            return 1
        except (KeyError, RuntimeError, ValueError) as exc:
            print(f"Response parsing failed: {exc}", file=sys.stderr)
            return 1

        elapsed = time.time() - started
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out_path = result_dir / f"run_{run_idx}_{stamp}.txt"
        out_path.write_text(text, encoding="utf-8")

        print(text)
        print(f"\nElapsed: {elapsed:.2f} s")
        print(f"Saved: {out_path}")

        if args.mode == "roboos":
            print(
                "RoboOS 模式通常只返回接收状态；请同时查看 master 终端中的 "
                "planner_raw_output / final_output。"
            )
            continue

        plan = extract_json(text)
        if plan is None:
            print("\nScore: 0/5")
            print("[FAIL] 模型输出不是可解析 JSON")
            scores.append(0)
        else:
            score, notes = validate_plan(plan)
            scores.append(score)
            print(f"\nScore: {score}/5")
            for note in notes:
                print(note)
        print()

    if scores:
        avg = sum(scores) / len(scores)
        success = sum(score >= 4 for score in scores)
        print("========== SUMMARY ==========")
        print(f"Average score: {avg:.2f}/5")
        print(f"Planning pass rate (>=4/5): {success}/{len(scores)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
