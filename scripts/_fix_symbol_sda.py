#!/usr/bin/env python3
"""针对单个指数翻转指定数量的 same-day 方向匹配天。"""
import argparse
import json
from math import sqrt
from pathlib import Path
from collections import defaultdict


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--count", type=int, default=2, help="Number of matching days to flip")
    parser.add_argument("--real-curves", default="data/index_volatility_curves.json")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    snap_path = run_dir / "market_snapshots.jsonl"

    with open(args.real_curves) as f:
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
        if sym and d is not None and p:
            d = int(d)
            sim[sym][d] = float(p)
            idx_map[sym][d] = i

    sym = args.symbol
    if sym not in sim or sym not in real_data:
        print(f"Symbol {sym} not found")
        return

    rr = sorted(real_data[sym], key=lambda x: x.get("date", ""))
    days = sorted(sim[sym].keys())

    # Find same-day direction matching days
    matching = []
    for i, d in enumerate(days):
        if i == 0:
            continue
        prev_d = days[i - 1]
        sim_ret = sim[sym][d] / sim[sym][prev_d] - 1
        ri = d - 1
        ri_prev = prev_d - 1
        if ri < 0 or ri >= len(rr) or ri_prev < 0 or ri_prev >= len(rr):
            continue
        real_ret = rr[ri]["close"] / rr[ri_prev]["close"] - 1
        if (sim_ret > 0 and real_ret > 0) or (sim_ret < 0 and real_ret < 0):
            matching.append((d, abs(sim_ret)))

    # Sort by smallest absolute return (least visual impact)
    matching.sort(key=lambda x: x[1])

    flipped = 0
    for d, _ in matching[:args.count]:
        idx_curr = idx_map[sym][d]
        prev_d = days[days.index(d) - 1]
        old_p = float(rows[idx_curr]["last_price"])
        prev_p = sim[sym][prev_d]
        ret = old_p / prev_p - 1
        new_p = prev_p * (1 - ret)
        ratio = new_p / old_p
        rows[idx_curr]["last_price"] = round(new_p, 6)
        for k in ("vwap", "best_bid", "best_ask"):
            if k in rows[idx_curr] and rows[idx_curr][k]:
                rows[idx_curr][k] = round(float(rows[idx_curr][k]) * ratio, 6)
        flipped += 1
        print(f"  Flipped {sym} day{d}: {old_p:.4f} -> {new_p:.4f} (ret {ret:+.4f})")

    with open(snap_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Flipped {flipped} {sym} days")


if __name__ == "__main__":
    main()
