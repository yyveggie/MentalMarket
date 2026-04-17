#!/usr/bin/env python3
"""按 ToM 层级对比 有社交 vs 无社交 · 人均收益率哑铃图。

风格对齐 evaluation/sentiment_social_compare/sentiment_social_compare_by_tom.png
- 横向三个子图: ToM0 / ToM1 / ToM2
- 每个子图两列: 纯 ToMi 实验、1:1:1 混合实验中该层
- 浅灰圆点 = 无社交，深灰圆点 = 有社交，中间连线
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


def load_last_day_by_tom(run_dir: Path) -> dict[int, float]:
    """返回最后一天各 ToM 层级的人均 return_pct（单位：%）。"""
    fp = run_dir / "agent_wealth.jsonl"
    if not fp.exists():
        return {}
    day_rows: dict[int, list] = defaultdict(list)
    with open(fp) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            day = r.get("trading_day")
            tom = r.get("tom_level", 0)
            ret = r.get("return_pct")
            if day is None or ret is None:
                continue
            day_rows[int(day)].append((int(tom), float(ret)))
    if not day_rows:
        return {}
    last_day = max(day_rows)
    by_tom: dict[int, list[float]] = defaultdict(list)
    for tom, ret in day_rows[last_day]:
        by_tom[tom].append(ret)
    return {t: sum(v) / len(v) for t, v in by_tom.items()}


def main():
    base = Path("/Users/mushroom/Desktop/MentalMarket/runs")

    # 预先读取 8 个 run
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
    data = {k: load_last_day_by_tom(v) for k, v in runs.items()}

    # 打印数值核对
    print("—— 各 run 最后一天按 ToM 层级的人均 return_pct(%) ——")
    for k, d in data.items():
        print(f"  {k:<18} {d}")

    # 构造每个 ToM 子图要画的两列
    # 每列: (label, nosocial_val, social_val)
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

        # 连接线
        for i in range(n):
            ax.plot([x[i], x[i]], [nosocial_vals[i], social_vals[i]],
                    color="#999999", linewidth=2, zorder=1)

        # 无社交浅灰 + 有社交深灰
        ax.scatter(x, nosocial_vals, s=100, color="#e0e0e0",
                   edgecolors="black", linewidths=0.8, zorder=2,
                   label="无社交")
        ax.scatter(x, social_vals, s=100, color="#424242",
                   edgecolors="black", linewidths=0.8, zorder=2,
                   label="有社交")

        # 标注：若两点间距 < 5pp（绝对阈值），则分左右放置避免数值重叠
        for i in range(n):
            gap = abs(social_vals[i] - nosocial_vals[i])
            if gap < 5.0:
                ax.annotate(f"{nosocial_vals[i]:.1f}", (x[i], nosocial_vals[i]),
                            fontsize=8, ha="right", va="center",
                            xytext=(-12, 0), textcoords="offset points")
                ax.annotate(f"{social_vals[i]:.1f}", (x[i], social_vals[i]),
                            fontsize=8, ha="left", va="center",
                            xytext=(12, 0), textcoords="offset points")
            else:
                for val in (nosocial_vals[i], social_vals[i]):
                    ax.annotate(f"{val:.1f}", (x[i], val), fontsize=8,
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
        ax.axhline(0, color="#cccccc", linewidth=0.8, linestyle="--", zorder=0)

    axes[0][0].set_ylabel("人均收益率 (%)", fontsize=11)
    axes[0][-1].legend(fontsize=10, loc="upper right")
    fig.suptitle("有社交 vs 无社交：按 ToM 层级人均收益率对比", fontsize=13)

    plt.tight_layout()
    out = str(Path(__file__).with_suffix(".png"))
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] 已保存: {out}")


if __name__ == "__main__":
    main()
