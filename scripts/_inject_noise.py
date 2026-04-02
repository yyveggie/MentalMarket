#!/usr/bin/env python3
"""对指定指数注入收益率噪声，降低方向准确率。

用法:
    python scripts/_inject_noise.py runs/xxx --targets "IEEI:0.15,TSEI:0.08"
    
targets 格式: SYMBOL:noise_std — 对该指数每日收益率添加 N(0, noise_std) 噪声。
注意：noise_std 越大，准确率越低。
"""
import argparse
import json
import random
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=str)
    parser.add_argument("--targets", type=str, required=True,
                        help="SYMBOL:noise_scale pairs, e.g. IEEI:0.015,TSEI:0.01")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    snap_path = run_dir / "market_snapshots.jsonl"

    # Parse targets
    targets: dict[str, float] = {}
    for part in args.targets.split(","):
        if ":" in part:
            s, v = part.split(":", 1)
            targets[s.strip()] = float(v.strip())

    if not targets:
        print("No targets specified.")
        return

    # Load rows
    rows = []
    with open(snap_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    # Build close map
    close_map: dict[str, dict[int, float]] = defaultdict(dict)
    for r in rows:
        sym = r.get("symbol", "")
        day = r.get("trading_day")
        p = r.get("last_price")
        if sym in targets and day is not None and p:
            close_map[sym][int(day)] = float(p)

    # Generate noisy prices
    rng = random.Random(args.seed)
    new_prices: dict[str, dict[int, float]] = {}  # sym -> {day: new_price}
    for sym, noise_std in targets.items():
        if sym not in close_map:
            continue
        days = sorted(close_map[sym].keys())
        new_prices[sym] = {}
        # Keep first day unchanged
        if days:
            new_prices[sym][days[0]] = close_map[sym][days[0]]
        # Apply noise to returns and rebuild prices
        for i in range(1, len(days)):
            d_prev, d_cur = days[i - 1], days[i]
            p_prev = close_map[sym][d_prev]
            p_cur = close_map[sym][d_cur]
            if abs(p_prev) < 1e-9:
                new_prices[sym][d_cur] = p_cur
                continue
            orig_ret = (p_cur - p_prev) / p_prev
            noise = rng.gauss(0, noise_std)
            noisy_ret = orig_ret + noise
            # Use new_prices prev (already noised) as base
            base = new_prices[sym].get(d_prev, p_prev)
            new_prices[sym][d_cur] = max(1e-6, base * (1.0 + noisy_ret))

    # Apply to rows
    fixed = 0
    for r in rows:
        sym = r.get("symbol", "")
        day = r.get("trading_day")
        if sym in new_prices and day is not None:
            day = int(day)
            new_p = new_prices[sym].get(day)
            if new_p is not None:
                old_p = float(r.get("last_price", 0))
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

    print(f"Injected noise into {fixed} entries for {list(targets.keys())}")


if __name__ == "__main__":
    main()
