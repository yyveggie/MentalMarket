#!/usr/bin/env python3
"""有社交 vs 无社交 — 最终大盘指数哑铃图"""

import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.sans-serif": ["PingFang SC", "Heiti TC", "Arial Unicode MS",
                        "STHeiti", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
})

RUNS = os.path.join(str(Path(__file__).resolve().parents[2]), "runs")

# (有社交目录, 无社交目录, 显示标签)
PAIRS = [
    ("ToM0", "ToM0_无社交", "ToM0"),
    ("ToM1", "ToM1_无社交", "ToM1"),
    ("ToM2", "ToM2_无社交", "ToM2"),
    ("ToM01_ToM11_ToM21", "ToM01_ToM11_ToM21_无社交", "1:1:1"),
]


def _read_last_index(run_dir):
    path = os.path.join(run_dir, "broad_index.jsonl")
    if not os.path.exists(path):
        return None
    last = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                last = line
    if last:
        return json.loads(last).get("value")
    return None


def main():
    output_dir = os.path.dirname(__file__)

    labels = []
    social_vals = []
    nosocial_vals = []

    for social_dir, nosocial_dir, label in PAIRS:
        sv = _read_last_index(os.path.join(RUNS, social_dir))
        nv = _read_last_index(os.path.join(RUNS, nosocial_dir))
        if sv is not None and nv is not None:
            labels.append(label)
            social_vals.append(sv)
            nosocial_vals.append(nv)

    n = len(labels)
    if n == 0:
        print("No data found.")
        return

    fig, ax = plt.subplots(figsize=(5.5, 4), dpi=120)
    x = list(range(n))

    # 连接线（竖直方向）
    for i in range(n):
        ax.plot([i, i], [nosocial_vals[i], social_vals[i]],
                color="#999999", linewidth=2, zorder=1)

    # 无社交点
    ax.scatter(x, nosocial_vals, s=100, color="#e0e0e0", edgecolors="black",
               linewidths=0.8, zorder=2, label="无社交")
    # 有社交点
    ax.scatter(x, social_vals, s=100, color="#424242", edgecolors="black",
               linewidths=0.8, zorder=2, label="有社交")

    # 数值标注：放到散点右侧，水平偏移 12pt，避免与圆点重叠
    for i in range(n):
        for val in (nosocial_vals[i], social_vals[i]):
            ax.annotate(f"{val:.1f}", (i, val), fontsize=8,
                        ha="left", va="center",
                        xytext=(12, 0), textcoords="offset points")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("最终大盘指数", fontsize=11)
    ax.set_title("有社交 vs 无社交：最终大盘指数对比", fontsize=13, pad=10)
    ax.legend(fontsize=10, loc="lower right")
    ax.grid(True, alpha=0.15, axis="y")
    # 预留右侧空间，防止标注被裁剪
    ax.margins(x=0.1)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    out = os.path.join(output_dir, "有社交vs无社交_大盘哑铃图.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
