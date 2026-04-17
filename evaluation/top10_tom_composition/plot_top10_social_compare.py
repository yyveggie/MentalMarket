#!/usr/bin/env python3
"""1:1:1 有社交 vs 无社交：Top 10 收益率心智构成 · 哑铃图对比。

风格对齐 evaluation/sentiment_social_compare/plot_sentiment_std_social_compare.py
的 plot_tom_subplots 版本：
 - 浅灰圆点 = 无社交，深灰圆点 = 有社交，中间连线
 - 散点右侧标数值
 - 移除 top/right spine，y 轴浅虚线网格
"""

from __future__ import annotations

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


# (ToM 层级, 无社交 Top10 席位, 有社交 Top10 席位)
DATA = [
    (0, 10, 0),   # ToM0: 无社交独占 10 席 → 有社交 0 席
    (1,  0, 2),   # ToM1: 无社交 0 席    → 有社交 2 席
    (2,  0, 8),   # ToM2: 无社交 0 席    → 有社交 8 席
]


def main():
    toms = [r[0] for r in DATA]
    nosocial = np.array([r[1] for r in DATA])
    social = np.array([r[2] for r in DATA])
    x = np.arange(len(DATA))

    fig, ax = plt.subplots(figsize=(5.0, 4.6), dpi=150)

    # 连接线
    for i in range(len(DATA)):
        ax.plot([x[i], x[i]], [nosocial[i], social[i]],
                color="#999999", linewidth=2, zorder=1)

    # 散点
    ax.scatter(x, nosocial, s=140, color="#e0e0e0",
               edgecolors="black", linewidths=0.9, zorder=2,
               label="无社交")
    ax.scatter(x, social, s=140, color="#424242",
               edgecolors="black", linewidths=0.9, zorder=2,
               label="有社交")

    # 数值标注：点右侧 12pt
    for i in range(len(DATA)):
        for val in (nosocial[i], social[i]):
            ax.annotate(f"{int(val)}", (x[i], val), fontsize=10,
                        ha="left", va="center",
                        xytext=(12, 0), textcoords="offset points",
                        fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels([f"ToM{t}" for t in toms], fontsize=11)
    ax.set_ylabel("Top 10 收益率席位数", fontsize=11)
    ax.set_yticks(range(0, 12, 2))
    ax.set_ylim(-1.2, 11.5)
    ax.set_title("1:1:1 等人口配比下“有社交 vs 无社交” Top 10 收益率的心智层级构成",
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


if __name__ == "__main__":
    main()
