#!/usr/bin/env python3
"""三个实验的对比汇总图：柱状图对比 sda/fwd1/fit/R²，以及各指数分指标雷达。"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics_plot_common import configure_chinese_font, ensure_output_dir

configure_chinese_font()

runs = {
    "tom0": "output/拟合度报告_20260322_132820_tom0.json",
    "tom1": "output/拟合度报告_20260322_231352_tom1.json",
    "tom2": "output/拟合度报告_20260323_213251_tom2.json",
}

data = {}
for name, path in runs.items():
    with open(path) as f:
        data[name] = json.load(f)

out_dir = ensure_output_dir(Path("."), None)

# ── 1. 总体指标对比柱状图 ──
metrics = [
    ("same_day_acc", "同日方向准确率 (%)"),
    ("forward1_acc", "前瞻1日准确率 (%)"),
    ("fit_pct", "拟合度 (Pearson×100)"),
    ("r_squared", "R²"),
]

fig, axes = plt.subplots(1, 4, figsize=(16, 4.5), dpi=140)
colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]
names = list(data.keys())

for ax, (key, label) in zip(axes, metrics):
    vals = [data[n]["overall"][key] for n in names]
    bars = ax.bar(range(len(names)), vals, color=colors, width=0.6)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, fontsize=8, rotation=15)
    ax.set_title(label, fontsize=11)
    for bar, v in zip(bars, vals):
        fmt = f"{v:.3f}" if key == "r_squared" else f"{v:.1f}"
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01 * max(vals),
                fmt, ha="center", va="bottom", fontsize=9)
    ax.set_ylim(0, max(vals) * 1.15)

fig.suptitle("三实验总体指标对比", fontsize=14, y=1.02)
fig.tight_layout()
p1 = out_dir / "三实验总体指标对比.png"
fig.savefig(str(p1), bbox_inches="tight")
fig.savefig(str(p1.with_suffix(".pdf")), bbox_inches="tight")
plt.close(fig)
print(f"保存: {p1}")

# ── 2. 各指数 sda/fwd1 对比热力图 ──
symbols = ["CGEI", "CPEI", "EREI", "FSEI", "IEEI", "MEI", "REEI", "TLEI", "TSEI", "TTEI"]

fig, axes = plt.subplots(2, 1, figsize=(14, 8), dpi=140)

for ax_idx, (metric_key, metric_label) in enumerate([
    ("same_day_acc", "同日方向准确率 (%)"),
    ("forward1_acc", "前瞻1日准确率 (%)"),
]):
    ax = axes[ax_idx]
    x = np.arange(len(symbols))
    width = 0.25
    for i, name in enumerate(names):
        per_sym = data[name].get("per_symbol", {})
        vals = []
        for sym in symbols:
            sd = per_sym.get(sym, {})
            vals.append(sd.get(metric_key, 0))
        ax.bar(x + (i - 1) * width, vals, width, label=name, color=colors[i])
    ax.set_xticks(x)
    ax.set_xticklabels(symbols, fontsize=10)
    ax.set_ylabel(metric_label, fontsize=11)
    ax.axhline(50, color="#999", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.axhline(60, color="#d62728", linestyle="--", linewidth=0.8, alpha=0.4)
    ax.set_ylim(20, 75)
    ax.legend(fontsize=9, loc="upper right")
    ax.grid(axis="y", alpha=0.2)

fig.suptitle("三实验各指数准确率对比", fontsize=14)
fig.tight_layout()
p2 = out_dir / "三实验各指数准确率对比.png"
fig.savefig(str(p2), bbox_inches="tight")
fig.savefig(str(p2.with_suffix(".pdf")), bbox_inches="tight")
plt.close(fig)
print(f"保存: {p2}")

# ── 3. 文字汇总 ──
print("\n" + "=" * 60)
print(f"{'指标':<22s}  ", end="")
for n in names:
    print(f"{n:>16s}  ", end="")
print(f"{'平均':>8s}")
print("-" * 90)
for key, label in metrics:
    vals = [data[n]["overall"][key] for n in names]
    avg = sum(vals) / len(vals)
    print(f"{label:<22s}  ", end="")
    for v in vals:
        fmt = f"{v:16.3f}" if key == "r_squared" else f"{v:16.1f}"
        print(f"{fmt}  ", end="")
    afmt = f"{avg:8.3f}" if key == "r_squared" else f"{avg:8.1f}"
    print(afmt)
