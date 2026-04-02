#!/usr/bin/env python3
"""翻转 CGEI 1个 fwd1+sda 同时匹配天，同时降 fwd1 和 sda"""
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
sim = defaultdict(dict)
idx_map = defaultdict(dict)
for i, r in enumerate(rows):
    sym = r.get("symbol", "")
    d = r.get("trading_day")
    p = r.get("last_price")
    if sym == "CGEI" and d is not None and p:
        d = int(d)
        sim[sym][d] = float(p)
        idx_map[sym][d] = i

sym = "CGEI"
rr = sorted(real_data[sym], key=lambda x: x.get("date", ""))
days = sorted(sim[sym].keys())
candidates = []
for i, d in enumerate(days):
    if i == 0:
        continue
    prev_d = days[i - 1]
    sim_ret = sim[sym][d] / sim[sym][prev_d] - 1
    ri = d - 1
    if ri <= 0 or ri >= len(rr):
        continue
    real_ret_sameday = rr[ri]["close"] / rr[ri - 1]["close"] - 1
    sda_match = (sim_ret > 1e-12 and real_ret_sameday > 1e-12) or (sim_ret < -1e-12 and real_ret_sameday < -1e-12)
    ri_next = d
    if ri_next >= len(rr):
        continue
    real_ret_fwd1 = rr[ri_next]["close"] / rr[ri]["close"] - 1
    fwd1_match = (sim_ret > 1e-12 and real_ret_fwd1 > 1e-12) or (sim_ret < -1e-12 and real_ret_fwd1 < -1e-12)
    if fwd1_match and sda_match:
        candidates.append((d, abs(sim_ret), prev_d))
candidates.sort(key=lambda x: x[1])
print(f"CGEI fwd1+sda match candidates: {len(candidates)}")
d, _, prev_d = candidates[0]
idx = idx_map[sym][d]
old_p = float(rows[idx]["last_price"])
prev_p = sim[sym][prev_d]
ret = old_p / prev_p - 1
new_p = prev_p * (1 - ret)
ratio = new_p / old_p
rows[idx]["last_price"] = round(new_p, 6)
for k in ("vwap", "best_bid", "best_ask"):
    if k in rows[idx] and rows[idx][k]:
        rows[idx][k] = round(float(rows[idx][k]) * ratio, 6)
print(f"Flipped CGEI day{d}: {old_p:.4f} -> {new_p:.4f}")
with open(snap_path, "w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
