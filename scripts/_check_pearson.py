#!/usr/bin/env python3
"""检查各指数的真实 Pearson r（不截断）。"""
import json, sys
from pathlib import Path
from math import sqrt
from collections import defaultdict

if len(sys.argv) < 2:
    print("Usage: _check_pearson.py <run_dir>")
    sys.exit(1)
run = Path(sys.argv[1])

with open("data/index_volatility_curves.json") as f:
    raw = json.load(f)
real_data = raw.get("indices", raw)

rows = []
with open(run / "market_snapshots.jsonl") as f:
    for line in f:
        line = line.strip()
        if line:
            rows.append(json.loads(line))

sim_close = defaultdict(dict)
for r in rows:
    sym = r.get("symbol", "")
    td = r.get("trading_day")
    p = r.get("last_price")
    if sym and td is not None and p and not sym.startswith("__"):
        sim_close[sym][int(td)] = float(p)

print(f"{'指数':6s}  {'Pearson_r':>10s}  {'pairs':>6s}")
print("-" * 30)
for sym in sorted(real_data.keys()):
    if sym.startswith("__") or sym not in sim_close:
        continue
    real_rows = sorted(real_data[sym], key=lambda x: x.get("date", ""))
    max_day = max(sim_close[sym].keys()) if sim_close[sym] else 0
    n_days = min(len(real_rows), max_day + 1)

    real_rets = []
    sim_rets = []
    sim_days = sorted(sim_close[sym].keys())
    for i in range(1, len(sim_days)):
        d0, d1 = sim_days[i - 1], sim_days[i]
        if d1 - d0 != 1:
            continue
        # real index: d0-1, d1-1 (day 1 -> real_rows[0])
        ri0, ri1 = d0 - 1, d1 - 1
        if ri0 < 0 or ri1 >= len(real_rows):
            continue
        rp0 = real_rows[ri0].get("close", real_rows[ri0].get("value"))
        rp1 = real_rows[ri1].get("close", real_rows[ri1].get("value"))
        sp0 = sim_close[sym][d0]
        sp1 = sim_close[sym][d1]
        if rp0 and rp1 and sp0 and sp1 and abs(rp0) > 1e-9 and abs(sp0) > 1e-9:
            real_rets.append((rp1 - rp0) / rp0)
            sim_rets.append((sp1 - sp0) / sp0)

    if len(real_rets) < 5:
        print(f"{sym:6s}  insufficient data ({len(real_rets)} pairs)")
        continue

    n = len(real_rets)
    mx = sum(real_rets) / n
    my = sum(sim_rets) / n
    num = sum((real_rets[j] - mx) * (sim_rets[j] - my) for j in range(n))
    dx = sum((v - mx) ** 2 for v in real_rets)
    dy = sum((v - my) ** 2 for v in sim_rets)
    if dx > 0 and dy > 0:
        pr = num / sqrt(dx * dy)
    else:
        pr = 0
    print(f"{sym:6s}  {pr:+10.4f}  {n:6d}")
