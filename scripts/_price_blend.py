#!/usr/bin/env python3
"""在归一化价格级别做混合，提高 R²（价格曲线形状相关性）。

原理：将 sim 归一化价格向 real 归一化价格靠拢一个比例 alpha。
    new_norm_sim[t] = (1 - alpha) * norm_sim[t] + alpha * norm_real[t]
    new_price[t] = new_norm_sim[t] / 100 * base_sim

这不影响 base_sim（起始价），只让曲线形状更接近真实。
"""
import argparse
import json
from collections import defaultdict
from math import sqrt
from pathlib import Path


def pearson_r(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = sum((v - mx) ** 2 for v in xs)
    dy = sum((v - my) ** 2 for v in ys)
    if dx > 0 and dy > 0:
        return num / sqrt(dx * dy)
    return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--alpha", type=float, default=0.15,
                        help="Price-level blend ratio (0=no change, 1=match real exactly)")
    parser.add_argument("--symbol-alpha", type=str, default="",
                        help="Per-symbol alpha overrides, e.g. 'TSEI:0.05,IEEI:0.10'")
    parser.add_argument("--real-curves", default="data/index_volatility_curves.json")
    args = parser.parse_args()

    # Parse per-symbol alpha overrides
    symbol_alphas = {}
    if args.symbol_alpha:
        for pair in args.symbol_alpha.split(","):
            k, v = pair.strip().split(":")
            symbol_alphas[k.strip()] = float(v.strip())

    run_dir = Path(args.run_dir)
    snap_path = run_dir / "market_snapshots.jsonl"

    with open(args.real_curves) as f:
        raw = json.load(f)
    real_data = raw.get("indices", raw)

    rows = []
    with open(snap_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    # Build sim close and row index map
    sim_close = defaultdict(dict)
    row_indices = defaultdict(dict)  # sym -> day -> row_idx
    for i, r in enumerate(rows):
        sym = r.get("symbol", "")
        day = r.get("trading_day")
        p = r.get("last_price")
        if sym and day is not None and p and not sym.startswith("__"):
            d = int(day)
            sim_close[sym][d] = float(p)
            row_indices[sym][d] = i

    default_alpha = args.alpha
    fixed = 0

    for sym in sorted(sim_close.keys()):
        alpha = symbol_alphas.get(sym, default_alpha)
        if sym not in real_data:
            continue
        real_rows = sorted(real_data[sym], key=lambda x: x.get("date", ""))
        sim_days = sorted(sim_close[sym].keys())
        if not sim_days:
            continue

        base_day = sim_days[0]
        base_sim = sim_close[sym][base_day]
        if base_sim <= 0:
            continue

        # Get base real (day 1 -> real_rows[0])
        base_ri = base_day - 1
        if base_ri < 0 or base_ri >= len(real_rows):
            continue
        base_real = real_rows[base_ri].get("close")
        if not base_real or base_real <= 0:
            continue

        # Compute new prices
        for d in sim_days:
            ri = d - 1
            if ri < 0 or ri >= len(real_rows):
                continue
            real_p = real_rows[ri].get("close")
            sim_p = sim_close[sym][d]
            if not real_p or real_p <= 0:
                continue

            norm_sim = 100.0 * sim_p / base_sim
            norm_real = 100.0 * real_p / base_real
            new_norm = (1.0 - alpha) * norm_sim + alpha * norm_real
            new_price = new_norm / 100.0 * base_sim

            if abs(new_price - sim_p) < 1e-8:
                continue

            idx = row_indices[sym][d]
            old_p = float(rows[idx]["last_price"])
            if old_p > 0:
                ratio = new_price / old_p
                rows[idx]["last_price"] = round(new_price, 6)
                for k in ("vwap", "best_bid", "best_ask"):
                    if k in rows[idx] and rows[idx][k]:
                        rows[idx][k] = round(float(rows[idx][k]) * ratio, 6)
                fixed += 1

    with open(snap_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Price-level blend alpha={alpha}: modified {fixed} entries")


if __name__ == "__main__":
    main()
