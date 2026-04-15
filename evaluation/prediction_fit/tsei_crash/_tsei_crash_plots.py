#!/usr/bin/env python3
"""TSEI 崩盘叙事配图：
  图A — TSEI 价格 vs 基本面三实验对比
  图B — 10 指数日收益率热力图 (ToM06)，标注全市场同步下跌日
"""
import json, math, sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from metrics_plot_common import read_jsonl, safe_int, configure_chinese_font

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

configure_chinese_font()

base = Path(__file__).resolve().parent.parent.parent.parent
experiments = {
    'ToM01 (33/33/33)': base / 'runs' / 'ToM01_ToM11_ToM21_预测拟合',
    'ToM06 (60/10/30)': base / 'runs' / 'ToM06_ToM13_ToM21_预测拟合',
    'ToM07 (70/10/20)': base / 'runs' / 'ToM07_ToM12_ToM21_预测拟合',
}

SYMBOLS = ['CGEI','CPEI','EREI','FSEI','IEEI','MEI','REEI','TLEI','TSEI','TTEI']

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

# ═══════════════════════════════════════════════════
# 图 A: TSEI — 三实验 价格 vs 基本面
# ═══════════════════════════════════════════════════
fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
fig.suptitle('TSEI 价格 vs 基本面：三种 ToM 配比下的定价扭曲',
             fontsize=16, fontweight='bold')

from metric_emh import _hurst_rs, _variance_ratio

for idx, (exp_label, run_dir) in enumerate(experiments.items()):
    ax = axes[idx]
    dd = load_sym(run_dir, 'TSEI')
    days = sorted(dd.keys())
    prices = [dd[d]['price'] for d in days]
    fvs = [dd[d]['fair_value'] for d in days]
    devs = [dd[d]['dev_pct'] for d in days]

    ax.plot(days, prices, color='#2196F3', linewidth=2, label='市场价格', zorder=3)
    ax.plot(days, fvs, color='#FF5722', linewidth=2, linestyle='--', label='基本面 (Fair Value)', zorder=3)

    # 填充偏离区域
    for i in range(len(days)-1):
        color = 'green' if prices[i] >= fvs[i] else 'red'
        ax.fill_between([days[i], days[i+1]], [prices[i], prices[i+1]], [fvs[i], fvs[i+1]],
                        alpha=0.15, color=color)

    # 右轴: 偏离度
    ax2 = ax.twinx()
    ax2.bar(days, devs, alpha=0.25, color=['green' if d >= 0 else 'red' for d in devs], width=0.8, zorder=1)
    ax2.set_ylabel('价格偏离 (%)', fontsize=11)
    ax2.axhline(y=0, color='gray', linewidth=0.5, linestyle=':')

    # 统计量
    r_list = []
    for i in range(1, len(days)):
        p0, p1 = dd[days[i-1]]['price'], dd[days[i]]['price']
        if p0 > 0 and p1 > 0: r_list.append(math.log(p1/p0))
    H = _hurst_rs(r_list)
    vr10 = _variance_ratio(r_list, 10)
    avg_dev = sum(devs)/len(devs)

    label_type = {0: '均值回复', 1: '协调失败', 2: '趋势持续'}
    ax.set_title(f'{exp_label}  |  H={H:.3f}  VR(10)={vr10:.3f}  avg RD={avg_dev:+.1f}%  [{label_type[idx]}]',
                fontsize=13, fontweight='bold')
    ax.set_ylabel('价格', fontsize=11)
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

axes[-1].set_xlabel('交易日', fontsize=12)
plt.tight_layout()
outA = Path(__file__).resolve().parent / 'TSEI_价格vs基本面_三实验对比.png'
plt.savefig(outA, dpi=200, bbox_inches='tight')
print(f"Saved: {outA}")
plt.close()

# ═══════════════════════════════════════════════════
# 图 B: 10 指数日收益率热力图 — ToM06
# ═══════════════════════════════════════════════════
run06 = experiments['ToM06 (60/10/30)']

# 1) Load all 10 indices price series
sym_data = {}
for sym in SYMBOLS:
    dd = load_sym(run06, sym)
    sym_data[sym] = dd

# 2) 计算收益率矩阵
all_days = sorted(set().union(*(sym_data[s].keys() for s in SYMBOLS)))
all_days = [d for d in all_days if d >= 2]  # 需要前一天

ret_matrix = np.full((len(SYMBOLS), len(all_days)), np.nan)
for si, sym in enumerate(SYMBOLS):
    dd = sym_data[sym]
    for di, day in enumerate(all_days):
        prev_day = day - 1
        if prev_day in dd and day in dd:
            p0 = dd[prev_day]['price']
            p1 = dd[day]['price']
            if p0 and p0 > 0 and p1 and p1 > 0:
                ret_matrix[si, di] = (p1/p0 - 1) * 100  # percent

# 3) 找同步下跌日 (所有 10 支都下跌)
sync_down_days = []
for di, day in enumerate(all_days):
    col = ret_matrix[:, di]
    if np.all(~np.isnan(col)) and np.all(col < 0):
        sync_down_days.append((di, day))

print(f'同步下跌日数: {len(sync_down_days)}')
for di, day in sync_down_days:
    print(f'  Day {day}: avg return = {np.nanmean(ret_matrix[:, di]):.2f}%')

# 4) 画热力图
fig2, ax = plt.subplots(figsize=(18, 5))

# Clip for better color contrast
vmax = min(8, np.nanmax(np.abs(ret_matrix)))
cmap = plt.cm.RdYlGn  # Red=negative, Green=positive
im = ax.imshow(ret_matrix, aspect='auto', cmap=cmap, vmin=-vmax, vmax=vmax,
               interpolation='nearest')

ax.set_yticks(range(len(SYMBOLS)))
ax.set_yticklabels(SYMBOLS, fontsize=11)

# X-ticks: every 5 days
tick_positions = list(range(0, len(all_days), 5))
ax.set_xticks(tick_positions)
ax.set_xticklabels([str(all_days[i]) for i in tick_positions], fontsize=9)
ax.set_xlabel('交易日', fontsize=12)

# 标注同步下跌日
for di, day in sync_down_days:
    ax.axvline(x=di, color='black', linewidth=2, linestyle='--', alpha=0.8)
    ax.annotate(f'全市场同步下跌\nDay {day}',
               xy=(di, -0.5), xytext=(di+2, -1.8),
               fontsize=9, fontweight='bold', color='black',
               arrowprops=dict(arrowstyle='->', color='black', lw=1.5),
               annotation_clip=False)

cbar = plt.colorbar(im, ax=ax, pad=0.01, shrink=0.9)
cbar.set_label('日收益率 (%)', fontsize=11)

ax.set_title('ToM06 (60/10/30)：10 支指数日收益率热力图\n'
             '黑色虚线标注全市场同步下跌日',
             fontsize=14, fontweight='bold')

plt.tight_layout()
outB = Path(__file__).resolve().parent / 'ToM06_10指数日收益率热力图.png'
plt.savefig(outB, dpi=200, bbox_inches='tight')
print(f"Saved: {outB}")
plt.close()
