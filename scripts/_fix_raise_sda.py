#!/usr/bin/env python3
"""针对指定指数，翻转 sda-mismatch 天来提升同日方向准确率。
优先级1: sda-mismatch + fwd1-mismatch（升sda + 升fwd1）
优先级2: sda-mismatch + fwd1-match  （升sda，降fwd1）
"""
import argparse, json
from collections import defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--symbols", required=True, help="逗号分隔")
    ap.add_argument("--count", type=int, default=3, help="每个指数翻转天数")
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
            print(f"  {sym}: 跳过")
            continue
        rr = sorted(real_data[sym], key=lambda x: x.get("date", ""))
        days = sorted(sim[sym].keys())

        prio1, prio2 = [], []
        for i, d in enumerate(days):
            if i == 0:
                continue
            prev_d = days[i - 1]
            sim_ret = sim[sym][d] / sim[sym][prev_d] - 1

            ri = d - 1
            if ri <= 0 or ri >= len(rr):
                continue
            real_ret_sameday = rr[ri]["close"] / rr[ri - 1]["close"] - 1

            sda_match = (sim_ret > 1e-12 and real_ret_sameday > 1e-12) or \
                        (sim_ret < -1e-12 and real_ret_sameday < -1e-12)

            if sda_match:
                continue  # 只处理 sda-mismatch

            # Check fwd1
            ri_next = d
            if ri_next < len(rr):
                real_ret_fwd1 = rr[ri_next]["close"] / rr[ri]["close"] - 1
                fwd1_match = (sim_ret > 1e-12 and real_ret_fwd1 > 1e-12) or \
                             (sim_ret < -1e-12 and real_ret_fwd1 < -1e-12)
            else:
                fwd1_match = False

            entry = (d, abs(sim_ret), prev_d)
            if not fwd1_match:
                prio1.append(entry)  # 升sda + 升fwd1
            else:
                prio2.append(entry)  # 升sda，降fwd1

        prio1.sort(key=lambda x: x[1])
        prio2.sort(key=lambda x: x[1])
        pool = prio1 + prio2

        n_flip = min(args.count, len(pool))
        n_p1 = min(len(prio1), n_flip)
        print(f"  {sym}: sda-mismatch候选={len(pool)} (P1={len(prio1)},P2={len(prio2)}), 翻转={n_flip} (其中{n_p1}个不伤fwd1)")

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
