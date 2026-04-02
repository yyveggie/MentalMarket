#!/usr/bin/env python3
"""从 trades.jsonl 重建 market_snapshots.jsonl 中的 last_price。

用每天每个 symbol 最后一笔成交价还原 last_price/vwap/best_bid/best_ask。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def main():
    run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")

    trades_path = run_dir / "trades.jsonl"
    snap_path = run_dir / "market_snapshots.jsonl"

    if not trades_path.exists():
        raise SystemExit(f"trades.jsonl not found in {run_dir}")

    # Build last trade price per (symbol, trading_day)
    # Use the last trade by sim_time for each (symbol, day)
    last_trade: dict[str, dict[int, tuple[float, float]]] = defaultdict(dict)  # sym -> {day: (sim_time, price)}
    with open(trades_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            t = json.loads(line)
            sym = t.get("symbol", "")
            day = t.get("trading_day")
            st = t.get("sim_time", 0)
            price = t.get("price")
            if sym and day is not None and price:
                day = int(day)
                prev = last_trade[sym].get(day)
                if prev is None or st >= prev[0]:
                    last_trade[sym][day] = (st, float(price))

    # Also compute VWAP per (symbol, day)
    vwap_data: dict[str, dict[int, tuple[float, float]]] = defaultdict(dict)  # sym -> {day: (sum_pq, sum_q)}
    with open(trades_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            t = json.loads(line)
            sym = t.get("symbol", "")
            day = t.get("trading_day")
            price = t.get("price")
            qty = t.get("quantity", 0)
            if sym and day is not None and price and qty > 0:
                day = int(day)
                prev = vwap_data[sym].get(day, (0.0, 0.0))
                vwap_data[sym][day] = (prev[0] + float(price) * qty, prev[1] + qty)

    # Read snapshots and restore prices
    rows = []
    with open(snap_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    fixed = 0
    for r in rows:
        sym = r.get("symbol", "")
        day = r.get("trading_day")
        if not sym or day is None or sym.startswith("__"):
            continue
        day = int(day)
        trade = last_trade.get(sym, {}).get(day)
        if trade:
            orig_price = float(r.get("last_price", 0))
            new_price = trade[1]
            if abs(orig_price - new_price) > 1e-6:
                ratio = new_price / orig_price if orig_price > 0 else 1.0
                r["last_price"] = round(new_price, 6)
                # Restore vwap
                vd = vwap_data.get(sym, {}).get(day)
                if vd and vd[1] > 0:
                    r["vwap"] = round(vd[0] / vd[1], 6)
                # Scale bid/ask proportionally
                for k in ("best_bid", "best_ask"):
                    if k in r and r[k] and orig_price > 0:
                        r[k] = round(float(r[k]) * ratio, 6)
                fixed += 1

    with open(snap_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Restored {fixed} snapshot entries from trades.jsonl")


if __name__ == "__main__":
    main()
