#!/usr/bin/env python3
import json
from collections import defaultdict

orig = defaultdict(dict)
with open('runs/20260329_005147_tom07_tom12_tom21_预测拟合/market_snapshots.jsonl.bak') as f:
    for line in f:
        r = json.loads(line)
        sym, day, p = r.get('symbol',''), r.get('trading_day'), r.get('last_price')
        if sym and day and p and not sym.startswith('__'):
            orig[sym][int(day)] = float(p)

real_data = json.load(open('data/index_volatility_curves.json'))
real = {}
for sym, rows in real_data.get('indices', {}).items():
    prices = [r['close'] for r in sorted(rows, key=lambda x: x['date'])]
    real[sym] = prices

for sym in sorted(orig.keys()):
    days = sorted(orig[sym].keys())
    base_s = orig[sym][days[0]]
    rp = real.get(sym, [])
    base_r = rp[0] if rp else 1
    sim_10 = [100*orig[sym][d]/base_s for d in days[:10]]
    real_10 = [100*rp[i]/base_r for i in range(min(10, len(rp)))]
    s_str = ' '.join(f'{v:.1f}' for v in sim_10)
    r_str = ' '.join(f'{v:.1f}' for v in real_10)
    # Max sim change in first 10 days
    max_change = max(sim_10) - min(sim_10)
    print(f'{sym:6s}  max_swing={max_change:.1f}%')
    print(f'  sim:  {s_str}')
    print(f'  real: {r_str}')
