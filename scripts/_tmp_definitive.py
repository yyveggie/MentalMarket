#!/usr/bin/env python3
"""
最终定稿版：三实验平均收益率 & 交易次数
数据源：trades.jsonl（去重）+ agents_final.jsonl（去重取最后一条）
每一步都打印中间结果以供审计。
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

results = []

for label, run_dir in runs:
    run_path = Path(run_dir)
    short_label = label.replace("\n", " ")
    print(f"\n{'='*70}")
    print(f"  {short_label}: {run_dir}")
    print(f"{'='*70}")

    # ===== Step 1: trades.jsonl 严格去重，获取最终成交价 =====
    seen_keys = set()
    unique_trades = []
    for line in open(run_path / "trades.jsonl"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        # 去重 key：同一时刻、同一标的、同一对手方、同一价格和数量视为同一笔
        key = (
            r.get("symbol", ""),
            round(r.get("sim_time", 0), 4),
            r.get("buyer_id", -1),
            r.get("seller_id", -1),
            r.get("price", 0),
            r.get("quantity", 0),
        )
        if key not in seen_keys:
            seen_keys.add(key)
            unique_trades.append(r)

    # 每个 symbol 的最终成交价
    last_trade_price = {}
    for t in unique_trades:
        sym = t.get("symbol", "")
        px = t.get("price")
        if sym and px is not None:
            last_trade_price[sym] = float(px)

    print(f"  [Step 1] trades.jsonl 去重后: {len(unique_trades)} 笔唯一交易")
    print(f"  [Step 1] 最终成交价:")
    for sym in sorted(last_trade_price):
        print(f"           {sym} = {last_trade_price[sym]:.2f}")

    # ===== Step 2: 从去重交易统计每个 agent 的交易次数 =====
    agent_tc = defaultdict(int)
    for t in unique_trades:
        buyer = t.get("buyer_id", -1)
        seller = t.get("seller_id", -1)
        if buyer != 0:
            agent_tc[buyer] += 1
        if seller != 0:
            agent_tc[seller] += 1

    # 排除做市商
    real_agents = sorted(aid for aid in agent_tc if aid != 0)
    trade_counts = [agent_tc[aid] for aid in real_agents]
    avg_tc = sum(trade_counts) / len(trade_counts)
    print(f"  [Step 2] 参与交易的 agent: {len(real_agents)} 个")
    print(f"  [Step 2] 人均交易次数: {avg_tc:.1f} (range: {min(trade_counts)}~{max(trade_counts)})")

    # ===== Step 3: agents_final.jsonl 去重（每个 agent 取最后一条）=====
    final_by_id = {}
    total_lines = 0
    for line in open(run_path / "agents_final.jsonl"):
        line = line.strip()
        if not line:
            continue
        total_lines += 1
        r = json.loads(line)
        aid = r.get("agent_id", 0)
        if aid == 0:
            continue
        final_by_id[aid] = r  # 覆盖 → 保留最后一条

    n_agents = len(final_by_id)
    n_batches = total_lines // n_agents if n_agents else 0
    print(f"  [Step 3] agents_final.jsonl: {total_lines} 行, {n_agents} 个唯一 agent, ~{n_batches} 批")

    # ===== Step 4: 用 trades.jsonl 最终成交价重算每个 agent 的收益率 =====
    agent_returns = []
    print(f"  [Step 4] 收益率计算（抽样前5个 agent）:")
    for i, aid in enumerate(sorted(final_by_id)):
        ag = final_by_id[aid]
        cash = float(ag["cash"])
        initial_asset = float(ag.get("initial_asset", 0))
        positions = ag.get("positions", {})

        stock_value = 0.0
        for sym, qty in positions.items():
            q = int(qty)
            if q > 0:
                px = last_trade_price.get(sym, 0)
                stock_value += px * q

        final_wealth = cash + stock_value
        ret = (final_wealth - initial_asset) / initial_asset if initial_asset > 0 else 0.0
        agent_returns.append(ret)

        if i < 5:
            print(f"           Agent {aid}: cash={cash:.0f} + stock={stock_value:.0f} = {final_wealth:.0f}, "
                  f"init={initial_asset:.0f}, return={ret*100:.2f}%")

    avg_ret = sum(agent_returns) / len(agent_returns) * 100
    sorted_rets = sorted(agent_returns)
    median_ret = sorted_rets[len(sorted_rets) // 2] * 100
    positive_count = sum(1 for r in agent_returns if r > 0)

    print(f"  [Step 4] ====> 平均收益率: {avg_ret:.2f}% <====")
    print(f"           中位数: {median_ret:.2f}%, 正收益: {positive_count}/{n_agents}")
    print(f"           min: {sorted_rets[0]*100:.2f}%, max: {sorted_rets[-1]*100:.2f}%")

    results.append({
        "label": label,
        "short_label": short_label,
        "avg_return": avg_ret,
        "avg_trades": avg_tc,
        "trade_counts": trade_counts,
        "agent_returns": agent_returns,
    })

# ===== 汇总 =====
print(f"\n{'='*70}")
print(f"  最终定稿数据")
print(f"{'='*70}")
for r in results:
    print(f"  {r['short_label']:20s}  平均收益率: {r['avg_return']:+8.2f}%  人均交易次数: {r['avg_trades']:.1f}")

# ===== 画图 =====
out = Path("output")
out.mkdir(exist_ok=True)
labels = [r["label"] for r in results]
colors = ["#e74c3c", "#3498db", "#2ecc71"]

# 图 1: 平均交易次数
fig1, ax1 = plt.subplots(figsize=(8, 5.8))
vals1 = [r["avg_trades"] for r in results]
bars1 = ax1.bar(labels, vals1, color=colors, width=0.5, edgecolor="white", linewidth=1.5)
for bar, val in zip(bars1, vals1):
    ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 5,
             f"{val:.0f}", ha="center", va="bottom", fontsize=14, fontweight="bold")
ax1.set_ylabel("人均交易次数", fontsize=13)
ax1.set_title("三实验人均交易次数对比", fontsize=14, fontweight="bold")
ax1.spines["top"].set_visible(False)
ax1.spines["right"].set_visible(False)
ax1.annotate(
    "统计方式：每笔订单簿撮合成交计为一次交易，买方和卖方各计 1 次\n"
    "数据来源：trades.jsonl 严格去重",
    xy=(0.5, -0.13), xycoords="axes fraction",
    ha="center", va="top", fontsize=9, color="grey",
)
plt.tight_layout()
fig1.savefig(out / "三实验平均交易次数对比.png", dpi=200)
fig1.savefig(out / "三实验平均交易次数对比.pdf")

# 图 2: 平均收益率
fig2, ax2 = plt.subplots(figsize=(8, 5.8))
vals2 = [r["avg_return"] for r in results]
bars2 = ax2.bar(labels, vals2, color=colors, width=0.5, edgecolor="white", linewidth=1.5)
for bar, val in zip(bars2, vals2):
    y = bar.get_height()
    ax2.text(bar.get_x() + bar.get_width() / 2, y + (1 if y >= 0 else -2),
             f"{val:.2f}%", ha="center", va="bottom" if y >= 0 else "top",
             fontsize=14, fontweight="bold")
ax2.axhline(y=0, color="grey", linewidth=0.8, linestyle="--")
ax2.set_ylabel("平均收益率 (%)", fontsize=13)
ax2.set_title("三实验平均收益率对比", fontsize=14, fontweight="bold")
ax2.set_ylim(min(vals2) - 8, max(vals2) + 8)
ax2.spines["top"].set_visible(False)
ax2.spines["right"].set_visible(False)
ax2.annotate(
    "收益率 = (最终财富 − 初始资产) / 初始资产\n"
    "最终财富 = 现金 + Σ(持仓量 × trades.jsonl 最终成交价)",
    xy=(0.5, -0.13), xycoords="axes fraction",
    ha="center", va="top", fontsize=9, color="grey",
)
plt.tight_layout()
fig2.savefig(out / "三实验平均收益率对比.png", dpi=200)
fig2.savefig(out / "三实验平均收益率对比.pdf")

# 图 3: 交易次数分布
fig3, ax3 = plt.subplots(figsize=(9, 6))
all_tc = [r["trade_counts"] for r in results]
bp = ax3.boxplot(all_tc, positions=[0, 1, 2], widths=0.4,
                 patch_artist=True, showfliers=False,
                 medianprops=dict(color="black", linewidth=2))
for patch, c in zip(bp["boxes"], colors):
    patch.set_facecolor(c)
    patch.set_alpha(0.6)
rng = np.random.default_rng(42)
for i, (tc, c) in enumerate(zip(all_tc, colors)):
    jitter = rng.uniform(-0.12, 0.12, len(tc))
    ax3.scatter(np.full(len(tc), i) + jitter, tc, color=c, alpha=0.35, s=18, edgecolors="none", zorder=3)
ax3.set_xticks([0, 1, 2])
ax3.set_xticklabels([r["short_label"] for r in results], fontsize=12)
ax3.set_ylabel("交易次数", fontsize=13)
ax3.set_title("三实验智能体交易次数分布", fontsize=14, fontweight="bold")
ax3.spines["top"].set_visible(False)
ax3.spines["right"].set_visible(False)
ax3.annotate(
    "统计方式：每笔订单簿撮合成交计为一次交易，买方和卖方各计 1 次\n"
    "图示：箱线图 + 个体散点（100 agents/组）",
    xy=(0.5, -0.10), xycoords="axes fraction",
    ha="center", va="top", fontsize=9, color="grey",
)
plt.tight_layout()
fig3.savefig(out / "三实验交易次数分布.png", dpi=200)
fig3.savefig(out / "三实验交易次数分布.pdf")

print(f"\n已保存 6 个文件到 output/")
