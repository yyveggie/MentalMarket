#!/usr/bin/env python3
"""IEEI-ToM07 泡沫深度分析。"""
import json, math, sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from metrics_plot_common import read_jsonl, safe_int

run_dir = Path(__file__).resolve().parent.parent.parent.parent / 'runs' / 'ToM07_ToM12_ToM21_预测拟合'

# 1. IEEI 逐日数据
snap_path = run_dir / 'market_snapshots.jsonl'
ieei_days = {}
for r in read_jsonl(snap_path):
    if r.get('symbol') != 'IEEI': continue
    day = safe_int(r.get('trading_day'))
    if day is None: continue
    ieei_days[day] = {
        'price': r.get('last_price'),
        'dev_pct': r.get('price_deviation_pct'),
        'volume': r.get('volume'),
        'buy_vol': r.get('buy_volume'),
        'sell_vol': r.get('sell_volume'),
        'trade_count': r.get('trade_count'),
        'buy_sell_ratio': r.get('buy_sell_ratio'),
        'volatility': r.get('volatility'),
    }

sorted_days = sorted(ieei_days.keys())
print("="*80)
print("IEEI-ToM07 逐日关键数据 (前10日 + 中间采样 + 最后20日)")
print(f"{'Day':>4} {'Price':>8} {'Dev%':>7} {'Volume':>8} {'BuyVol':>8} {'SellVol':>8} {'B/S':>6} {'Volatil':>8} {'Trades':>6}")
print('-'*80)
for d in sorted_days[:10]:
    r = ieei_days[d]
    def _f(v, fmt):
        return f"{v:{fmt}}" if v is not None else "N/A".rjust(len(f"{0:{fmt}}"))
    print(f"{d:>4} {_f(r['price'],'8.3f')} {_f(r['dev_pct'],'+7.2f')} {_f(r['volume'],'8')} {_f(r['buy_vol'],'8')} {_f(r['sell_vol'],'8')} {_f(r['buy_sell_ratio'],'6.3f')} {_f(r['volatility'],'8.4f')} {_f(r['trade_count'],'6')}")
print("  ...")
for d in sorted_days[20::10]:
    r = ieei_days[d]
    def _f(v, fmt):
        return f"{v:{fmt}}" if v is not None else "N/A".rjust(len(f"{0:{fmt}}"))
    print(f"{d:>4} {_f(r['price'],'8.3f')} {_f(r['dev_pct'],'+7.2f')} {_f(r['volume'],'8')} {_f(r['buy_vol'],'8')} {_f(r['sell_vol'],'8')} {_f(r['buy_sell_ratio'],'6.3f')} {_f(r['volatility'],'8.4f')} {_f(r['trade_count'],'6')}")
print("  ...")
for d in sorted_days[-20:]:
    r = ieei_days[d]
    def _f(v, fmt):
        return f"{v:{fmt}}" if v is not None else "N/A".rjust(len(f"{0:{fmt}}"))
    print(f"{d:>4} {_f(r['price'],'8.3f')} {_f(r['dev_pct'],'+7.2f')} {_f(r['volume'],'8')} {_f(r['buy_vol'],'8')} {_f(r['sell_vol'],'8')} {_f(r['buy_sell_ratio'],'6.3f')} {_f(r['volatility'],'8.4f')} {_f(r['trade_count'],'6')}")

# 2. 价格阶段分析
first_price = ieei_days[sorted_days[0]]['price']
max_dev_day = max(sorted_days, key=lambda d: ieei_days[d]['dev_pct'])
max_price_day = max(sorted_days, key=lambda d: ieei_days[d]['price'])
min_price_day = min(sorted_days, key=lambda d: ieei_days[d]['price'])
last_price = ieei_days[sorted_days[-1]]['price']
cum_ret = math.log(last_price/first_price)*100

print("\n" + "="*80)
print("IEEI-ToM07 价格阶段分析")
print(f"  初始价格 (day {sorted_days[0]}): {first_price:.4f}")
print(f"  最高价 (day {max_price_day}): {ieei_days[max_price_day]['price']:.4f} (dev={ieei_days[max_price_day]['dev_pct']:+.2f}%)")
print(f"  最低价 (day {min_price_day}): {ieei_days[min_price_day]['price']:.4f} (dev={ieei_days[min_price_day]['dev_pct']:+.2f}%)")
print(f"  最大偏离 (day {max_dev_day}): dev={ieei_days[max_dev_day]['dev_pct']:+.2f}%")
print(f"  终点价格 (day {sorted_days[-1]}): {last_price:.4f} (dev={ieei_days[sorted_days[-1]]['dev_pct']:+.2f}%)")
print(f"  累计收益率: {cum_ret:+.1f}%")

# 找拐点(最大回撤起点)
peak_price = 0
peak_day = sorted_days[0]
for d in sorted_days:
    p = ieei_days[d]['price']
    if p > peak_price:
        peak_price = p
        peak_day = d
trough_after_peak = min((d for d in sorted_days if d >= peak_day), key=lambda d: ieei_days[d]['price'])
drawdown = (ieei_days[trough_after_peak]['price'] - peak_price) / peak_price * 100
print(f"  最大回撤: peak day{peak_day}→trough day{trough_after_peak}, drawdown={drawdown:+.1f}%")

# 3. 单指数 GSADF
print("\n" + "="*80)
print("IEEI-ToM07 单指数 GSADF 泡沫检验")
prices = [ieei_days[d]['price'] for d in sorted_days]
T = len(prices)
log_prices = [math.log(p) for p in prices]
min_win = max(15, int(T * (0.01 + 1.8/T**0.5)))

def cv95(T):
    if T<=50: return 1.68
    elif T<=100: return 1.68-(T-50)/50*(1.68-1.49)
    elif T<=200: return 1.49-(T-100)/100*(1.49-1.34)
    else: return 1.34

cv = cv95(T)
print(f"  T={T}, min_win={min_win}, cv_95={cv:.4f}")

def ols_adf(y):
    n = len(y)
    if n < 6: return None
    dy = [y[t]-y[t-1] for t in range(1,n)]
    yl = [y[t-1] for t in range(1,n)]
    m = len(dy)
    sx = sum(yl); sx2 = sum(v*v for v in yl)
    sy = sum(dy); sxy = sum(dy[i]*yl[i] for i in range(m))
    denom = m*sx2-sx*sx
    if abs(denom)<1e-30: return None
    beta = (m*sxy-sx*sy)/denom
    alpha = (sy-beta*sx)/m
    resid = [dy[i]-alpha-beta*yl[i] for i in range(m)]
    sse = sum(e*e for e in resid)
    s2 = sse/max(1,m-2)
    se2 = s2*m/denom
    if se2<=0: return None
    return beta/se2**0.5

bsadf_series = []
bubble_days = []
for idx in range(len(sorted_days)):
    day = sorted_days[idx]
    if idx+1 < min_win:
        bsadf_series.append((day, None))
        continue
    max_stat = None
    best_r1 = None
    for r1 in range(0, idx-min_win+2):
        seg = log_prices[r1:idx+1]
        stat = ols_adf(seg)
        if stat is not None and (max_stat is None or stat > max_stat):
            max_stat = stat
            best_r1 = r1
    bsadf_series.append((day, max_stat))
    if max_stat is not None and max_stat > cv:
        is_up = log_prices[idx] > log_prices[best_r1]
        label = "BUBBLE" if is_up else "CRASH"
        if is_up:
            bubble_days.append(day)
        print(f"  *** {label} day {day}: BSADF={max_stat:.4f} > cv={cv:.4f}, price={ieei_days[day]['price']:.4f}, dev={ieei_days[day]['dev_pct']:+.2f}%")

if not bubble_days:
    max_bsadf_val = max((s for _, s in bsadf_series if s is not None), default=0)
    print(f"  未检测到显著泡沫日. 最大 BSADF = {max_bsadf_val:.4f} (需 > {cv:.4f})")

print(f"\n  统计显著泡沫天数: {len(bubble_days)}")

# 4. 买卖力量分阶段统计
print("\n" + "="*80)
print("IEEI-ToM07 买卖力量阶段分析")
phases = [
    ("前期 day1-30", 1, 30),
    ("中期 day31-60", 31, 60),
    ("后期 day61-99", 61, 99),
]
for label, d0, d1 in phases:
    subset = [ieei_days[d] for d in sorted_days if d0 <= d <= d1]
    if not subset: continue
    avg_bsr = sum(r['buy_sell_ratio'] for r in subset)/len(subset)
    avg_vol = sum(r['volume'] for r in subset)/len(subset)
    avg_dev = sum(r['dev_pct'] for r in subset)/len(subset)
    avg_price = sum(r['price'] for r in subset)/len(subset)
    cum = math.log(subset[-1]['price']/subset[0]['price'])*100 if len(subset)>1 else 0
    print(f"  {label}: avg_price={avg_price:.3f}, avg_dev={avg_dev:+.1f}%, avg_B/S={avg_bsr:.3f}, avg_vol={avg_vol:.0f}, period_ret={cum:+.1f}%")

# 5. 三实验对比
print("\n" + "="*80)
print("IEEI 三实验全面对比")
for exp_label, rd in [
    ('ToM01 (33-33-33)', Path(__file__).resolve().parent.parent.parent.parent / 'runs' / 'ToM01_ToM11_ToM21_预测拟合'),
    ('ToM06 (60-10-30)', Path(__file__).resolve().parent.parent.parent.parent / 'runs' / 'ToM06_ToM13_ToM21_预测拟合'),
    ('ToM07 (70-10-20)', Path(__file__).resolve().parent.parent.parent.parent / 'runs' / 'ToM07_ToM12_ToM21_预测拟合'),
]:
    sp = rd / 'market_snapshots.jsonl'
    dd = {}
    for r in read_jsonl(sp):
        if r.get('symbol')!='IEEI': continue
        day = safe_int(r.get('trading_day'))
        if day: dd[day] = r
    sdays = sorted(dd.keys())
    if len(sdays) < 2: continue
    p0 = dd[sdays[0]]['last_price']
    pN = dd[sdays[-1]]['last_price']
    cum = math.log(pN/p0)*100
    devs = [dd[d]['price_deviation_pct'] for d in sdays]
    avg_dev = sum(devs)/len(devs)
    max_dev = max(devs)
    min_dev = min(devs)
    vols = [dd[d].get('volume',0) for d in sdays]
    avg_vol = sum(vols)/len(vols)
    bsr = [dd[d].get('buy_sell_ratio',0) for d in sdays]
    avg_bsr = sum(bsr)/len(bsr)
    trades = [dd[d].get('trade_count',0) for d in sdays]
    avg_trades = sum(trades)/len(trades)
    
    # 买方主导天数 (B/S > 1)
    buy_dom_days = sum(1 for d in sdays if dd[d].get('buy_sell_ratio',0) > 1.0)
    
    print(f"  {exp_label}:")
    print(f"    cum_ret={cum:+.1f}%, avg_dev={avg_dev:+.1f}%, dev_range=[{min_dev:+.1f}%,{max_dev:+.1f}%]")
    print(f"    avg_vol={avg_vol:.0f}, avg_B/S={avg_bsr:.3f}, avg_trades={avg_trades:.1f}")
    print(f"    买方主导天数(B/S>1): {buy_dom_days}/{len(sdays)} ({buy_dom_days/len(sdays)*100:.0f}%)")
