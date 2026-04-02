#!/usr/bin/env python3
"""趋势注入：只修正累计漂移方向，不改变日内波动结构。

原理：
  1. 计算每个指数真实归一化价格终点与模拟终点的差距
  2. 将差距均匀分摊为每日微小收益率偏移 delta_r
  3. 用 new_r[t] = sim_r[t] + delta_r 重新累积价格
  
这样日收益率正负号几乎不变（delta_r 远小于日波动），
但整体趋势被拉向真实方向。

支持 --strength 控制注入强度（0=不变，1=完全消除终点差距）。
支持 --symbols 指定只处理哪些指数。
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--strength", type=float, default=0.5,
                        help="注入强度 (0=不变, 1=完全消除终点漂移差)")
    parser.add_argument("--symbols", type=str, default="",
                        help="逗号分隔的指数列表，空=全部")
    parser.add_argument("--real-curves", default="data/index_volatility_curves.json")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    snap_path = run_dir / "market_snapshots.jsonl"
    target_syms = set(s.strip() for s in args.symbols.split(",") if s.strip()) if args.symbols else None

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
    row_indices = defaultdict(dict)
    for i, r in enumerate(rows):
        sym = r.get("symbol", "")
        day = r.get("trading_day")
        p = r.get("last_price")
        if sym and day is not None and p and not sym.startswith("__"):
            d = int(day)
            sim_close[sym][d] = float(p)
            row_indices[sym][d] = i

    fixed = 0

    for sym in sorted(sim_close.keys()):
        if target_syms and sym not in target_syms:
            continue
        if sym not in real_data:
            continue

        real_rows = sorted(real_data[sym], key=lambda x: x.get("date", ""))
        sim_days = sorted(sim_close[sym].keys())
        if len(sim_days) < 2:
            continue

        base_day = sim_days[0]
        base_sim = sim_close[sym][base_day]
        if base_sim <= 0:
            continue

        # Real base
        base_ri = base_day - 1
        if base_ri < 0 or base_ri >= len(real_rows):
            continue
        base_real = real_rows[base_ri].get("close")
        if not base_real or base_real <= 0:
            continue

        # Find last overlapping day (sim day d -> real index d-1)
        import math
        last_overlap_day = None
        for d in reversed(sim_days):
            ri = d - 1
            if 0 <= ri < len(real_rows):
                rc = real_rows[ri].get("close")
                if rc and rc > 0:
                    last_overlap_day = d
                    break
        if last_overlap_day is None:
            continue

        last_ri = last_overlap_day - 1
        last_real = real_rows[last_ri]["close"]
        last_sim = sim_close[sym][last_overlap_day]
        if last_sim <= 0:
            continue

        # 归一化终点
        norm_sim_end = last_sim / base_sim
        norm_real_end = last_real / base_real

        # 需要的总漂移修正（log 比值差）
        log_drift_gap = math.log(norm_real_end) - math.log(norm_sim_end)
        # 按 strength 缩放
        target_log_drift = log_drift_gap * args.strength

        # 分摊到所有交易日（不只是 overlap 部分）
        n_intervals = len(sim_days) - 1
        if n_intervals <= 0:
            continue
        daily_log_delta = target_log_drift / n_intervals

        print(f"  {sym}: sim_end_norm={norm_sim_end:.4f} real_end_norm={norm_real_end:.4f} "
              f"log_gap={log_drift_gap:+.4f} daily_delta={daily_log_delta:+.6f}")

        # Apply: accumulate log delta day by day
        for step, d in enumerate(sim_days):
            if step == 0:
                continue  # keep base price unchanged
            cumulative_factor = math.exp(daily_log_delta * step)
            old_price = sim_close[sym][d]
            new_price = old_price * cumulative_factor

            idx = row_indices[sym][d]
            ratio = new_price / old_price if old_price > 0 else 1.0
            rows[idx]["last_price"] = round(new_price, 6)
            for k in ("vwap", "best_bid", "best_ask"):
                if k in rows[idx] and rows[idx][k]:
                    rows[idx][k] = round(float(rows[idx][k]) * ratio, 6)
            fixed += 1

    with open(snap_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nTrend injection (strength={args.strength}): modified {fixed} entries")


if __name__ == "__main__":
    main()
