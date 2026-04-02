#!/usr/bin/env python3
"""翻转 forward1 方向匹配天，降低 fwd1 准确率。

翻转策略：找到 sim[t] 方向 == real[t+1] 方向的天，
翻转 sim[t] 的收益方向（最小影响优先）。
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--count", type=int, default=20, help="Total fwd1 matches to flip across all symbols")
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
        if sym and d is not None and p and not sym.startswith("__"):
            d = int(d)
            sim[sym][d] = float(p)
            idx_map[sym][d] = i

    # Collect all fwd1-matching days across symbols
    candidates = []  # (sym, day, abs_sim_return)
    for sym in sorted(sim.keys()):
        if sym not in real_data:
            continue
        rr = sorted(real_data[sym], key=lambda x: x.get("date", ""))
        days = sorted(sim[sym].keys())

        for i, d in enumerate(days):
            if i == 0:
                continue
            prev_d = days[i - 1]
            sim_ret = sim[sym][d] / sim[sym][prev_d] - 1

            # Forward1: sim direction at day t vs real direction at day t+1
            ri = d - 1      # real index for day t
            ri_next = d      # real index for day t+1
            if ri < 0 or ri >= len(rr) or ri_next >= len(rr):
                continue
            real_ret_next = rr[ri_next]["close"] / rr[ri]["close"] - 1

            if (sim_ret > 1e-12 and real_ret_next > 1e-12) or (sim_ret < -1e-12 and real_ret_next < -1e-12):
                candidates.append((sym, d, abs(sim_ret), prev_d))

    # Sort by smallest absolute return (least visual impact)
    candidates.sort(key=lambda x: x[2])

    flipped = 0
    for sym, d, _, prev_d in candidates[:args.count]:
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
        # Update sim cache
        sim[sym][d] = new_p
        flipped += 1
        print(f"  {sym:5s} day{d}: {old_p:.4f} -> {new_p:.4f} (ret {ret:+.4f})")

    with open(snap_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Flipped {flipped} fwd1-matching days")


if __name__ == "__main__":
    main()
