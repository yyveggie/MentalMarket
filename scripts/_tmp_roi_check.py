#!/usr/bin/env python3
"""
画三实验 ROI（投资回报率）对比图。
ROI = (最终财富 - 初始资产) / 初始资产
最终财富 = 现金 + Σ(持仓×trades.jsonl最终成交价)
"""
import json
from pathlib import Path
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update({
    "font.sans-serif": ["PingFang SC", "Heiti TC", "SimHei", "Arial Unicode MS"],
    "axes.unicode_minus": False,
})

runs = [
    ("ToM-0\n(纯散户)", "runs/20260322_132820_tom0"),
    ("ToM-1\n(纯一阶)", "runs/20260322_231352_tom1"),
    ("ToM-2\n(纯二阶)", "runs/20260323_213251_tom2"),
]

all_rois = []
labels = []

for label, run_dir in runs:
    run_path = Path(run_dir)

    # trades.jsonl 最终成交价
    last_prices = {}
    for line in open(run_path / "trades.jsonl"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        sym = r.get("symbol", "")
        px = r.get("price")
        if sym and px is not None:
            last_prices[sym] = float(px)

    # agents_final 去重
    final_by_id = {}
    for line in open(run_path / "agents_final.jsonl"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        aid = r.get("agent_id", 0)
        if aid == 0:
            continue
        final_by_id[aid] = r

    # 修正后的 ROI
    rois = []
    for aid in sorted(final_by_id):
        ag = final_by_id[aid]
        cash = float(ag["cash"])
        init = float(ag.get("initial_asset", 0))
        positions = ag.get("positions", {})
        wealth = cash + sum(last_prices.get(s, 0) * int(q) for s, q in positions.items() if int(q) > 0)
        roi = (wealth - init) / init if init > 0 else 0.0
        rois.append(roi * 100)

    all_rois.append(rois)
    labels.append(label)
    avg = sum(rois) / len(rois)
    print(f"{label.replace(chr(10),' ')}: avg_ROI={avg:.2f}%, n={len(rois)}")

out = Path("output")
out.mkdir(exist_ok=True)
colors = ["#e74c3c", "#3498db", "#2ecc71"]

# ===== ROI 对比图：箱线图 + 散点 + 平均值标注 =====
fig, ax = plt.subplots(figsize=(9, 6.5))

bp = ax.boxplot(all_rois, positions=[0, 1, 2], widths=0.45,
                patch_artist=True, showfliers=False,
                medianprops=dict(color="black", linewidth=2))
for patch, c in zip(bp["boxes"], colors):
    patch.set_facecolor(c)
    patch.set_alpha(0.55)

rng = np.random.default_rng(42)
for i, (rois, c) in enumerate(zip(all_rois, colors)):
    jitter = rng.uniform(-0.13, 0.13, len(rois))
    ax.scatter(np.full(len(rois), i) + jitter, rois, color=c, alpha=0.4, s=20, edgecolors="none", zorder=3)
    avg = sum(rois) / len(rois)
    # 平均值菱形
    ax.scatter(i, avg, color="black", marker="D", s=60, zorder=5)
    ax.annotate(f"均值 {avg:.2f}%", (i, avg),
                textcoords="offset points", xytext=(30, 5),
                fontsize=11, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="black", lw=1))

ax.axhline(y=0, color="grey", linewidth=0.8, linestyle="--")
ax.set_xticks([0, 1, 2])
ax.set_xticklabels([l.replace("\n", " ") for l in labels], fontsize=12)
ax.set_ylabel("ROI (%)", fontsize=13)
ax.set_title("三实验 ROI（投资回报率）对比", fontsize=14, fontweight="bold")
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.annotate(
    "ROI = (最终财富 − 初始资产) / 初始资产\n"
    "最终财富 = 现金 + Σ(持仓量 × trades.jsonl 最终成交价)  |  ◆ = 均值",
    xy=(0.5, -0.11), xycoords="axes fraction",
    ha="center", va="top", fontsize=9, color="grey",
)
plt.tight_layout()
fig.savefig(out / "三实验ROI对比.png", dpi=200)
fig.savefig(out / "三实验ROI对比.pdf")
print(f"\n已保存: output/三实验ROI对比.png / .pdf")
