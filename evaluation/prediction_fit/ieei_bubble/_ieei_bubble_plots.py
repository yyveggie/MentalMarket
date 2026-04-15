#!/usr/bin/env python3
"""IEEI 泡沫叙事配图：
  图A — IEEI 价格 vs 基本面三实验对比（标注"价量背离"）
  图B — IEEI-ToM07 价格+成交量 双轴图，三阶段标注
"""
import json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from metrics_plot_common import read_jsonl, safe_int, configure_chinese_font

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

configure_chinese_font()

base = Path(__file__).resolve().parent.parent.parent.parent
experiments = {
    'ToM01 (33/33/33)': base / 'runs' / 'ToM01_ToM11_ToM21_预测拟合',
    'ToM06 (60/10/30)': base / 'runs' / 'ToM06_ToM13_ToM21_预测拟合',
    'ToM07 (70/10/20)': base / 'runs' / 'ToM07_ToM12_ToM21_预测拟合',
}

def load_sym(run_dir, sym):
    snap = run_dir / 'market_snapshots.jsonl'
    dd = {}
    for r in read_jsonl(snap):
        if r.get('symbol') != sym: continue
        day = safe_int(r.get('trading_day'))
        if day is None: continue
        price = r.get('last_price')
        dev = r.get('price_deviation_pct', 0)
        vol = r.get('volume', 0)
        bs = r.get('buy_sell_ratio', 1.0)
        if price is not None:
            fv = price / (1 + dev / 100) if abs(1 + dev/100) > 1e-8 else price
            dd[day] = {'price': price, 'dev_pct': dev, 'fair_value': fv,
                       'volume': vol, 'buy_sell_ratio': bs}
    return dd

from metric_emh import _hurst_rs, _variance_ratio

# ═══════════════════════════════════════════════════
# 图 A: IEEI — 三实验 价格 vs 基本面 + 成交量背景
# ═══════════════════════════════════════════════════
fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
fig.suptitle('IEEI 价格 vs 基本面：三种 ToM 配比下的投机性过热',
             fontsize=16, fontweight='bold')

for idx, (exp_label, run_dir) in enumerate(experiments.items()):
    ax = axes[idx]
    dd = load_sym(run_dir, 'IEEI')
    days = sorted(dd.keys())
    prices = [dd[d]['price'] for d in days]
    fvs = [dd[d]['fair_value'] for d in days]
    devs = [dd[d]['dev_pct'] for d in days]

    ax.plot(days, prices, color='#2196F3', linewidth=2, label='市场价格', zorder=3)
    ax.plot(days, fvs, color='#FF5722', linewidth=2, linestyle='--', label='基本面', zorder=3)

    for i in range(len(days)-1):
        color = 'green' if prices[i] >= fvs[i] else 'red'
        ax.fill_between([days[i], days[i+1]], [prices[i], prices[i+1]], [fvs[i], fvs[i+1]],
                        alpha=0.15, color=color)

    ax2 = ax.twinx()
    ax2.bar(days, devs, alpha=0.25, color=['green' if d >= 0 else 'red' for d in devs], width=0.8, zorder=1)
    ax2.set_ylabel('价格偏离 (%)', fontsize=11)
    ax2.axhline(y=0, color='gray', linewidth=0.5, linestyle=':')

    r_list = []
    for i in range(1, len(days)):
        p0, p1 = dd[days[i-1]]['price'], dd[days[i]]['price']
        if p0 > 0 and p1 > 0: r_list.append(math.log(p1/p0))
    H = _hurst_rs(r_list)
    vr10 = _variance_ratio(r_list, 10)
    avg_dev = sum(devs)/len(devs)

    labels = {0: '均值回复', 1: '低估+随机', 2: '投机过热'}
    ax.set_title(f'{exp_label}  |  H={H:.3f}  VR(10)={vr10:.3f}  avg RD={avg_dev:+.1f}%  [{labels[idx]}]',
                fontsize=13, fontweight='bold')
    ax.set_ylabel('价格', fontsize=11)
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

axes[-1].set_xlabel('交易日', fontsize=12)
plt.tight_layout()
outA = Path(__file__).resolve().parent / 'IEEI_价格vs基本面_三实验对比.png'
plt.savefig(outA, dpi=200, bbox_inches='tight')
print(f"Saved: {outA}")
plt.close()

# ═══════════════════════════════════════════════════
# 图 B: IEEI-ToM07 放大 — 价格 + 成交量 + 三阶段标注
# ═══════════════════════════════════════════════════
dd07 = load_sym(experiments['ToM07 (70/10/20)'], 'IEEI')
days = sorted(dd07.keys())
prices = [dd07[d]['price'] for d in days]
fvs = [dd07[d]['fair_value'] for d in days]
vols = [dd07[d]['volume'] for d in days]
devs = [dd07[d]['dev_pct'] for d in days]

fig2, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(16, 9),
                                       gridspec_kw={'height_ratios': [2, 1]},
                                       sharex=True)

# Top: Price + Fair Value
ax_top.plot(days, prices, color='#2196F3', linewidth=2.5, label='市场价格', zorder=4)
ax_top.plot(days, fvs, color='#FF5722', linewidth=2, linestyle='--', label='基本面', zorder=4)
for i in range(len(days)-1):
    color = 'green' if prices[i] >= fvs[i] else 'red'
    ax_top.fill_between([days[i], days[i+1]], [prices[i], prices[i+1]], [fvs[i], fvs[i+1]],
                        alpha=0.12, color=color)

# 三阶段分区
phase_boundaries = [1, 30, 65, days[-1]]
phase_colors = ['#E3F2FD', '#FFF3E0', '#FFEBEE']
phase_labels = ['Phase 1: 放量上涨', 'Phase 2: 缩量整理', 'Phase 3: 极低量加速']
for i in range(3):
    ax_top.axvspan(phase_boundaries[i], phase_boundaries[i+1],
                   alpha=0.08, color=phase_colors[i], zorder=0)
    cx = (phase_boundaries[i] + phase_boundaries[i+1]) / 2
    ax_top.text(cx, max(prices)*0.97, phase_labels[i],
               ha='center', fontsize=10, fontstyle='italic', alpha=0.7)

# 统计框
r_list = []
for i in range(1, len(days)):
    p0, p1 = dd07[days[i-1]]['price'], dd07[days[i]]['price']
    if p0 > 0 and p1 > 0: r_list.append(math.log(p1/p0))
H = _hurst_rs(r_list)
cum_ret = (prices[-1]/prices[0] - 1)*100
textstr = (f'累计涨幅 = +{cum_ret:.1f}%\n'
           f'avg RD = +{np.mean(devs):.1f}%\n'
           f'Hurst H = {H:.3f}\n'
           f'成交量下降 {(1-vols[-1]/max(vols[0], 1))*100:.0f}%')
props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
ax_top.text(0.02, 0.35, textstr, transform=ax_top.transAxes, fontsize=11,
            verticalalignment='top', bbox=props)

ax_top.set_title('IEEI-ToM07 (70/10/20)：投机性过热的三阶段演化\n'
                 '"价格持续上涨 + 成交量持续萎缩" = 经典价量背离',
                 fontsize=14, fontweight='bold')
ax_top.set_ylabel('价格', fontsize=12)
ax_top.legend(loc='upper right', fontsize=11)
ax_top.grid(True, alpha=0.3)

# Bottom: Volume bars
colors = []
for i, d in enumerate(days):
    if i == 0:
        colors.append('#999')
    elif prices[i] >= prices[i-1]:
        colors.append('#26a69a')  # green for up
    else:
        colors.append('#ef5350')  # red for down
ax_bot.bar(days, vols, color=colors, alpha=0.7, width=0.8)

# 成交量 moving average
if len(vols) >= 10:
    ma = np.convolve(vols, np.ones(10)/10, mode='valid')
    ax_bot.plot(days[9:], ma, color='orange', linewidth=2, label='10日均量')
    ax_bot.legend(loc='upper right', fontsize=10)

# 阶段分区
for i in range(3):
    ax_bot.axvspan(phase_boundaries[i], phase_boundaries[i+1],
                   alpha=0.08, color=phase_colors[i], zorder=0)

# 计算各阶段均量
p1_vol = np.mean([dd07[d]['volume'] for d in days if d <= 30])
p2_vol = np.mean([dd07[d]['volume'] for d in days if 30 < d <= 65])
p3_vol = np.mean([dd07[d]['volume'] for d in days if d > 65])
ax_bot.text(15, max(vols)*0.9, f'均量 {p1_vol:,.0f}', ha='center', fontsize=9, color='#1565C0')
ax_bot.text(47.5, max(vols)*0.9, f'均量 {p2_vol:,.0f}', ha='center', fontsize=9, color='#E65100')
ax_bot.text(82.5, max(vols)*0.9, f'均量 {p3_vol:,.0f}', ha='center', fontsize=9, color='#B71C1C')

ax_bot.set_ylabel('成交量', fontsize=12)
ax_bot.set_xlabel('交易日', fontsize=12)
ax_bot.grid(True, alpha=0.3)

plt.tight_layout()
outB = Path(__file__).resolve().parent / 'IEEI_ToM07_投机过热三阶段.png'
plt.savefig(outB, dpi=200, bbox_inches='tight')
print(f"Saved: {outB}")
plt.close()
