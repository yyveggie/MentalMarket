#!/usr/bin/env python3
"""按 ToM 层级对比 有社交 vs 无社交 · 情绪均值哑铃图。

用于替代 sentiment_heatmap_by_tom_social_compare.png：
- 横向三个子图: ToM0 / ToM1 / ToM2
- 每个子图两列: 纯 ToMi 实验、1:1:1 混合实验中该层
- 浅灰圆点 = 无社交，深灰圆点 = 有社交，中间连线
- Y 轴: 情绪均值 mean(sentiment) ∈ [-1, +1]
  +1=极度看多，-1=极度看空，0=中性；综合反映正负情绪的净方向。
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

def load_sentiment_mean_by_tom(run_dir: Path) -> dict[int, float]:
    """返回各 ToM 层级的情绪均值 ∈ [-1, +1]。

    聚合口径（与 plot_sentiment_std_social_compare.py 对齐）：
        1. 先按 (trading_day, tom_level) 计算当日均值
        2. 再对各 tom_level 跨日均值求算数平均
    这样每个交易日等权，避免某天交易密集扭曲整体均值。
    """
    fp = run_dir / "sentiment_series.jsonl"
    if not fp.exists():
        return {}
    # { tom_level: { trading_day: [sentiment, ...] } }
    per_day: dict[int, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    with open(fp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            tom = r.get("tom_level")
            sval = r.get("sentiment")
            day = r.get("trading_day")
            if tom is None or sval is None or day is None:
                continue
            per_day[int(tom)][int(day)].append(float(sval))

    result: dict[int, float] = {}
    for tom, day_map in per_day.items():
        daily_means = [sum(v) / len(v) for v in day_map.values() if v]
        if daily_means:
            result[tom] = sum(daily_means) / len(daily_means)
    return result


def main():
    base = Path("/Users/mushroom/Desktop/MentalMarket/runs")
    runs = {
        "ToM0_nosocial": base / "ToM0_无社交",
        "ToM1_nosocial": base / "ToM1_无社交",
        "ToM2_nosocial": base / "ToM2_无社交",
        "ToM0_social":   base / "ToM0",
        "ToM1_social":   base / "ToM1",
        "ToM2_social":   base / "ToM2",
        "mix_nosocial":  base / "ToM01_ToM11_ToM21_无社交",
        "mix_social":    base / "ToM01_ToM11_ToM21",
    }
    data = {k: load_sentiment_mean_by_tom(v) for k, v in runs.items()}

    print("—— 各 run 按 ToM 层级的情绪均值 mean(sentiment) ——")
    for k, d in data.items():
        print(f"  {k:<18} {d}")

    tom_pairs: dict[int, list[tuple[str, float, float]]] = {}
    for t in (0, 1, 2):
        entries = []
        pure_ns = data[f"ToM{t}_nosocial"].get(t)
        pure_s = data[f"ToM{t}_social"].get(t)
        if pure_ns is not None and pure_s is not None:
            entries.append((f"ToM{t}", pure_ns, pure_s))
        mix_ns = data["mix_nosocial"].get(t)
        mix_s = data["mix_social"].get(t)
        if mix_ns is not None and mix_s is not None:
            entries.append(("1:1:1", mix_ns, mix_s))
        tom_pairs[t] = entries

    toms = [t for t in (0, 1, 2) if tom_pairs[t]]
    n_toms = len(toms)

    fig, axes = plt.subplots(1, n_toms, figsize=(3.2 * n_toms, 4),
                             sharey=True, squeeze=False, dpi=120)

    for ti, t in enumerate(toms):
        ax = axes[0][ti]
        entries = tom_pairs[t]
        n = len(entries)
        labels = [e[0] for e in entries]
        nosocial_vals = np.array([e[1] for e in entries])
        social_vals = np.array([e[2] for e in entries])
        x = np.arange(n)

        for i in range(n):
            ax.plot([x[i], x[i]], [nosocial_vals[i], social_vals[i]],
                    color="#999999", linewidth=2, zorder=1)

        ax.scatter(x, nosocial_vals, s=100, color="#e0e0e0",
                   edgecolors="black", linewidths=0.8, zorder=2,
                   label="无社交")
        ax.scatter(x, social_vals, s=100, color="#424242",
                   edgecolors="black", linewidths=0.8, zorder=2,
                   label="有社交")

        # 两点近距离时分左右，避免标注重叠（阈值 0.05 适适合 [-1,+1] 量级）
        for i in range(n):
            gap = abs(social_vals[i] - nosocial_vals[i])
            if gap < 0.05:
                ax.annotate(f"{nosocial_vals[i]:.2f}", (x[i], nosocial_vals[i]),
                            fontsize=8, ha="right", va="center",
                            xytext=(-12, 0), textcoords="offset points")
                ax.annotate(f"{social_vals[i]:.2f}", (x[i], social_vals[i]),
                            fontsize=8, ha="left", va="center",
                            xytext=(12, 0), textcoords="offset points")
            else:
                for val in (nosocial_vals[i], social_vals[i]):
                    ax.annotate(f"{val:.2f}", (x[i], val), fontsize=8,
                                ha="left", va="center",
                                xytext=(12, 0), textcoords="offset points")

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10)
        ax.set_title(f"ToM{t}", fontsize=11, pad=8)
        ax.grid(True, alpha=0.15, axis="y")
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.margins(x=0.25)

    axes[0][0].set_ylabel("情绪均值  (− 悲观  ←  0  →  乐观 +)", fontsize=10)
    axes[0][-1].legend(fontsize=10, loc="upper right")
    fig.suptitle("有社交 vs 无社交：按 ToM 层级情绪均值对比", fontsize=13)
    for ax in axes[0]:
        ax.axhline(0, color="#cccccc", linewidth=0.8, linestyle="--", zorder=0)

    plt.tight_layout()
    out = str(Path(__file__).with_suffix(".png"))
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] 已保存: {out}")


if __name__ == "__main__":
    main()
