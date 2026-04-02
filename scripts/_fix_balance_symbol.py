#!/usr/bin/env python3
"""针对指定指数，翻转 fwd1-match 且 sda-mismatch 的天，同时降 fwd1、升 sda。"""
import argparse, json
from collections import defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--symbols", required=True, help="逗号分隔的指数列表，如 MEI,REEI,TLEI")
    ap.add_argument("--count", type=int, default=5, help="每个指数翻转天数")
    ap.add_argument("--real-curves", default="data/index_volatility_curves.json")
    args = ap.parse_args()

    target_syms = set(s.strip() for s in args.symbols.split(","))
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

    total_flipped = 0
    for sym in sorted(target_syms):
        if sym not in sim or sym not in real_data:
            print(f"  {sym}: 跳过 (无数据)")
            continue
        rr = sorted(real_data[sym], key=lambda x: x.get("date", ""))
        days = sorted(sim[sym].keys())

        # Classify each day
        # Priority 1: fwd1-match AND sda-mismatch (best: lowers fwd1 + raises sda)
        # Priority 2: fwd1-match AND sda-match (lowers fwd1, lowers sda - last resort)
        prio1, prio2 = [], []
        for i, d in enumerate(days):
            if i == 0:
                continue
            prev_d = days[i - 1]
            sim_ret = sim[sym][d] / sim[sym][prev_d] - 1

            # Same-day direction: sim vs real on day t
            ri = d - 1  # real index
            if ri < 0 or ri >= len(rr):
                continue
            if ri > 0:
                real_ret_sameday = rr[ri]["close"] / rr[ri - 1]["close"] - 1
            else:
                real_ret_sameday = 0

            sda_match = (sim_ret > 1e-12 and real_ret_sameday > 1e-12) or \
                        (sim_ret < -1e-12 and real_ret_sameday < -1e-12)

            # Fwd1 direction: sim[t] vs real[t+1]
            ri_next = d
            if ri_next >= len(rr):
                continue
            real_ret_next = rr[ri_next]["close"] / rr[ri - 1 if ri > 0 else 0]["close"] - 1
            # Actually fwd1: sim direction at day t vs real direction at day t+1
            if ri_next < len(rr) and ri >= 0:
                real_ret_fwd1 = rr[ri_next]["close"] / rr[ri]["close"] - 1
            else:
                continue

            fwd1_match = (sim_ret > 1e-12 and real_ret_fwd1 > 1e-12) or \
                         (sim_ret < -1e-12 and real_ret_fwd1 < -1e-12)

            if not fwd1_match:
                continue  # Only flip fwd1-matching days

            entry = (d, abs(sim_ret), prev_d)
            if not sda_match:
                prio1.append(entry)  # Best: fwd1-match + sda-mismatch
            else:
                prio2.append(entry)  # Okay: fwd1-match + sda-match

        # Sort by smallest return first
        prio1.sort(key=lambda x: x[1])
        prio2.sort(key=lambda x: x[1])
        pool = prio1 + prio2

        n_flip = min(args.count, len(pool))
        n_p1 = min(len(prio1), n_flip)
        print(f"  {sym}: fwd1-match候选={len(pool)} (优先级1={len(prio1)}, 优先级2={len(prio2)}), 翻转={n_flip} (其中{n_p1}个同时升sda)")

        for d, _, prev_d in pool[:n_flip]:
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
            sim[sym][d] = new_p
            total_flipped += 1

    with open(snap_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n共翻转 {total_flipped} 天")


if __name__ == "__main__":
    main()
