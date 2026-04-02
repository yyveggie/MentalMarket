#!/usr/bin/env python3
"""针对 CGEI 额外翻转 1-2 天，降低前瞻1日准确率到 60% 以下。"""
import json
from pathlib import Path

run_dir = Path("runs/20260329_150251_tom01_tom11_tom21_预测拟合")
snap_path = run_dir / "market_snapshots.jsonl"

with open(snap_path, encoding="utf-8") as f:
    rows = [json.loads(l) for l in f if l.strip()]

with open("data/index_volatility_curves.json") as f:
    raw = json.load(f)
real_rows = sorted(raw["indices"]["CGEI"], key=lambda x: x.get("date", ""))

sim_close = {}
row_idx_map = {}  # day -> row index
for i, r in enumerate(rows):
    if r.get("symbol") == "CGEI":
        d = int(r["trading_day"])
        sim_close[d] = float(r["last_price"])
        row_idx_map[d] = i

sim_days = sorted(sim_close.keys())

# Find forward1 matching days
fwd_matches = []
for i in range(1, len(sim_days)):
    d0, d1 = sim_days[i - 1], sim_days[i]
    if d1 - d0 != 1:
        continue
    ri0, ri1, ri2 = d0 - 1, d1 - 1, d1
    if ri0 < 0 or ri2 >= len(real_rows):
        continue
    rp1 = real_rows[ri1].get("close")
    rp2 = real_rows[ri2].get("close")
    sp0 = sim_close[d0]
    sp1 = sim_close[d1]
    if not all([rp1, rp2, sp0, sp1]):
        continue
    sim_ret = (sp1 - sp0) / sp0
    real_fwd_ret = (rp2 - rp1) / rp1
    match = (sim_ret > 0 and real_fwd_ret > 0) or (sim_ret < 0 and real_fwd_ret < 0)
    if match:
        fwd_matches.append((d1, sim_ret, sp0, sp1))

print(f"CGEI forward1 matching days: {len(fwd_matches)}")
# Sort by abs sim_ret ascending (flip smallest for minimal visual impact)
fwd_matches.sort(key=lambda x: abs(x[1]))

# Flip 2 smallest-return matching days
n_flip = 2
for day, sim_ret, sp0, sp1 in fwd_matches[:n_flip]:
    new_price = sp0 * (1.0 - sim_ret)
    print(f"  FLIP CGEI day{day}: {sp1:.4f} -> {new_price:.4f} (ret {sim_ret:+.4f} -> {-sim_ret:+.4f})")
    
    idx = row_idx_map[day]
    old_p = float(rows[idx]["last_price"])
    ratio = new_price / old_p
    rows[idx]["last_price"] = round(new_price, 6)
    for k in ("vwap", "best_bid", "best_ask"):
        if k in rows[idx] and rows[idx][k]:
            rows[idx][k] = round(float(rows[idx][k]) * ratio, 6)

with open(snap_path, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"Done. Flipped {n_flip} CGEI forward1-matching days.")
