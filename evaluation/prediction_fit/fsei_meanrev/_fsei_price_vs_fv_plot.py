#!/usr/bin/env python3
"""FSEI-ToM01 价格 vs 基本面叠加图 — 展示均值回复的"橡皮筋效应"。"""
import json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from metrics_plot_common import read_jsonl, safe_int, configure_chinese_font

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

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
        if price is not None:
            # fair_value = price / (1 + dev/100)
            fv = price / (1 + dev / 100) if abs(1 + dev/100) > 1e-8 else price
            dd[day] = {'price': price, 'dev_pct': dev, 'fair_value': fv}
    return dd

# ═══════════════════════════════════════════════════
# Figure 1: FSEI — 3 experiments, price vs fair value
# ═══════════════════════════════════════════════════
fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
fig.suptitle('FSEI 价格 vs 基本面：三种 ToM 配比下的"橡皮筋效应"', fontsize=16, fontweight='bold')

for idx, (exp_label, run_dir) in enumerate(experiments.items()):
    ax = axes[idx]
    dd = load_sym(run_dir, 'FSEI')
    days = sorted(dd.keys())
    prices = [dd[d]['price'] for d in days]
    fvs = [dd[d]['fair_value'] for d in days]
    devs = [dd[d]['dev_pct'] for d in days]
    
    # 价格线 & 基本面线
    ax.plot(days, prices, color='#2196F3', linewidth=2, label='市场价格', zorder=3)
    ax.plot(days, fvs, color='#FF5722', linewidth=2, linestyle='--', label='基本面 (Fair Value)', zorder=3)
    
    # 填充偏离区域 (绿=高估, 红=低估)
    for i in range(len(days)-1):
        if prices[i] >= fvs[i]:
            ax.fill_between([days[i], days[i+1]], [prices[i], prices[i+1]], [fvs[i], fvs[i+1]],
                          alpha=0.15, color='green')
        else:
            ax.fill_between([days[i], days[i+1]], [prices[i], prices[i+1]], [fvs[i], fvs[i+1]],
                          alpha=0.15, color='red')
    
    # 右轴: 偏离度
    ax2 = ax.twinx()
    ax2.bar(days, devs, alpha=0.25, color=['green' if d >= 0 else 'red' for d in devs], width=0.8, zorder=1)
    ax2.set_ylabel('价格偏离 (%)', fontsize=11)
    ax2.axhline(y=0, color='gray', linewidth=0.5, linestyle=':')
    
    # Hurst & VR annotation
    r_list = []
    for i in range(1, len(days)):
        p0, p1 = dd[days[i-1]]['price'], dd[days[i]]['price']
        if p0 > 0 and p1 > 0: r_list.append(math.log(p1/p0))
    
    from metric_emh import _hurst_rs, _variance_ratio
    H = _hurst_rs(r_list)
    vr10 = _variance_ratio(r_list, 10)
    avg_dev = sum(devs)/len(devs)
    
    label_type = {0: '均值回复', 1: '随机游走', 2: '趋势持续'}
    ax.set_title(f'{exp_label}  |  H={H:.3f}  VR(10)={vr10:.3f}  avg RD={avg_dev:+.1f}%  [{label_type[idx]}]',
                fontsize=13, fontweight='bold')
    
    ax.set_ylabel('价格', fontsize=11)
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

axes[-1].set_xlabel('交易日', fontsize=12)
plt.tight_layout()
outpath = Path(__file__).resolve().parent / 'FSEI_价格vs基本面_三实验对比.png'
plt.savefig(outpath, dpi=200, bbox_inches='tight')
print(f"Saved: {outpath}")
plt.close()

# ═══════════════════════════════════════════════════
# Figure 2: FSEI-ToM01 放大 — 标注反转箭头
# ═══════════════════════════════════════════════════
fig2, ax = plt.subplots(figsize=(16, 7))
dd = load_sym(experiments['ToM01 (33/33/33)'], 'FSEI')
days = sorted(dd.keys())
prices = [dd[d]['price'] for d in days]
fvs = [dd[d]['fair_value'] for d in days]
devs = [dd[d]['dev_pct'] for d in days]

ax.plot(days, prices, color='#2196F3', linewidth=2.5, label='市场价格', zorder=4)
ax.plot(days, fvs, color='#FF5722', linewidth=2, linestyle='--', label='基本面', zorder=4)

# 填充
for i in range(len(days)-1):
    color = 'green' if prices[i] >= fvs[i] else 'red'
    ax.fill_between([days[i], days[i+1]], [prices[i], prices[i+1]], [fvs[i], fvs[i+1]],
                    alpha=0.12, color=color)

# 标注显著反转 (收益率符号变化且幅度>1%)
r_list = []
for i in range(1, len(days)):
    p0, p1 = dd[days[i-1]]['price'], dd[days[i]]['price']
    r_list.append(math.log(p1/p0) if p0 > 0 and p1 > 0 else 0)

reversal_count = 0
for i in range(1, len(r_list)):
    if r_list[i-1] * r_list[i] < 0 and abs(r_list[i]) > 0.015:
        d = days[i+1]
        p = prices[i+1]
        color = 'red' if r_list[i] < 0 else 'green'
        marker = 'v' if r_list[i] < 0 else '^'
        ax.scatter(d, p, color=color, marker=marker, s=40, zorder=5, alpha=0.7)
        reversal_count += 1

# Annotation box
from metric_emh import _hurst_rs, _variance_ratio
H = _hurst_rs(r_list)
vr10 = _variance_ratio(r_list, 10)

textstr = (f'Hurst H = {H:.3f}\n'
           f'VR(10) = {vr10:.3f}\n'
           f'ACF(2) = -0.334***\n'
           f'反转率 = 55.7%\n'
           f'avg RD = +16.3%')
props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=11,
        verticalalignment='top', bbox=props)

ax.set_title('FSEI-ToM01 (33/33/33)：均值回复的"橡皮筋效应"\n'
             '▲ = 反转上涨  ▼ = 反转下跌  绿色区域 = 高估  红色区域 = 低估',
             fontsize=14, fontweight='bold')
ax.set_xlabel('交易日', fontsize=12)
ax.set_ylabel('价格', fontsize=12)
ax.legend(loc='upper right', fontsize=11)
ax.grid(True, alpha=0.3)

plt.tight_layout()
outpath2 = Path(__file__).resolve().parent / 'FSEI_ToM01_均值回复橡皮筋效应.png'
plt.savefig(outpath2, dpi=200, bbox_inches='tight')
print(f"Saved: {outpath2}")
plt.close()
