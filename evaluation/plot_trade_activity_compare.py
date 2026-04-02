#!/usr/bin/env python3
"""三个实验的平均每智能体交易次数对比图。"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics_plot_common import configure_chinese_font, ensure_output_dir

configure_chinese_font()

runs = {
    "tom0": "runs/20260322_132820_tom0",
    "tom1": "runs/20260322_231352_tom1",
    "tom2": "runs/20260323_213251_tom2",
}

out_dir = ensure_output_dir(Path("."), None)

stats = {}
for label, run_path in runs.items():
    trades_path = Path(run_path) / "trades.jsonl"
    agent_trades = defaultdict(int)
    total_trades = 0
    with open(trades_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            t = json.loads(line)
            if t.get("is_seed_trade"):
                continue
            buyer = t.get("buyer_id")
            seller = t.get("seller_id")
            total_trades += 1
            if buyer is not None:
                agent_trades[buyer] += 1
            if seller is not None:
                agent_trades[seller] += 1

    n_agents = len(agent_trades)
    counts = list(agent_trades.values())
    avg_per_agent = sum(counts) / n_agents if n_agents else 0
    median_per_agent = sorted(counts)[len(counts) // 2] if counts else 0
    max_per_agent = max(counts) if counts else 0
    min_per_agent = min(counts) if counts else 0

    stats[label] = {
        "total_trades": total_trades,
        "n_agents": n_agents,
        "avg": avg_per_agent,
        "median": median_per_agent,
        "max": max_per_agent,
        "min": min_per_agent,
        "counts": counts,
    }
    print(f"{label.replace(chr(10), ' ')}: {total_trades} trades, {n_agents} agents, "
          f"avg={avg_per_agent:.1f}, median={median_per_agent}, range=[{min_per_agent}, {max_per_agent}]")

# ── 柱状图：总交易数 + 平均每人交易数 ──
labels = list(stats.keys())
colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]

fig, axes = plt.subplots(1, 3, figsize=(15, 5), dpi=140)

# 1) 总交易数
vals = [stats[l]["total_trades"] for l in labels]
bars = axes[0].bar(range(len(labels)), vals, color=colors, width=0.6)
axes[0].set_xticks(range(len(labels)))
axes[0].set_xticklabels(labels, fontsize=9)
axes[0].set_title("总交易笔数（不含种子）", fontsize=12)
for b, v in zip(bars, vals):
    axes[0].text(b.get_x() + b.get_width() / 2, b.get_height(), str(v),
                 ha="center", va="bottom", fontsize=10)

# 2) 平均每智能体交易次数
vals = [stats[l]["avg"] for l in labels]
bars = axes[1].bar(range(len(labels)), vals, color=colors, width=0.6)
axes[1].set_xticks(range(len(labels)))
axes[1].set_xticklabels(labels, fontsize=9)
axes[1].set_title("平均每智能体交易次数", fontsize=12)
for b, v in zip(bars, vals):
    axes[1].text(b.get_x() + b.get_width() / 2, b.get_height(), f"{v:.1f}",
                 ha="center", va="bottom", fontsize=10)

# 3) 箱线图：分布
box_data = [stats[l]["counts"] for l in labels]
bp = axes[2].boxplot(box_data, labels=[l.replace("\n", " ") for l in labels],
                     patch_artist=True, widths=0.5)
for patch, color in zip(bp["boxes"], colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.5)
axes[2].set_title("每智能体交易次数分布", fontsize=12)
axes[2].set_ylabel("交易次数")

fig.suptitle("三实验智能体交易活跃度对比", fontsize=14, y=1.02)
fig.tight_layout()
p = out_dir / "三实验交易活跃度对比.png"
fig.savefig(str(p), bbox_inches="tight")
fig.savefig(str(p.with_suffix(".pdf")), bbox_inches="tight")
plt.close(fig)
print(f"\n保存: {p}")
