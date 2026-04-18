#!/usr/bin/env python3
"""7:2:1 基线 vs "认知能否翻盘"：Top 10 收益率心智构成 · 哑铃图对比。

风格对齐 plot_top10_social_compare.py：
 - 浅灰圆点 = 基线 7:2:1 (对照)
 - 深灰圆点 = 7:2:1 认知能否翻盘 (实验组)
 - 中间连线 + 点右侧数值标注
 - 移除 top/right spine，y 轴浅虚线网格
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams["font.sans-serif"] = [
    "PingFang SC", "Heiti SC", "STHeiti",
    "Arial Unicode MS", "SimHei", "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False


RUNS_DIR = Path("/Users/mushroom/Desktop/MentalMarket/runs")
BASELINE_RUN = "ToM07_ToM12_ToM21"
TURNAROUND_RUN = "ToM07_ToM12_ToM21_认知能否翻盘"


def compute_top10_composition(run_dir: Path) -> dict:
    """读取 agent_wealth.jsonl，按最后一天 return_pct 统计 Top10 ToM 构成。"""
    fp = run_dir / "agent_wealth.jsonl"
    if not fp.exists():
        raise FileNotFoundError(fp)

    day_agents: dict[int, list] = defaultdict(list)
    with open(fp) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            day = r.get("trading_day")
            aid = r.get("agent_id")
            tom = r.get("tom_level", 0)
            ret = r.get("return_pct")
            if day is None or aid is None or ret is None:
                continue
            day_agents[int(day)].append({"aid": aid, "tom": int(tom), "ret": float(ret)})

    last_day = max(day_agents)
    agents = sorted(day_agents[last_day], key=lambda a: a["ret"], reverse=True)
    top10 = agents[:10]
    return Counter(a["tom"] for a in top10)


def main():
    baseline = compute_top10_composition(RUNS_DIR / BASELINE_RUN)
    turnaround = compute_top10_composition(RUNS_DIR / TURNAROUND_RUN)

    toms = [0, 1, 2]
    left = np.array([baseline.get(t, 0) for t in toms])
    right = np.array([turnaround.get(t, 0) for t in toms])
    x = np.arange(len(toms))

    # 重合点横向微错位，避免浅色被深色完全覆盖
    offset = 0.08
    x_left = np.array([xi - (offset if l == r else 0.0) for xi, l, r in zip(x, left, right)])
    x_right = np.array([xi + (offset if l == r else 0.0) for xi, l, r in zip(x, left, right)])

    fig, ax = plt.subplots(figsize=(5.0, 4.6), dpi=150)

    # 连接线（仅当两点不重合时绘制）
    for i in range(len(toms)):
        if left[i] != right[i]:
            ax.plot([x[i], x[i]], [left[i], right[i]],
                    color="#999999", linewidth=2, zorder=1)

    # 散点
    ax.scatter(x_left, left, s=140, color="#e0e0e0",
               edgecolors="black", linewidths=0.9, zorder=2,
               label="7:2:1 基线")
    ax.scatter(x_right, right, s=140, color="#424242",
               edgecolors="black", linewidths=0.9, zorder=2,
               label="7:2:1 认知翻盘")

    # 数值标注：基线标左侧，实验组标右侧
    for i in range(len(toms)):
        ax.annotate(f"{int(left[i])}", (x_left[i], left[i]), fontsize=10,
                    ha="right", va="center",
                    xytext=(-12, 0), textcoords="offset points",
                    fontweight="bold", color="#555555")
        ax.annotate(f"{int(right[i])}", (x_right[i], right[i]), fontsize=10,
                    ha="left", va="center",
                    xytext=(12, 0), textcoords="offset points",
                    fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels([f"ToM{t}" for t in toms], fontsize=11)
    ax.set_ylabel("Top 10 收益率席位数", fontsize=11)
    ax.set_yticks(range(0, 12, 2))
    ax.set_ylim(-1.2, 11.5)
    ax.set_title("7:2:1 人口配比下“基线 vs 认知翻盘” Top 10 收益率的心智层级构成",
                 fontsize=13, pad=12)

    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.margins(x=0.28)

    ax.legend(fontsize=10, loc="upper right", framealpha=0.9)

    plt.tight_layout()
    out = str(Path(__file__).with_suffix(".png"))
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] 已保存: {out}")
    print(f"  基线 7:2:1 Top10 T0:T1:T2 = {left[0]}:{left[1]}:{left[2]}")
    print(f"  认知翻盘 7:2:1 Top10 T0:T1:T2 = {right[0]}:{right[1]}:{right[2]}")


if __name__ == "__main__":
    main()
