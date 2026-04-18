#!/usr/bin/env python3
"""有社交 vs 无社交 · 日均换手率哑铃图对比（按心智层级分类）。

对比实验配对：
 - 纯 ToM0 有社交  vs  纯 ToM0 无社交
 - 纯 ToM1 有社交  vs  纯 ToM1 无社交
 - 纯 ToM2 有社交  vs  纯 ToM2 无社交
 - 1:1:1 混合中的 ToM0 / ToM1 / ToM2（有社交 vs 无社交）

换手率定义与聚合口径完全对齐 plot_turnover_by_tom.py：
 - 对每个 (agent, day) 取 turnover_rate 最大值（= 当日终盘换手率）
 - 按 tom_level 分组，计算均值
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


RUNS_DIR = Path("/Users/mushroom/Desktop/MentalMarket/runs")
OUT_DIR = Path(__file__).parent
CACHE_FILE = OUT_DIR / "_turnover_social_cache.json"

# (run_name, 是否有社交) 每个 run 对应若干 ToM 层级
PURE_PAIRS = [
    (0, "ToM0", "ToM0_无社交"),
    (1, "ToM1", "ToM1_无社交"),
    (2, "ToM2", "ToM2_无社交"),
]
MIXED_PAIR = ("ToM01_ToM11_ToM21", "ToM01_ToM11_ToM21_无社交")

ALL_RUNS = [r for _, s, ns in PURE_PAIRS for r in (s, ns)] + list(MIXED_PAIR)

COLOR_NOSOCIAL = "#e0e0e0"  # 浅灰
COLOR_SOCIAL = "#424242"    # 深灰
COLOR_LINK = "#999999"


def compute_run(run_dir: Path) -> dict[str, list[float]]:
    """{tom_str: [daily_turnover, ...]}"""
    fp = run_dir / "behavioral_biases.jsonl"
    if not fp.exists():
        return {}
    daily_max: dict[tuple[int, int], tuple[float, int]] = {}
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            tr = r.get("turnover_rate"); aid = r.get("agent_id")
            day = r.get("trading_day"); tom = r.get("tom_level")
            if tr is None or aid is None or day is None or tom is None:
                continue
            key = (int(aid), int(day))
            prev = daily_max.get(key)
            if prev is None or tr > prev[0]:
                daily_max[key] = (float(tr), int(tom))
    by_tom: dict[int, list[float]] = defaultdict(list)
    for _, (tr, tom) in daily_max.items():
        by_tom[tom].append(tr)
    return {str(t): vs for t, vs in by_tom.items()}


def load_or_compute(force: bool = False) -> dict:
    if CACHE_FILE.exists() and not force:
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if all(r in cached for r in ALL_RUNS):
                return cached
        except Exception:
            pass

    result = {}
    for name in ALL_RUNS:
        print(f"  解析 {name} ...", flush=True)
        result[name] = compute_run(RUNS_DIR / name)

    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"  缓存已写入: {CACHE_FILE}")
    return result


def mean_of(vals: list[float]) -> float:
    return float(np.mean(vals)) if vals else float("nan")


def main():
    print("[1/2] 计算各 run 的 per-ToM 日均换手率...")
    raw = load_or_compute()

    # 组装 6 个 x 位置：每个 ToM 层级下有 2 个（纯实验 + 1:1:1）
    # rows 结构：[(label, tom, nosocial_mean, social_mean), ...]
    rows = []
    mixed_s, mixed_ns = MIXED_PAIR
    for tom, social_run, nosocial_run in PURE_PAIRS:
        # 纯实验
        s_vals = raw.get(social_run, {}).get(str(tom), [])
        ns_vals = raw.get(nosocial_run, {}).get(str(tom), [])
        rows.append((f"ToM{tom}", tom, mean_of(ns_vals), mean_of(s_vals), len(ns_vals), len(s_vals)))
        # 1:1:1 下的该 ToM 层级
        s_mix = raw.get(mixed_s, {}).get(str(tom), [])
        ns_mix = raw.get(mixed_ns, {}).get(str(tom), [])
        rows.append(("1:1:1", tom, mean_of(ns_mix), mean_of(s_mix), len(ns_mix), len(s_mix)))

    # 打印
    print("\n[2/2] 结果:")
    print(f"{'分组':<16}{'ToM':>5}{'无社交':>12}{'有社交':>12}{'Δ(social-nosocial)':>22}{'n_ns':>8}{'n_s':>8}")
    print("-" * 84)
    for label, tom, ns, s, n_ns, n_s in rows:
        delta = s - ns
        print(f"{label:<16}{tom:>5}{ns:>12.4f}{s:>12.4f}{delta:>+22.4f}{n_ns:>8}{n_s:>8}")

    # ── 绘图 ─────────────────────────────────────────────────────
    plt.rcParams.update({
        "font.sans-serif": [
            "Heiti TC", "PingFang SC", "Arial Unicode MS",
            "STHeiti", "SimHei", "Arial"],
        "axes.unicode_minus": False,
    })

    # x 位置：每个 ToM 层级占 2 个位置，层级间留空
    x_positions = []
    group_centers = []
    cursor = 0
    for gi in range(3):
        x_positions.append(cursor)
        x_positions.append(cursor + 1)
        group_centers.append(cursor + 0.5)
        cursor += 3  # 2 个柱位 + 1 个空位

    labels = [r[0] for r in rows]
    nosocial = np.array([r[2] for r in rows])
    social = np.array([r[3] for r in rows])

    fig, ax = plt.subplots(figsize=(8.5, 5.0), dpi=150)

    # 连接线
    for i, x in enumerate(x_positions):
        ax.plot([x, x], [nosocial[i], social[i]],
                color=COLOR_LINK, linewidth=2, zorder=1)

    # 散点
    ax.scatter(x_positions, nosocial, s=140, color=COLOR_NOSOCIAL,
               edgecolors="black", linewidths=0.9, zorder=2,
               label="无社交")
    ax.scatter(x_positions, social, s=140, color=COLOR_SOCIAL,
               edgecolors="black", linewidths=0.9, zorder=2,
               label="有社交")

    # 数值标注：无社交标左，有社交标右
    for i, x in enumerate(x_positions):
        ax.annotate(f"{nosocial[i]:.3f}", (x, nosocial[i]), fontsize=9,
                    ha="right", va="center",
                    xytext=(-10, 0), textcoords="offset points",
                    color="#555555")
        ax.annotate(f"{social[i]:.3f}", (x, social[i]), fontsize=9,
                    ha="left", va="center",
                    xytext=(10, 0), textcoords="offset points",
                    fontweight="bold")

    # 顶部 ToM 分组标注
    ymax = max(nosocial.max(), social.max())
    for gi, center in enumerate(group_centers):
        ax.text(center, ymax * 1.10, f"ToM{gi}",
                ha="center", va="bottom",
                fontsize=12, fontweight="bold", color="#333333")

    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, fontsize=10, rotation=0)
    ax.set_xlim(x_positions[0] - 0.7, x_positions[-1] + 0.7)
    ax.set_ylabel("日均换手率", fontsize=11)
    ax.set_ylim(0, ymax * 1.22)
    ax.set_title("有社交 vs 无社交 · 日均换手率对比",
                 fontsize=13, pad=14)

    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.legend(fontsize=10, loc="upper left", bbox_to_anchor=(1.0, 1.0),
              framealpha=0.9, borderaxespad=0.0)

    plt.tight_layout()
    out_png = OUT_DIR / "有无社交换手率_哑铃对比.png"
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"\n对比图: {out_png}")


if __name__ == "__main__":
    main()
