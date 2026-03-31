#!/usr/bin/env python3
"""分析真实曲线与模拟曲线之间的差距。"""
import json
from pathlib import Path

run_dir = Path("runs/20260329_150251")

# 1. Load real curves
rc = json.loads(Path("data/index_volatility_curves.json").read_text(encoding="utf-8"))
real_symbols = list(rc.get("indices", {}).keys())
print(f"Real symbols: {real_symbols}")

# Build real close by (symbol, day_index)
# day_index=1 corresponds to the first date in the calendar
all_dates = set()
for sym, rows in rc.get("indices", {}).items():
    for r in rows:
        d = r.get("date", "")
        if d:
            all_dates.add(d)
calendar = sorted(all_dates)
date_to_day = {d: i + 1 for i, d in enumerate(calendar)}
print(f"Real calendar: {len(calendar)} dates, {calendar[0]} to {calendar[-1]}")

real_close = {}  # (symbol, day) -> close
for sym, rows in rc.get("indices", {}).items():
    for r in rows:
        d = r.get("date", "")
        c = r.get("close")
        if d and c is not None:
            day = date_to_day[d]
            real_close[(sym, day)] = float(c)

# 2. Load sim snapshots
snap_rows = []
with open(run_dir / "market_snapshots.jsonl", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            snap_rows.append(json.loads(line))

sim_symbols = set()
sim_days = set()
sim_by = {}
for r in snap_rows:
    s = r.get("symbol", "")
    d = int(r.get("trading_day", 0) or 0)
    t = float(r.get("sim_time", 0) or 0)
    p = float(r.get("last_price", 0) or 0)
    if not s or d <= 0 or p <= 0:
        continue
    sim_symbols.add(s)
    sim_days.add(d)
    key = (s, d)
    if key not in sim_by or t >= sim_by[key][0]:
        sim_by[key] = (t, p)

print(f"\nSim symbols: {sorted(sim_symbols)}")
print(f"Sim trading days: {min(sim_days)}-{max(sim_days)} ({len(sim_days)} days)")

# 3. Compare
common_symbols = sorted(set(real_symbols) & sim_symbols)
print(f"\nCommon symbols: {common_symbols}")

for sym in common_symbols:
    real_days = sorted(d for (s, d) in real_close if s == sym)
    sim_days_s = sorted(d for (s, d) in sim_by if s == sym)
    common_days = sorted(set(real_days) & set(sim_days_s))
    if not common_days:
        print(f"  {sym}: no common days")
        continue
    
    # Compute direction accuracy and correlation
    same_dir = 0
    total = 0
    real_rets = []
    sim_rets = []
    for i in range(1, len(common_days)):
        d_prev = common_days[i - 1]
        d_cur = common_days[i]
        if d_cur != d_prev + 1:
            continue
        rp = real_close[(sym, d_prev)]
        rc_val = real_close[(sym, d_cur)]
        sp = sim_by[(sym, d_prev)][1]
        sc = sim_by[(sym, d_cur)][1]
        
        rd = rc_val - rp
        sd = sc - sp
        
        r_sign = 1 if rd > 1e-12 else (-1 if rd < -1e-12 else 0)
        s_sign = 1 if sd > 1e-12 else (-1 if sd < -1e-12 else 0)
        
        if not (r_sign == 0 and s_sign == 0):
            if r_sign == s_sign:
                same_dir += 1
            total += 1
        
        real_rets.append(rd / rp if abs(rp) > 1e-9 else 0)
        sim_rets.append(sd / sp if abs(sp) > 1e-9 else 0)
    
    # Pearson corr
    n = len(real_rets)
    if n >= 2:
        mx = sum(real_rets) / n
        my = sum(sim_rets) / n
        num = sum((real_rets[i] - mx) * (sim_rets[i] - my) for i in range(n))
        dx = sum((v - mx) ** 2 for v in real_rets)
        dy = sum((v - my) ** 2 for v in sim_rets)
        corr = num / (dx * dy) ** 0.5 if dx > 0 and dy > 0 else 0
    else:
        corr = 0
    
    acc = 100.0 * same_dir / total if total > 0 else 0
    fit = max(0, corr) * 100
    
    print(f"  {sym}: common_days={len(common_days)}, dir_acc={acc:.1f}%, corr={corr:.3f}, fit={fit:.1f}%")
    
    # Show a few sample days
    if common_days:
        d = common_days[0]
        rp = real_close[(sym, d)]
        sp = sim_by[(sym, d)][1]
        print(f"    day1: real={rp:.2f}, sim={sp:.2f}, ratio={sp/rp:.4f}")
        d = common_days[-1]
        rp = real_close[(sym, d)]
        sp = sim_by[(sym, d)][1]
        print(f"    last: real={rp:.2f}, sim={sp:.2f}, ratio={sp/rp:.4f}")
