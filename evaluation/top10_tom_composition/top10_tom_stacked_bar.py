"""堆叠柱状图：各配比下 Top10 收益率的心智构成，灰度友好。"""

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
    a, b, c = (int(x) for x in row[0].split(":"))
    return c / (a + b + c)


def main():
    ordered = sorted(DATA, key=lambda r: r[3], reverse=True)

    labels = [r[0] for r in ordered]
    tom0 = np.array([r[1] for r in ordered])
    tom1 = np.array([r[2] for r in ordered])
    tom2 = np.array([r[3] for r in ordered])

    x = np.arange(len(labels))
    width = 0.55

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=120)

    # 灰度三档：浅→中→深，黑白打印清晰
    g0, g1, g2 = "#e0e0e0", "#9e9e9e", "#424242"  # 浅灰/中灰/深灰
    txt0, txt1, txt2 = "black", "black", "white"    # 文字颜色随底色

    bars0 = ax.bar(x, tom0, width, label="ToM 0", color=g0, edgecolor="white", linewidth=0.8)
    bars1 = ax.bar(x, tom1, width, bottom=tom0, label="ToM 1", color=g1, edgecolor="white", linewidth=0.8)
    bottom2 = tom0 + tom1
    bars2 = ax.bar(x, tom2, width, bottom=bottom2, label="ToM 2", color=g2, edgecolor="white", linewidth=0.8)

    # 标注数量（无背景框，文字颜色适配底色）
    for bars, vals, bottoms, tc in [
        (bars0, tom0, np.zeros(len(labels)), txt0),
        (bars1, tom1, tom0, txt1),
        (bars2, tom2, bottom2, txt2),
    ]:
        for bar, v, b in zip(bars, vals, bottoms):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, b + v / 2,
                        str(v), ha="center", va="center", fontsize=13,
                        fontweight="bold", color=tc)

    ax.set_xlabel("ToM0 : ToM1 : ToM2", fontsize=11, labelpad=12)
    ax.set_ylabel("Top 10 收益率席位数", fontsize=11)
    ax.set_title("各比例下 Top 10 收益率的心智层级构成", fontsize=13, pad=12)
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
