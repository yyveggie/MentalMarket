"""第一类信息占比（横轴）与大盘指数（纵轴）的二维折线图（与 ratio_index_chart.py 独立）。"""

import matplotlib.pyplot as plt
import matplotlib

matplotlib.rcParams["font.sans-serif"] = [
    "PingFang SC",
    "Heiti SC",
    "STHeiti",
    "Arial Unicode MS",
    "SimHei",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False

# DATA = [
#     ("1:0:0", 33.5573),
#     ("0:1:0", 99.9295),
#     ("0:0:1", 143.3776),
#     ("0:1:1", 140.5165),
#     ("1:0:1", 99.9512),
#     ("1:1:0", 87.5078),
#     ("1:1:1", 92.5633),
#     ("7:2:1", 63.1847),
#     ("6:3:1", 65.8213),
#     ("2:1:1", 79.4677),
#     ("2:3:3", 114.865),
# ]

# 图中数据：ToM 比例 -> 人均收益率
DATA = [
    ("1:0:0", -31.32),
    ("0:1:0", 1.17),
    ("0:0:1", 25.28),
    ("0:1:1", 16.91),
    ("1:0:1", -1.32),
    ("1:1:0", -10.46),
    ("1:1:1", -9.01),
    ("7:2:1", -22.86),
    ("6:3:1", -17.87),
    ("2:1:1", -14.01),
    ("2:3:3", 3.74),
]


def _ratio_tuple(label: str) -> tuple[int, int, int]:
    a, b, c = (int(x) for x in label.split(":"))
    return (a, b, c)


def _first_share(label: str) -> float:
    a, b, c = _ratio_tuple(label)
    total = a + b + c
    return a / total


def main():
    ordered = sorted(
        DATA,
        key=lambda x: (_first_share(x[0]), *_ratio_tuple(x[0])),
    )
    labels = [r for r, _ in ordered]
    values = [v for _, v in ordered]
    x_pct = [_first_share(lab) * 100.0 for lab in labels]

    fig, ax = plt.subplots(figsize=(10, 5), dpi=120)
    ax.plot(
        x_pct,
        values,
        marker="o",
        linewidth=2,
        markersize=7,
        color="#2563eb",
        markerfacecolor="#3b82f6",
        markeredgecolor="#1e40af",
    )
    ax.set_xlabel("ToM 比例（%）")
    ax.set_ylabel("个人收益率")
    ax.set_title("ToM 在不同比例下的个人收益率趋势图")
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.set_xlim(left=min(x_pct) - 3, right=max(x_pct) + 3)
    y_min = min(values)
    y_max = max(values)
    y_pad = (y_max - y_min) * 0.1 + 1.0
    ax.set_ylim(bottom=y_min - y_pad, top=y_max + y_pad)

    for xp, v, lab in zip(x_pct, values, labels):
        ax.annotate(
            f"{v:.2f}\n{lab}",
            (xp, v),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=7,
            color="#334155",
        )

    plt.tight_layout()
    out = __file__.replace(".py", ".png")
    plt.savefig(out, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    main()
