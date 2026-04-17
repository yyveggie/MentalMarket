"""一次性脚本：按 ToM 配比与大盘指数绘制二维散点图（与业务代码无关）。"""

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

# 图中数据：比例 -> (大盘指数, 人均收益率)
DATA = [
    ("1:0:0", 33.5573, -31.32),
    ("0:1:0", 99.9295, 1.17),
    ("0:0:1", 143.3776, 25.28),
    ("0:1:1", 140.5165, 16.91),
    ("1:0:1", 99.9512, -1.32),
    ("1:1:0", 87.5078, -10.46),
    ("1:1:1", 92.5633, -9.01),
    ("7:2:1", 63.1847, -22.86),
    ("6:3:1", 65.8213, -17.87),
    ("2:1:1", 79.4677, -14.01),
    ("2:3:3", 114.865, 3.74),
]


def _ratio_tuple(label: str) -> tuple[int, int, int]:
    a, b, c = (int(x) for x in label.split(":"))
    return (a, b, c)


def _share_p1_p3(label: str) -> tuple[float, float]:
    """返回 (第一类占比, 第三类占比)，均为 0~1。"""
    a, b, c = _ratio_tuple(label)
    total = a + b + c
    return a / total, c / total


def main():
    labels = [r for r, _, _ in DATA]
    index_values = [v for _, v, _ in DATA]
    returns = [r for _, _, r in DATA]
    p1p3 = [_share_p1_p3(lab) for lab in labels]
    p1_pct = [s[0] * 100.0 for s in p1p3]
    p3_pct = [s[1] * 100.0 for s in p1p3]

    # 点大小映射收益率：越正越大，越负越小
    ret_arr = np.array(returns)
    sizes = 60 + 340 * (ret_arr - ret_arr.min()) / max(1e-6, ret_arr.max() - ret_arr.min())

    # 按指数值分三档，用不同 marker 形状区分（黑白友好）
    # 低 (<80): 下三角 v  |  中 (80-120): 圆 o  |  高 (>120): 上三角 ^
    markers = []
    for v in index_values:
        if v < 80:
            markers.append("v")
        elif v <= 120:
            markers.append("o")
        else:
            markers.append("^")

    fig, ax = plt.subplots(figsize=(10, 8), dpi=120, facecolor="#f8fafc")
    ax.set_facecolor("#f8fafc")

    # viridis 色谱在黑白打印下仍可区分明暗
    cmap = plt.cm.viridis
    idx_min, idx_max = min(index_values), max(index_values)
    norm = plt.Normalize(idx_min, idx_max)

    # 逐点绘制在左侧 Y 轴 (ToM2 占比)
    for xp, yp, idx_v, sz, mk in zip(p1_pct, p3_pct, index_values, sizes, markers):
        ax.scatter(
            xp, yp,
            c=[cmap(norm(idx_v))],
            s=sz,
            marker=mk,
            edgecolors="#0f172a",
            linewidths=0.9,
            alpha=0.85,
            zorder=5,
        )

    # colorbar
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, pad=0.02, shrink=0.82)
    cbar.set_label("大盘指数", fontsize=10)

    # 形状图例（黑白区分）
    from matplotlib.lines import Line2D
    legend_elems = [
        Line2D([0], [0], marker="v", color="w", markerfacecolor="gray", markersize=9, markeredgecolor="k", lw=0, label="指数 < 80"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="gray", markersize=9, markeredgecolor="k", lw=0, label="指数 80~120"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="gray", markersize=9, markeredgecolor="k", lw=0, label="指数 > 120"),
    ]
    ax.legend(handles=legend_elems, loc="upper right", fontsize=9, framealpha=0.9, title="指数区间")

    # 标注每个点的配比、指数和收益率（手动偏移避免重叠）
    offset_overrides = {
        "6:3:1": (-40, 14),
        "7:2:1": (40, -18),
        "2:3:3": (0, 16),
        "1:1:1": (40, 4),
        "1:1:0": (-40, -18),
    }
    for xp, yp, idx_v, ret_v, lab in zip(p1_pct, p3_pct, index_values, returns, labels):
        xyoff = offset_overrides.get(lab, (0, 12))
        ax.annotate(
            f"{lab}\n指数{idx_v:.1f} 收益{ret_v:+.1f}%",
            (xp, yp),
            textcoords="offset points",
            xytext=xyoff,
            ha="center",
            fontsize=7.5,
            color="#334155",
            fontweight="medium",
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#cbd5e1", alpha=0.7),
            arrowprops=dict(arrowstyle="-", color="#94a3b8", lw=0.6) if lab in offset_overrides else None,
        )

    ax.set_xlabel("ToM0 占比（%）", fontsize=11, labelpad=8)
    ax.set_ylabel("ToM2 占比（%）", fontsize=11, labelpad=8)
    ax.set_title("ToM0 与 ToM2 占比与大盘指数以及平均收益率散点图（点大小=收益率，形状=指数区间）", fontsize=13, pad=14)

    ax.set_xlim(-5, 105)
    ax.set_ylim(-5, 105)
    ax.grid(False)

    fig.tight_layout()
    out = __file__.replace(".py", ".png")
    plt.savefig(out, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    main()
