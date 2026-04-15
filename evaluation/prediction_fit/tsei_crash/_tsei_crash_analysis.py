#!/usr/bin/env python3
"""TSEI-ToM06 系统性低估/崩盘深度分析。"""
import json, math, sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from metrics_plot_common import read_jsonl, safe_int

SYMBOLS = ['CGEI','CPEI','EREI','FSEI','IEEI','MEI','REEI','TLEI','TSEI','TTEI']

def load_sym_data(run_dir, target_sym):
    snap_path = run_dir / 'market_snapshots.jsonl'
    sym_days = {}
    for r in read_jsonl(snap_path):
        if r.get('symbol') != target_sym: continue
        day = safe_int(r.get('trading_day'))
        if day is None: continue
        sym_days[day] = {
            'price': r.get('last_price'),
            'dev_pct': r.get('price_deviation_pct', 0),
            'volume': r.get('volume', 0),
            'buy_vol': r.get('buy_volume', 0),
            'sell_vol': r.get('sell_volume', 0),
            'trade_count': r.get('trade_count', 0),
            'buy_sell_ratio': r.get('buy_sell_ratio', 0),
            'volatility': r.get('volatility'),
        }
    return sym_days

def _f(v, fmt):
    if v is None: return "N/A".rjust(8)
    return f"{v:{fmt}}"

base = Path(__file__).resolve().parent.parent.parent.parent
experiments = {
    'ToM01': base / 'runs' / 'ToM01_ToM11_ToM21_预测拟合',
    'ToM06': base / 'runs' / 'ToM06_ToM13_ToM21_预测拟合',
    'ToM07': base / 'runs' / 'ToM07_ToM12_ToM21_预测拟合',
}

# ═══════════════════════════════════════════════════
# Part 1: TSEI-ToM06 逐日数据
# ═══════════════════════════════════════════════════
tsei06 = load_sym_data(experiments['ToM06'], 'TSEI')
sorted_days = sorted(tsei06.keys())
print("="*80)
print("TSEI-ToM06 逐日关键数据")
print(f"{'Day':>4} {'Price':>8} {'Dev%':>7} {'Volume':>8} {'BuyVol':>8} {'SellVol':>8} {'B/S':>8} {'Trades':>6}")
print('-'*65)
for d in sorted_days[:10]:
    r = tsei06[d]
    print(f"{d:>4} {_f(r['price'],'8.3f')} {_f(r['dev_pct'],'+7.2f')} {_f(r['volume'],'8')} {_f(r['buy_vol'],'8')} {_f(r['sell_vol'],'8')} {_f(r['buy_sell_ratio'],'8.3f')} {_f(r['trade_count'],'6')}")
print("  ... (中间采样) ...")
for d in sorted_days[10::10]:
    r = tsei06[d]
    print(f"{d:>4} {_f(r['price'],'8.3f')} {_f(r['dev_pct'],'+7.2f')} {_f(r['volume'],'8')} {_f(r['buy_vol'],'8')} {_f(r['sell_vol'],'8')} {_f(r['buy_sell_ratio'],'8.3f')} {_f(r['trade_count'],'6')}")
print("  ... (最后10日) ...")
for d in sorted_days[-10:]:
    r = tsei06[d]
    print(f"{d:>4} {_f(r['price'],'8.3f')} {_f(r['dev_pct'],'+7.2f')} {_f(r['volume'],'8')} {_f(r['buy_vol'],'8')} {_f(r['sell_vol'],'8')} {_f(r['buy_sell_ratio'],'8.3f')} {_f(r['trade_count'],'6')}")

# ═══════════════════════════════════════════════════
# Part 2: 价格阶段分析
# ═══════════════════════════════════════════════════
p0 = tsei06[sorted_days[0]]['price']
pN = tsei06[sorted_days[-1]]['price']
cum = math.log(pN/p0)*100

# 找最低价和最大偏离
min_price_day = min(sorted_days, key=lambda d: tsei06[d]['price'])
max_dev_neg_day = min(sorted_days, key=lambda d: tsei06[d]['dev_pct'])
max_price_day = max(sorted_days, key=lambda d: tsei06[d]['price'])

# 最大回撤
peak = 0; peak_day = sorted_days[0]
max_dd = 0; dd_peak = 0; dd_trough = 0
for d in sorted_days:
    p = tsei06[d]['price']
    if p > peak:
        peak = p; peak_day = d
    dd = (p - peak) / peak * 100
    if dd < max_dd:
        max_dd = dd; dd_peak = peak_day; dd_trough = d

print("\n" + "="*80)
print("TSEI-ToM06 价格阶段分析")
print(f"  初始价: {p0:.4f}")
print(f"  终点价: {pN:.4f} (cum_ret={cum:+.1f}%)")
print(f"  最高价 day{max_price_day}: {tsei06[max_price_day]['price']:.4f}")
print(f"  最低价 day{min_price_day}: {tsei06[min_price_day]['price']:.4f} (dev={tsei06[min_price_day]['dev_pct']:+.2f}%)")
print(f"  最大负偏离 day{max_dev_neg_day}: dev={tsei06[max_dev_neg_day]['dev_pct']:+.2f}%")
print(f"  最大回撤: day{dd_peak}→day{dd_trough}, drawdown={max_dd:+.1f}%")

# ═══════════════════════════════════════════════════
# Part 3: 分阶段统计
# ═══════════════════════════════════════════════════
phases = [
    ("前期 day1-25", 1, 25),
    ("中前期 day26-50", 26, 50),
    ("中后期 day51-75", 51, 75),
    ("后期 day76-99", 76, 99),
]
print("\n" + "="*80)
print("TSEI-ToM06 分阶段买卖力量分析")
for label, d0, d1 in phases:
    subset = [(d, tsei06[d]) for d in sorted_days if d0 <= d <= d1]
    if not subset: continue
    n = len(subset)
    avg_price = sum(r['price'] for _,r in subset)/n
    avg_dev = sum(r['dev_pct'] for _,r in subset)/n
    avg_vol = sum(r['volume'] for _,r in subset)/n
    avg_bsr = sum(r['buy_sell_ratio'] for _,r in subset)/n
    sell_dom = sum(1 for _,r in subset if r['buy_sell_ratio'] < 1.0 and r['volume'] > 0)
    prices_only = [r['price'] for _,r in subset]
    period_ret = math.log(prices_only[-1]/prices_only[0])*100 if len(prices_only)>1 and prices_only[0]>0 else 0
    print(f"  {label}: avg_price={avg_price:.3f}, avg_dev={avg_dev:+.1f}%, avg_vol={avg_vol:.0f}, avg_B/S={avg_bsr:.3f}, sell_dom_days={sell_dom}/{n}, period_ret={period_ret:+.1f}%")

# ═══════════════════════════════════════════════════
# Part 4: TSEI 单指数 GSADF (检测崩盘)
# ═══════════════════════════════════════════════════
print("\n" + "="*80)
print("TSEI-ToM06 单指数 GSADF 崩盘检验")
prices = [tsei06[d]['price'] for d in sorted_days]
T = len(prices)
log_prices = [math.log(p) for p in prices]
min_win = max(15, int(T * (0.01 + 1.8/T**0.5)))

def cv95(T):
    if T<=50: return 1.68
    elif T<=100: return 1.68-(T-50)/50*(1.68-1.49)
    else: return 1.49

cv = cv95(T)

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

max_bsadf = -999
crash_days = []
for idx in range(len(sorted_days)):
    day = sorted_days[idx]
    if idx+1 < min_win: continue
    max_stat = None
    best_r1 = None
    for r1 in range(0, idx-min_win+2):
        seg = log_prices[r1:idx+1]
        stat = ols_adf(seg)
        if stat is not None and (max_stat is None or stat > max_stat):
            max_stat = stat
            best_r1 = r1
    if max_stat is not None:
        if max_stat > max_bsadf: max_bsadf = max_stat
        if max_stat > cv:
            is_up = log_prices[idx] > log_prices[best_r1]
            label = "BUBBLE" if is_up else "CRASH"
            if not is_up:
                crash_days.append(day)
            print(f"  *** {label} day {day}: BSADF={max_stat:.4f}, price={tsei06[day]['price']:.4f}, dev={tsei06[day]['dev_pct']:+.2f}%")

if not crash_days and max_bsadf < cv:
    print(f"  未检测到显著爆发性行为. 最大 BSADF = {max_bsadf:.4f} (需 > {cv:.4f})")
print(f"  崩盘天数: {len(crash_days)}")

# ═══════════════════════════════════════════════════
# Part 5: TSEI 三实验对比
# ═══════════════════════════════════════════════════
print("\n" + "="*80)
print("TSEI 三实验全面对比")
for exp_label, rd in [
    ('ToM01 (33-33-33)', experiments['ToM01']),
    ('ToM06 (60-10-30)', experiments['ToM06']),
    ('ToM07 (70-10-20)', experiments['ToM07']),
]:
    dd = load_sym_data(rd, 'TSEI')
    sdays = sorted(dd.keys())
    if len(sdays) < 2: continue
    p0_ = dd[sdays[0]]['price']
    pN_ = dd[sdays[-1]]['price']
    cum_ = math.log(pN_/p0_)*100
    devs = [dd[d]['dev_pct'] for d in sdays]
    avg_dev = sum(devs)/len(devs)
    max_dev = max(devs)
    min_dev = min(devs)
    vols = [dd[d]['volume'] for d in sdays]
    avg_vol = sum(vols)/len(vols)
    bsr = [dd[d]['buy_sell_ratio'] for d in sdays]
    avg_bsr = sum(bsr)/len(bsr)
    sell_dom = sum(1 for d in sdays if dd[d]['buy_sell_ratio'] < 1.0 and dd[d]['volume'] > 0)
    
    # Hurst & VR
    rets = []
    for i in range(1, len(sdays)):
        d0_, d1_ = sdays[i-1], sdays[i]
        pp0, pp1 = dd[d0_]['price'], dd[d1_]['price']
        if pp0 > 0 and pp1 > 0:
            rets.append(math.log(pp1/pp0))
    
    from metric_emh import _hurst_rs, _variance_ratio, _runs_test
    H = _hurst_rs(rets)
    vr10 = _variance_ratio(rets, 10)
    rt = _runs_test(rets)
    
    print(f"  {exp_label}:")
    print(f"    cum_ret={cum_:+.1f}%, avg_dev={avg_dev:+.1f}%, dev_range=[{min_dev:+.1f}%,{max_dev:+.1f}%]")
    print(f"    avg_vol={avg_vol:.0f}, avg_B/S={avg_bsr:.3f}, sell_dom_days={sell_dom}/{len(sdays)}")
    print(f"    Hurst={H:.3f}, VR(10)={vr10:.3f}, RunsZ={rt[1]:+.3f}" if H and vr10 and rt else "    (insufficient data)")

# ═══════════════════════════════════════════════════
# Part 6: ToM06 全市场同步下跌验证
# ═══════════════════════════════════════════════════
print("\n" + "="*80)
print("ToM06 全市场同步下跌验证 (10个指数)")
tom06_dir = experiments['ToM06']
all_sym_data = {}
for sym in SYMBOLS:
    sd = load_sym_data(tom06_dir, sym)
    all_sym_data[sym] = sd

for sym in SYMBOLS:
    sd = all_sym_data[sym]
    sdays = sorted(sd.keys())
    if len(sdays) < 2: continue
    p0_ = sd[sdays[0]]['price']
    pN_ = sd[sdays[-1]]['price']
    cum_ = math.log(pN_/p0_)*100
    avg_dev = sum(sd[d]['dev_pct'] for d in sdays)/len(sdays)
    print(f"  {sym}: cum_ret={cum_:+.1f}%, avg_dev={avg_dev:+.1f}%, days={len(sdays)}")

# 计算同步下跌天数
all_days_set = set.intersection(*(set(all_sym_data[s].keys()) for s in SYMBOLS))
all_days_sorted = sorted(all_days_set)
sync_down = 0
for i in range(1, len(all_days_sorted)):
    d0, d1 = all_days_sorted[i-1], all_days_sorted[i]
    all_down = all(all_sym_data[s][d1]['price'] <= all_sym_data[s][d0]['price'] for s in SYMBOLS
                   if d0 in all_sym_data[s] and d1 in all_sym_data[s])
    if all_down: sync_down += 1
print(f"\n  全部10指数同步下跌天数: {sync_down}/{len(all_days_sorted)-1} ({sync_down/(len(all_days_sorted)-1)*100:.1f}%)")

# 同步上涨
sync_up = 0
for i in range(1, len(all_days_sorted)):
    d0, d1 = all_days_sorted[i-1], all_days_sorted[i]
    all_up = all(all_sym_data[s][d1]['price'] >= all_sym_data[s][d0]['price'] for s in SYMBOLS
                 if d0 in all_sym_data[s] and d1 in all_sym_data[s])
    if all_up: sync_up += 1
print(f"  全部10指数同步上涨天数: {sync_up}/{len(all_days_sorted)-1} ({sync_up/(len(all_days_sorted)-1)*100:.1f}%)")

# 对比其他实验
for exp_label, rd in [('ToM01', experiments['ToM01']), ('ToM07', experiments['ToM07'])]:
    all_sd = {sym: load_sym_data(rd, sym) for sym in SYMBOLS}
    ad_set = set.intersection(*(set(all_sd[s].keys()) for s in SYMBOLS))
    ad_sorted = sorted(ad_set)
    sd_cnt = 0; su_cnt = 0
    for i in range(1, len(ad_sorted)):
        d0, d1 = ad_sorted[i-1], ad_sorted[i]
        if all(all_sd[s][d1]['price'] <= all_sd[s][d0]['price'] for s in SYMBOLS if d0 in all_sd[s] and d1 in all_sd[s]):
            sd_cnt += 1
        if all(all_sd[s][d1]['price'] >= all_sd[s][d0]['price'] for s in SYMBOLS if d0 in all_sd[s] and d1 in all_sd[s]):
            su_cnt += 1
    n_ = len(ad_sorted)-1
    print(f"  {exp_label}: sync_down={sd_cnt}/{n_} ({sd_cnt/n_*100:.1f}%), sync_up={su_cnt}/{n_} ({su_cnt/n_*100:.1f}%)")
