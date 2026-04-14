"""堆叠柱状图：各配比下 Top10 收益率的心智构成，展示 ToM2 即使少数也占多数席位。"""

import matplotlib.pyplot as plt
import matplotlib
import numpy as np

matplotlib.rcParams["font.sans-serif"] = [
    "PingFang SC",
    "Heiti SC",
    "STHeiti",
    "Arial Unicode MS",
    "SimHei",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False

# (比例标签, ToM0数量, ToM1数量, ToM2数量)
DATA = [
    ("0:1:1", 0, 0, 10),
    ("1:0:1", 1, 0, 9),
    ("1:1:1", 0, 2, 8),
    ("2:1:1", 2, 1, 7),
    ("2:3:3", 1, 2, 7),
    ("7:2:1", 5, 0, 5),
    ("6:3:1", 6, 0, 4),
]


def _tom2_ratio(row):
    """ToM2 实际占比，用于排序。"""
    a, b, c = (int(x) for x in row[0].split(":"))
    return c / (a + b + c)


def main():
    # 按 ToM2 Top10 数量降序排列
    ordered = sorted(DATA, key=lambda r: r[3], reverse=True)

    labels = [r[0] for r in ordered]
    tom0 = [r[1] for r in ordered]
    tom1 = [r[2] for r in ordered]
    tom2 = [r[3] for r in ordered]

    x = np.arange(len(labels))
    width = 0.55

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=120)

    # 堆叠柱
    c0 = "#60a5fa"  # 蓝 - ToM0
    c1 = "#fbbf24"  # 黄 - ToM1
    c2 = "#f87171"  # 红 - ToM2

    bars0 = ax.bar(x, tom0, width, label="ToM 0", color=c0, edgecolor="white", linewidth=0.8)
    bars1 = ax.bar(x, tom1, width, bottom=tom0, label="ToM 1", color=c1, edgecolor="white", linewidth=0.8)
    bottom2 = [a + b for a, b in zip(tom0, tom1)]
    bars2 = ax.bar(x, tom2, width, bottom=bottom2, label="ToM 2", color=c2, edgecolor="white", linewidth=0.8)

    # 在每段上标注数量（>0 时显示）
    for bars, vals, bottoms in [
        (bars0, tom0, [0] * len(labels)),
        (bars1, tom1, tom0),
        (bars2, tom2, bottom2),
    ]:
        for bar, v, b in zip(bars, vals, bottoms):
            if v > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    b + v / 2,
                    str(v),
                    ha="center",
                    va="center",
                    fontsize=11,
                    fontweight="bold",
                    color="#1e293b",
                )

    # 在每根柱子下方标注 ToM2 实际占比（紧贴比例标签下方）
    for i, lab in enumerate(labels):
        ratio = _tom2_ratio(ordered[i])
        ax.annotate(
            f"{ratio:.0%}",
            xy=(x[i], 0),
            xytext=(0, -22),
            textcoords="offset points",
            ha="center",
            va="top",
            fontsize=8,
            color="#64748b",
        )

    ax.set_xlabel("智能体配比（ToM0 : ToM1 : ToM2）", fontsize=11, labelpad=32)
    ax.set_ylabel("Top 10 收益率席位数", fontsize=11)
    ax.set_title("各配比下 Top 10 收益率的心智层级构成", fontsize=13, pad=12)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_yticks(range(0, 11, 2))
    ax.set_ylim(0, 11)
    ax.legend(loc="upper right", fontsize=10, framealpha=0.9)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    out = __file__.replace(".py", ".png")
    plt.savefig(out, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
