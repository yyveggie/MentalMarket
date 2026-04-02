#!/usr/bin/env python3
import json, sys
from collections import defaultdict
from pathlib import Path

run_dir = Path(sys.argv[1])
snap_path = run_dir / "market_snapshots.jsonl"
with open("data/index_volatility_curves.json") as f:
    raw = json.load(f)
real_data = raw.get("indices", raw)

rows = []
with open(snap_path) as f:
    for line in f:
        line = line.strip()
        if line:
            rows.append(json.loads(line))

sim_close = defaultdict(dict)
for r in rows:
    sym = r.get("symbol", "")
    day = r.get("trading_day")
    p = r.get("last_price")
    if sym and day is not None and p and not sym.startswith("__"):
        sim_close[sym][int(day)] = float(p)

for sym in sorted(sim_close.keys()):
    if sym not in real_data:
        continue
    real_rows = sorted(real_data[sym], key=lambda x: x.get("date", ""))
    days = sorted(sim_close[sym].keys())
    sda_match = fwd_match = sda_n = fwd_n = 0
    for i, d in enumerate(days):
        ri = d - 1
        if ri < 1 or ri >= len(real_rows):
            continue
        if i == 0:
            continue
        prev_d = days[i - 1]
        if prev_d not in sim_close[sym]:
            continue
        sim_r = sim_close[sym][d] / sim_close[sym][prev_d] - 1
        real_r = real_rows[ri]["close"] / real_rows[ri - 1]["close"] - 1
        sda_n += 1
        if (sim_r >= 0) == (real_r >= 0):
            sda_match += 1
        if ri + 1 < len(real_rows):
            fwd_r = real_rows[ri + 1]["close"] / real_rows[ri]["close"] - 1
            fwd_n += 1
            if (sim_r >= 0) == (fwd_r >= 0):
                fwd_match += 1
    sda_pct = 100 * sda_match / sda_n if sda_n else 0
    fwd_pct = 100 * fwd_match / fwd_n if fwd_n else 0
    print(f"{sym}: sda={sda_pct:.1f}% ({sda_match}/{sda_n})  fwd1={fwd_pct:.1f}% ({fwd_match}/{fwd_n})")
