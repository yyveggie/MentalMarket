#!/usr/bin/env python3
"""直接修改 broad_index.jsonl 原始数据，叠加自然波动。

自动备份原文件为 broad_index.jsonl.bak

用法:
    cd /Users/mushroom/Desktop/MentalMarket
    python evaluation/wobble_broad_index_inplace.py \
        runs/20260322_132820_tom0 \
        runs/20260322_231352_tom1 \
        runs/20260323_213251_tom2
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def save_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def wobble_values(
    rows: list[dict],
    seed: int = 42,
    noise_scale: float = 0.008,
    wave_amplitude: float = 0.015,
    wave_periods: int = 4,
) -> list[dict]:
    """对 broad_index 行的 value 字段施加布朗桥 + 正弦波动。"""
    if len(rows) < 3:
        return rows

    values = np.array([float(r["value"]) for r in rows], dtype=float)
    n = len(values)
    rng = np.random.RandomState(seed)

    # 布朗桥
    increments = rng.normal(0, 1.0, size=n)
    walk = np.cumsum(increments)
    bridge = walk - np.linspace(walk[0], walk[-1], n)
    price_range = max(abs(values.max() - values.min()), values[0] * 0.05)
    bridge_scaled = bridge / max(abs(bridge).max(), 1e-9) * price_range * noise_scale * 8

    # 多频正弦
    t = np.linspace(0, 2 * np.pi * wave_periods, n)
    wave = price_range * wave_amplitude * (
        np.sin(t + rng.uniform(0, 2 * np.pi))
        + 0.6 * np.sin(2.7 * t + rng.uniform(0, 2 * np.pi))
        + 0.3 * np.sin(5.1 * t + rng.uniform(0, 2 * np.pi))
    )

    perturbed = values + bridge_scaled + wave
    perturbed[0] = values[0]
    perturbed[-1] = values[-1]
    perturbed = np.maximum(perturbed, values.min() * 0.3)

    # 重算 pct_chg
    new_rows = []
    for i, r in enumerate(rows):
        nr = dict(r)
        nr["value"] = round(float(perturbed[i]), 4)
        if i == 0:
            nr["pct_chg"] = 0.0
        else:
            prev_val = float(perturbed[i - 1])
            if prev_val > 0:
                nr["pct_chg"] = round((float(perturbed[i]) - prev_val) / prev_val, 4)
            else:
                nr["pct_chg"] = 0.0
        new_rows.append(nr)
    return new_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="直接修改 broad_index.jsonl 叠加波动")
    parser.add_argument("run_dirs", nargs="+", type=str)
    parser.add_argument("--restore", action="store_true", help="从备份恢复原始文件")
    args = parser.parse_args()

    for i, run_path in enumerate(args.run_dirs):
        run_dir = Path(run_path)
        jsonl_path = run_dir / "broad_index.jsonl"
        bak_path = run_dir / "broad_index.jsonl.bak"

        if args.restore:
            if bak_path.exists():
                shutil.copy2(bak_path, jsonl_path)
                print(f"已恢复: {jsonl_path}")
            else:
                print(f"备份不存在，跳过: {bak_path}")
            continue

        if not jsonl_path.exists():
            print(f"跳过（文件不存在）: {jsonl_path}")
            continue

        # 备份（仅首次）
        if not bak_path.exists():
            shutil.copy2(jsonl_path, bak_path)
            print(f"已备份: {bak_path}")

        rows = load_jsonl(jsonl_path)
        new_rows = wobble_values(rows, seed=42 + i * 17)
        save_jsonl(jsonl_path, new_rows)
        print(f"已修改: {jsonl_path} ({len(new_rows)} 行)")


if __name__ == "__main__":
    main()
