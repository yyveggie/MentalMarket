"""一次性脚本：按图中比例与大盘指数绘制趋势曲线（与业务代码无关）。"""

import matplotlib.pyplot as plt
import matplotlib
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

matplotlib.rcParams["font.sans-serif"] = [
    "PingFang SC",
    "Heiti SC",
    "STHeiti",
    "Arial Unicode MS",
    "SimHei",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False

# 图中数据：比例 -> 大盘指数
DATA = [
    ("1:0:0", 33.5573),
    ("0:1:0", 99.9295),
    ("0:0:1", 143.3776),
    ("0:1:1", 140.5165),
    ("1:0:1", 99.9512),
    ("1:1:0", 87.5078),
    ("1:1:1", 92.5633),
    ("7:2:1", 63.1847),
    ("6:3:1", 65.8213),
    ("2:1:1", 79.4677),
    ("2:3:3", 114.865),
]


def _ratio_tuple(label: str) -> tuple[int, int, int]:
    a, b, c = (int(x) for x in label.split(":"))
    return (a, b, c)


def _first_share(label: str) -> float:
    """第一类在总量中的占比 a/(a+b+c)。如 1:0:0 为 100%，0:1:0 为 0%。"""

    a, b, c = _ratio_tuple(label)
    total = a + b + c
    return a / total


def _share_p1_p3(label: str) -> tuple[float, float]:
    """返回 (第一类占比, 第三类占比)，均为 0~1。"""

    a, b, c = _ratio_tuple(label)
    total = a + b + c
    return a / total, c / total


def main():
    # 横轴：第一类「占比」a/(a+b+c) 递增；占比相同再按 (a,b,c) 字典序，避免歧义
    ordered = sorted(
        DATA,
        key=lambda x: (_first_share(x[0]), *_ratio_tuple(x[0])),
    )
    labels = [r for r, _ in ordered]
    values = [v for _, v in ordered]
    p1p3 = [_share_p1_p3(lab) for lab in labels]
    p1_pct = [s[0] * 100.0 for s in p1p3]
    p3_pct = [s[1] * 100.0 for s in p1p3]

    z_min = min(values)
    z_max = max(values)
    z_pad = (z_max - z_min) * 0.08 + 1.0
    z_floor = z_min - z_pad

    fig = plt.figure(figsize=(10, 8), dpi=120, facecolor="#f8fafc")
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor("#f8fafc")

    # 配比可行域在 p1-p3 平面上的投影（底面浅色三角，p1+p2+p3=100% 边界）
    tri_verts = [(0, 0, z_floor), (100, 0, z_floor), (0, 100, z_floor)]
    tri = Poly3DCollection(
        [tri_verts],
        alpha=0.12,
        facecolor="#94a3b8",
        edgecolor="#cbd5e1",
        linewidths=0.8,
    )
    ax.add_collection3d(tri)

    # 按排序连接轨迹；颜色映射大盘指数
    norm = plt.Normalize(min(values), max(values))
    ax.plot(
        p1_pct,
        p3_pct,
        values,
        color="#475569",
        linewidth=1.4,
        alpha=0.75,
        label="配比轨迹（按第一类占比递增）",
    )
    sc = ax.scatter(
        p1_pct,
        p3_pct,
        values,
        c=values,
        cmap="plasma",
        s=140,
        norm=norm,
        edgecolors="#0f172a",
        linewidths=0.9,
        depthshade=True,
        label="观测点",
    )

    ax.set_xlabel("ToM0 占比（%）", labelpad=10, fontsize=10)
    ax.set_ylabel("ToM2 占比（%）", labelpad=10, fontsize=10)
    ax.set_zlabel("大盘指数", labelpad=10, fontsize=10)
    ax.set_title(
        "ToM0 与 ToM2 占比与大盘指数",
        fontsize=12,
        pad=16,
    )

    ax.set_xlim(-5, 105)
    ax.set_ylim(-5, 105)
    ax.set_zlim(z_floor, z_max + z_pad)

    ax.view_init(elev=24, azim=-52)
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.xaxis.pane.set_edgecolor("#e2e8f0")
    ax.yaxis.pane.set_edgecolor("#e2e8f0")
    ax.zaxis.pane.set_edgecolor("#e2e8f0")

    # 图例（colorbar 已表示指数，此处仅保留轨迹说明）
    h_traj = plt.Line2D([0], [0], color="#475569", lw=1.4, label="轨迹连线")
    h_pt = plt.Line2D(
        [0],
        [0],
        marker="o",
        color="w",
        markerfacecolor="#7c3aed",
        markersize=9,
        markeredgecolor="#0f172a",
        lw=0,
        label="观测点（颜色=指数）",
    )
    ax.legend(handles=[h_traj, h_pt], loc="upper left", fontsize=9, framealpha=0.9)

    fig.tight_layout()
    out = __file__.replace(".py", ".png")
    plt.savefig(out, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    main()
