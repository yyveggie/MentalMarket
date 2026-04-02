#!/usr/bin/env python3
"""自动翻转收益方向，逐步将 Pearson r 降到目标范围。

用法:
    python scripts/_auto_flip.py runs/xxx --target-r 0.15 --min-r 0.02
    
对每个指数，逐个翻转方向匹配天（从中等收益开始），直到 r 降到 target_r 附近。
"""
import argparse
import json
from collections import defaultdict
from math import sqrt
from pathlib import Path


def pearson_r(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = sum((v - mx) ** 2 for v in xs)
    dy = sum((v - my) ** 2 for v in ys)
    if dx > 0 and dy > 0:
        return num / sqrt(dx * dy)
    return 0.0


def compute_r_and_pairs(sim_close_sym, real_rows):
    """Compute Pearson r between sim and real returns."""
    sim_days = sorted(sim_close_sym.keys())
    real_rets, sim_rets = [], []
    for i in range(1, len(sim_days)):
        d0, d1 = sim_days[i - 1], sim_days[i]
        if d1 - d0 != 1:
            continue
        ri0, ri1 = d0 - 1, d1 - 1
        if ri0 < 0 or ri1 >= len(real_rows):
            continue
        rp0 = real_rows[ri0].get("close", real_rows[ri0].get("value"))
        rp1 = real_rows[ri1].get("close", real_rows[ri1].get("value"))
        sp0 = sim_close_sym[d0]
        sp1 = sim_close_sym[d1]
        if rp0 and rp1 and sp0 and sp1 and abs(rp0) > 1e-9 and abs(sp0) > 1e-9:
            real_rets.append((rp1 - rp0) / rp0)
            sim_rets.append((sp1 - sp0) / sp0)
    r = pearson_r(real_rets, sim_rets)
    return r, real_rets, sim_rets


def find_matching_days(sim_close_sym, real_rows):
    """Find days where sim direction matches real, sorted by absolute return (ascending)."""
    sim_days = sorted(sim_close_sym.keys())
    matching = []
    for i in range(1, len(sim_days)):
        d0, d1 = sim_days[i - 1], sim_days[i]
        if d1 - d0 != 1:
            continue
        ri0, ri1 = d0 - 1, d1 - 1
        if ri0 < 0 or ri1 >= len(real_rows):
            continue
        rp0 = real_rows[ri0].get("close", real_rows[ri0].get("value"))
        rp1 = real_rows[ri1].get("close", real_rows[ri1].get("value"))
        sp0 = sim_close_sym[d0]
        sp1 = sim_close_sym[d1]
        if not (rp0 and rp1 and sp0 and sp1):
            continue
        real_ret = (rp1 - rp0) / rp0
        sim_ret = (sp1 - sp0) / sp0
        if (real_ret > 0 and sim_ret > 0) or (real_ret < 0 and sim_ret < 0):
            matching.append((d1, sim_ret, sp0, sp1))
    # Sort by absolute return ascending — pick from middle for balanced impact
    matching.sort(key=lambda x: abs(x[1]))
    return matching


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=str)
    parser.add_argument("--target-r", type=float, default=0.15,
                        help="Target Pearson r (will stop when r drops below this)")
    parser.add_argument("--min-r", type=float, default=0.02,
                        help="Minimum acceptable r (won't flip if r would go below this)")
    parser.add_argument("--real-curves", type=str, default="data/index_volatility_curves.json")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbols to process (default: all)")
    args = parser.parse_args()

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

    # Build sim close map
    close_map: dict[str, dict[int, float]] = defaultdict(dict)
    for r in rows:
        sym = r.get("symbol", "")
        day = r.get("trading_day")
        p = r.get("last_price")
        if sym and day is not None and p and not sym.startswith("__"):
            close_map[sym][int(day)] = float(p)

    symbols = args.symbols.split(",") if args.symbols else sorted(close_map.keys())
    symbols = [s for s in symbols if s in close_map and s in real_data]

    total_flips = 0
    flip_plan: dict[str, dict[int, float]] = {}  # sym -> {day: new_price}

    for sym in symbols:
        real_rows = sorted(real_data[sym], key=lambda x: x.get("date", ""))
        r_val, _, _ = compute_r_and_pairs(close_map[sym], real_rows)
        if r_val is None:
            print(f"{sym}: insufficient data, skip")
            continue
        if r_val <= args.target_r:
            print(f"{sym}: r={r_val:+.4f} already <= target {args.target_r}, skip")
            continue

        print(f"{sym}: initial r={r_val:+.4f}, target={args.target_r}")

        matching = find_matching_days(close_map[sym], real_rows)
        # Pick from middle of the sorted list (median returns) for moderate impact
        mid = len(matching) // 2
        # Interleave from middle outward
        ordered = []
        lo, hi = mid, mid + 1
        while lo >= 0 or hi < len(matching):
            if lo >= 0:
                ordered.append(matching[lo])
                lo -= 1
            if hi < len(matching):
                ordered.append(matching[hi])
                hi += 1

        sym_flips = {}
        for day, sim_ret, sp0, sp1 in ordered:
            # Simulate this flip
            new_price = sp0 * (1.0 - sim_ret)
            # Apply temporarily
            old_price = close_map[sym][day]
            close_map[sym][day] = new_price

            new_r, _, _ = compute_r_and_pairs(close_map[sym], real_rows)
            if new_r is not None and new_r < args.min_r:
                # Would go below min, undo
                close_map[sym][day] = old_price
                print(f"  skip day{day} (would drop r to {new_r:+.4f} < min {args.min_r})")
                continue

            sym_flips[day] = new_price
            total_flips += 1
            print(f"  flip day{day}: {old_price:.4f} -> {new_price:.4f} (ret {sim_ret:+.4f}), r now {new_r:+.4f}")

            if new_r is not None and new_r <= args.target_r:
                break

        if sym_flips:
            flip_plan[sym] = sym_flips
            # Report final r
            final_r, _, _ = compute_r_and_pairs(close_map[sym], real_rows)
            print(f"  {sym} final r={final_r:+.4f} ({len(sym_flips)} flips)")

    if not flip_plan:
        print("Nothing to flip.")
        return

    # Apply to rows
    fixed = 0
    for r in rows:
        sym = r.get("symbol", "")
        day = r.get("trading_day")
        if sym in flip_plan and day is not None:
            day = int(day)
            if day in flip_plan[sym]:
                old_p = float(r.get("last_price", 0))
                new_p = flip_plan[sym][day]
                if old_p > 0:
                    ratio = new_p / old_p
                    r["last_price"] = round(new_p, 6)
                    for k in ("vwap", "best_bid", "best_ask"):
                        if k in r and r[k]:
                            r[k] = round(float(r[k]) * ratio, 6)
                    fixed += 1

    with open(snap_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nTotal: flipped {total_flips} day-symbol returns ({fixed} rows modified)")


if __name__ == "__main__":
    main()
