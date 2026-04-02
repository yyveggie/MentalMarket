#!/usr/bin/env python3
"""平滑 market_snapshots.jsonl 中的异常价格跳变。

对日收益率绝对值 > threshold 的天数，用前后两天价格的线性插值替代。
只修改 last_price/vwap/best_bid/best_ask。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def main():
    run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 0.08
    max_passes = 20

    snap_path = run_dir / "market_snapshots.jsonl"

    rows = []
    with open(snap_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    total_fixes = 0
    for pass_num in range(1, max_passes + 1):
        # 收集每个 symbol 的 day -> last_price（取最后一条快照）
        close_map: dict[str, dict[int, float]] = defaultdict(dict)
        for r in rows:
            sym = r.get("symbol", "")
            day = r.get("trading_day")
            p = r.get("last_price")
            if sym and day is not None and p is not None and not sym.startswith("__"):
                close_map[sym][int(day)] = float(p)

        # 找需要平滑的 (symbol, day)
        fix_targets: dict[str, dict[int, float]] = {}  # sym -> {day: new_price}
        for sym in sorted(close_map):
            days = sorted(close_map[sym].keys())
            for i in range(1, len(days)):
                d_prev, d_cur = days[i - 1], days[i]
                p_prev, p_cur = close_map[sym][d_prev], close_map[sym][d_cur]
                ret = (p_cur - p_prev) / p_prev if abs(p_prev) > 1e-9 else 0
                if abs(ret) > threshold:
                    d_next_idx = i + 1
                    if d_next_idx < len(days):
                        d_next = days[d_next_idx]
                        p_next = close_map[sym][d_next]
                        new_price = (p_prev + p_next) / 2.0
                    else:
                        new_price = p_prev
                    if sym not in fix_targets:
                        fix_targets[sym] = {}
                    fix_targets[sym][d_cur] = new_price
                    print(f"  pass{pass_num} FIX {sym} day{d_cur}: {p_cur:.4f} -> {new_price:.4f}")

        if not fix_targets:
            print(f"Pass {pass_num}: no anomalies, done.")
            break

        n_fix = sum(len(v) for v in fix_targets.values())
        total_fixes += n_fix
        print(f"Pass {pass_num}: fixed {n_fix} entries")

        # 应用修复到 rows（就地更新，下一轮重新检测）
        for r in rows:
            sym = r.get("symbol", "")
            day = r.get("trading_day")
            if sym and day is not None and sym in fix_targets:
                day = int(day)
                new_p = fix_targets[sym].get(day)
                if new_p is not None:
                    old_p = float(r.get("last_price") or new_p)
                    if old_p > 0:
                        ratio = new_p / old_p
                        r["last_price"] = round(new_p, 6)
                        for k in ("vwap", "best_bid", "best_ask"):
                            if k in r and r[k]:
                                r[k] = round(float(r[k]) * ratio, 6)

    # 写回（不覆盖 bak）
    with open(snap_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Total fixed: {total_fixes} day-symbol entries across all passes. Saved to {snap_path}")


if __name__ == "__main__":
    main()
