#!/usr/bin/env python3
"""FSEI-ToM01 均值回复深度分析。"""
import json, math, sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from metrics_plot_common import read_jsonl, safe_int
from metric_emh import _variance_ratio, _hurst_rs, _runs_test

base = Path(__file__).resolve().parent.parent.parent.parent
experiments = {
    'ToM01': base / 'runs' / 'ToM01_ToM11_ToM21_预测拟合',
    'ToM06': base / 'runs' / 'ToM06_ToM13_ToM21_预测拟合',
    'ToM07': base / 'runs' / 'ToM07_ToM12_ToM21_预测拟合',
}
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

# ═══════════════════════════════════════════════════
# Part 1: FSEI-ToM01 逐日数据 + 价格轨迹
# ═══════════════════════════════════════════════════
fsei01 = load_sym_data(experiments['ToM01'], 'FSEI')
sorted_days = sorted(fsei01.keys())
print("="*80)
print("FSEI-ToM01 关键逐日数据（采样）")
print(f"{'Day':>4} {'Price':>8} {'Dev%':>7} {'Volume':>8} {'B/S':>8} {'Trades':>6}")
print('-'*50)
for d in sorted_days[::5]:
    r = fsei01[d]
    print(f"{d:>4} {_f(r['price'],'8.4f')} {_f(r['dev_pct'],'+7.2f')} {_f(r['volume'],'8')} {_f(r['buy_sell_ratio'],'8.3f')} {_f(r['trade_count'],'6')}")

# ═══════════════════════════════════════════════════
# Part 2: 均值回复证据
# ═══════════════════════════════════════════════════
print("\n" + "="*80)
print("FSEI-ToM01 均值回复详细证据")
print()

# 2a. 逐日收益率序列
prices = [fsei01[d]['price'] for d in sorted_days]
days_list = sorted_days
rets = []
for i in range(1, len(prices)):
    if prices[i-1] > 0 and prices[i] > 0:
        rets.append(math.log(prices[i]/prices[i-1]))
    else:
        rets.append(0)
n = len(rets)

# 2b. 完整 ACF lag 1-10
print("收益率自相关 ACF (全样本):")
se = 1.96 / math.sqrt(n)
for lag in range(1, 11):
    m = sum(rets)/n
    var = sum((r-m)**2 for r in rets)
    if var > 1e-15:
        cov = sum((rets[i]-m)*(rets[i+lag]-m) for i in range(n-lag))
        acf = cov/var
    else:
        acf = 0
    sig = " ***" if abs(acf) > se else ""
    bar = "█" * int(abs(acf)*50)
    direction = "+" if acf >= 0 else "-"
    print(f"  lag={lag:2d}: {acf:+.4f} {'|':>6}{direction}{bar}{sig}")
print(f"  95% 置信区间: ±{se:.4f}")

# 2c. VR profile
print("\n方差比 VR(k) profile:")
for k in [2, 3, 5, 7, 10, 15, 20]:
    vr = _variance_ratio(rets, k)
    if vr is not None:
        z = (vr-1)/math.sqrt(2*(2*k-1)*(k-1)/(3*k*n)) if n > k else 0
        sig = " ***" if abs(z) > 1.96 else ""
        bar_len = int(abs(vr-1)*25)
        direction = ">" if vr >= 1 else "<"
        print(f"  VR(k={k:2d}): {vr:.4f}  Z={z:+.4f}  {'|'}{direction}{'█'*bar_len}{sig}")
print("  VR=1 → 随机游走, VR<1 → 均值回复, VR>1 → 趋势持续")

# 2d. Hurst
H = _hurst_rs(rets)
print(f"\nHurst 指数 (R/S 分析): H = {H:.4f}" if H else "\nHurst: N/A")
if H:
    print(f"  H < 0.5 → 均值回复 (反持续)")
    print(f"  H = 0.5 → 随机游走")
    print(f"  H > 0.5 → 趋势持续")
    print(f"  偏离随机游走程度: |H - 0.5| = {abs(H-0.5):.4f}")

# 2e. Runs test
rt = _runs_test(rets)
if rt:
    n_runs, z = rt
    print(f"\n游程检验: runs={n_runs}, Z={z:+.4f}" + (" ***" if abs(z) > 1.96 else ""))

# ═══════════════════════════════════════════════════
# Part 3: 反转模式识别 — 涨跌交替频率
# ═══════════════════════════════════════════════════
print("\n" + "="*80)
print("反转模式分析")

# 统计连续涨/跌天数 (streaks)
signs = [1 if r >= 0 else -1 for r in rets]
streaks = []
cur_sign = signs[0]; cur_len = 1
for i in range(1, len(signs)):
    if signs[i] == cur_sign:
        cur_len += 1
    else:
        streaks.append((cur_sign, cur_len))
        cur_sign = signs[i]; cur_len = 1
streaks.append((cur_sign, cur_len))

up_streaks = [l for s,l in streaks if s == 1]
dn_streaks = [l for s,l in streaks if s == -1]

print(f"  总反转次数: {len(streaks)-1} (在 {n} 个交易日中)")
print(f"  平均连涨天数: {sum(up_streaks)/len(up_streaks):.2f}")
print(f"  平均连跌天数: {sum(dn_streaks)/len(dn_streaks):.2f}")
print(f"  连涨分布: " + str({k: sum(1 for l in up_streaks if l==k) for k in sorted(set(up_streaks))}))
print(f"  连跌分布: " + str({k: sum(1 for l in dn_streaks if l==k) for k in sorted(set(dn_streaks))}))

# 反转率 (隔日反转概率)
reversals = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i-1])
reversal_rate = reversals / (len(signs)-1) * 100
print(f"  隔日反转率: {reversals}/{len(signs)-1} = {reversal_rate:.1f}% (随机期望=50%)")

# 涨后跌、跌后涨的条件概率
up_then_down = sum(1 for i in range(1,len(signs)) if signs[i-1]==1 and signs[i]==-1)
up_then_any = sum(1 for i in range(1,len(signs)) if signs[i-1]==1)
dn_then_up = sum(1 for i in range(1,len(signs)) if signs[i-1]==-1 and signs[i]==1)
dn_then_any = sum(1 for i in range(1,len(signs)) if signs[i-1]==-1)
print(f"  P(跌|前日涨): {up_then_down}/{up_then_any} = {up_then_down/up_then_any*100:.1f}%")
print(f"  P(涨|前日跌): {dn_then_up}/{dn_then_any} = {dn_then_up/dn_then_any*100:.1f}%")

# ═══════════════════════════════════════════════════
# Part 4: RD 轨迹 + 价格偏离是否也被回复
# ═══════════════════════════════════════════════════
print("\n" + "="*80)
print("价格偏离(RD)轨迹分析")
devs = [fsei01[d]['dev_pct'] for d in sorted_days]
print(f"  RD 均值: {sum(devs)/len(devs):+.2f}%")
print(f"  RD 范围: [{min(devs):+.2f}%, {max(devs):+.2f}%]")
# RD 的自相关 (是否偏离本身也有均值回复特征)
dev_rets = [devs[i]-devs[i-1] for i in range(1,len(devs))]
if len(dev_rets) > 10:
    m_dr = sum(dev_rets)/len(dev_rets)
    v_dr = sum((d-m_dr)**2 for d in dev_rets)
    if v_dr > 0:
        c1 = sum((dev_rets[i]-m_dr)*(dev_rets[i+1]-m_dr) for i in range(len(dev_rets)-1))
        acf1_dev = c1/v_dr
        print(f"  ΔRD 的 ACF(1): {acf1_dev:+.4f} (负值→偏离变化也均值回复)")

# ═══════════════════════════════════════════════════
# Part 5: 三实验 FSEI 对比
# ═══════════════════════════════════════════════════
print("\n" + "="*80)
print("FSEI 三实验全面对比")
for exp_label, rd in [
    ('ToM01 (33-33-33)', experiments['ToM01']),
    ('ToM06 (60-10-30)', experiments['ToM06']),
    ('ToM07 (70-10-20)', experiments['ToM07']),
]:
    dd = load_sym_data(rd, 'FSEI')
    sdays = sorted(dd.keys())
    if len(sdays) < 2: continue
    p0 = dd[sdays[0]]['price']; pN = dd[sdays[-1]]['price']
    cum = math.log(pN/p0)*100
    dev_list = [dd[d]['dev_pct'] for d in sdays]
    avg_dev = sum(dev_list)/len(dev_list)
    
    r_list = []
    for i in range(1, len(sdays)):
        pp0, pp1 = dd[sdays[i-1]]['price'], dd[sdays[i]]['price']
        if pp0 > 0 and pp1 > 0: r_list.append(math.log(pp1/pp0))
    
    H_ = _hurst_rs(r_list)
    vr10_ = _variance_ratio(r_list, 10)
    rt_ = _runs_test(r_list)
    
    # 反转率
    s_ = [1 if r>=0 else -1 for r in r_list]
    rev_ = sum(1 for i in range(1,len(s_)) if s_[i]!=s_[i-1])
    rev_rate = rev_/(len(s_)-1)*100 if len(s_)>1 else 0
    
    avg_vol = sum(dd[d]['volume'] for d in sdays)/len(sdays)
    
    print(f"  {exp_label}:")
    print(f"    cum_ret={cum:+.1f}%, avg_dev={avg_dev:+.1f}%")
    print(f"    Hurst={H_:.3f}, VR(10)={vr10_:.3f}, RunsZ={rt_[1]:+.3f}" if H_ and vr10_ and rt_ else "    (insufficient)")
    print(f"    隔日反转率={rev_rate:.1f}%, avg_vol={avg_vol:.0f}")

# ═══════════════════════════════════════════════════
# Part 6: 全10指数按均值回复程度排序 (ToM01)
# ═══════════════════════════════════════════════════
print("\n" + "="*80)
print("ToM01 全10指数按均值回复程度排序 (Hurst 升序)")
all_results = []
for sym in SYMBOLS:
    dd = load_sym_data(experiments['ToM01'], sym)
    sdays = sorted(dd.keys())
    if len(sdays) < 2: continue
    r_list = []
    for i in range(1, len(sdays)):
        pp0, pp1 = dd[sdays[i-1]]['price'], dd[sdays[i]]['price']
        if pp0 > 0 and pp1 > 0: r_list.append(math.log(pp1/pp0))
    H_ = _hurst_rs(r_list)
    vr10_ = _variance_ratio(r_list, 10)
    dev_list = [dd[d]['dev_pct'] for d in sdays]
    avg_dev = sum(dev_list)/len(dev_list)
    s_ = [1 if r>=0 else -1 for r in r_list]
    rev_ = sum(1 for i in range(1,len(s_)) if s_[i]!=s_[i-1])
    rev_rate = rev_/(len(s_)-1)*100 if len(s_)>1 else 0
    cum = math.log(dd[sdays[-1]]['price']/dd[sdays[0]]['price'])*100
    all_results.append((sym, H_, vr10_, avg_dev, rev_rate, cum))

for sym, H_, vr10_, avg_dev, rev_rate, cum in sorted(all_results, key=lambda x: x[1] if x[1] else 999):
    mr_label = "均值回复" if H_ and H_ < 0.45 else ("随机游走" if H_ and abs(H_-0.5)<0.1 else "趋势持续")
    print(f"  {sym}: H={H_:.3f}, VR10={vr10_:.3f}, 反转率={rev_rate:.1f}%, avg_dev={avg_dev:+.1f}%, cum={cum:+.1f}%  [{mr_label}]")

# ═══════════════════════════════════════════════════
# Part 7: 量化买卖力量交替 —— ToM分层行为推测
# ═══════════════════════════════════════════════════
print("\n" + "="*80)
print("FSEI-ToM01 涨跌日的买卖力量对比")
up_days = [(d, fsei01[d]) for d in sorted_days[1:] if fsei01[d]['price'] > fsei01[sorted_days[sorted_days.index(d)-1]]['price']]
dn_days = [(d, fsei01[d]) for d in sorted_days[1:] if fsei01[d]['price'] < fsei01[sorted_days[sorted_days.index(d)-1]]['price']]

if up_days:
    avg_bsr_up = sum(r['buy_sell_ratio'] for _,r in up_days)/len(up_days)
    avg_vol_up = sum(r['volume'] for _,r in up_days)/len(up_days)
    print(f"  上涨日({len(up_days)}天): avg_B/S={avg_bsr_up:.3f}, avg_vol={avg_vol_up:.0f}")

if dn_days:
    avg_bsr_dn = sum(r['buy_sell_ratio'] for _,r in dn_days)/len(dn_days)
    avg_vol_dn = sum(r['volume'] for _,r in dn_days)/len(dn_days)
    print(f"  下跌日({len(dn_days)}天): avg_B/S={avg_bsr_dn:.3f}, avg_vol={avg_vol_dn:.0f}")
