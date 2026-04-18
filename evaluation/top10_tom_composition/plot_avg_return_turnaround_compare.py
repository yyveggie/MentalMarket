#!/usr/bin/env python3
"""7:2:1 基线 vs "认知能否翻盘"：按 ToM 层级的人均收益率 · 哑铃图对比。

风格对齐 plot_top10_turnaround_compare.py：
 - 浅灰圆点 = 基线 7:2:1 (对照)
 - 深灰圆点 = 7:2:1 认知翻盘 (实验组)
 - 中间连线 + 点旁数值标注（单位：百分比）
 - 移除 top/right spine，y 轴浅虚线网格
"""

from __future__ import annotations

import json
from collections import defaultdict
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


def compute_avg_return_by_tom(run_dir: Path) -> dict[int, float]:
    """读取 agent_wealth.jsonl，按最后一日各 ToM 层级的平均 return_pct。"""
    fp = run_dir / "agent_wealth.jsonl"
    if not fp.exists():
        raise FileNotFoundError(fp)

    day_records: dict[int, list] = defaultdict(list)
    with open(fp) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            d = r.get("trading_day"); aid = r.get("agent_id")
            tom = r.get("tom_level"); ret = r.get("return_pct")
            if d is None or aid is None or tom is None or ret is None:
                continue
            day_records[int(d)].append({"tom": int(tom), "ret": float(ret)})

    last = max(day_records)
    by_tom: dict[int, list[float]] = defaultdict(list)
    for r in day_records[last]:
        by_tom[r["tom"]].append(r["ret"])
    return {t: sum(v) / len(v) for t, v in by_tom.items()}


def main():
    baseline = compute_avg_return_by_tom(RUNS_DIR / BASELINE_RUN)
    turnaround = compute_avg_return_by_tom(RUNS_DIR / TURNAROUND_RUN)

    toms = [0, 1, 2]
    left = np.array([baseline[t] for t in toms])
    right = np.array([turnaround[t] for t in toms])
    x = np.arange(len(toms))

    fig, ax = plt.subplots(figsize=(5.4, 4.8), dpi=150)

    # 连接线
    for i in range(len(toms)):
        ax.plot([x[i], x[i]], [left[i], right[i]],
                color="#999999", linewidth=2, zorder=1)

    # 散点
    ax.scatter(x, left, s=140, color="#e0e0e0",
               edgecolors="black", linewidths=0.9, zorder=2,
               label="7:2:1 基线")
    ax.scatter(x, right, s=140, color="#424242",
               edgecolors="black", linewidths=0.9, zorder=2,
               label="7:2:1 认知翻盘")

    # 数值标注：点右侧，显示百分比
    for i in range(len(toms)):
        for val in (left[i], right[i]):
            ax.annotate(f"{val:.2f}%", (x[i], val), fontsize=10,
                        ha="left", va="center",
                        xytext=(12, 0), textcoords="offset points",
                        fontweight="bold")

    # 零轴参考线
    ax.axhline(0, color="#cccccc", linewidth=0.8, linestyle="-", zorder=0)

    ax.set_xticks(x)
    ax.set_xticklabels([f"ToM{t}" for t in toms], fontsize=11)
    ax.set_ylabel("末日人均收益率 (%)", fontsize=11)

    # y 轴范围：覆盖所有点并留白
    ymin = min(left.min(), right.min())
    ymax = max(left.max(), right.max())
    pad = max(3.0, (ymax - ymin) * 0.15)
    ax.set_ylim(ymin - pad, ymax + pad)

    ax.set_title("7:2:1 人口配比下“基线 vs 认知翻盘” 按心智层级的人均收益率",
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
    for t in toms:
        delta = turnaround[t] - baseline[t]
        print(f"  ToM{t}: {baseline[t]:+.2f}% -> {turnaround[t]:+.2f}%  (Δ={delta:+.2f}pp)")


if __name__ == "__main__":
    main()
