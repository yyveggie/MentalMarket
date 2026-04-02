#!/usr/bin/env python3
"""查看 tom2 的大盘指数（各 symbol 均价）逐日数据，找出缺失日。"""
import json
from collections import defaultdict

run = "runs/20260323_213251_tom2"

# 每个 symbol 每天的收盘价
prices = defaultdict(dict)  # prices[symbol][day] = last_price

with open(f"{run}/market_snapshots.jsonl") as f:
    for line in f:
        r = json.loads(line)
        sym = r.get("symbol", "")
        day = r.get("trading_day", 0)
        lp = r.get("last_price")
        if sym and day and lp is not None:
            prices[sym][day] = lp

symbols = sorted(prices.keys())
print(f"Symbols: {symbols}")
print(f"Symbol count: {len(symbols)}")
print()

# 大盘指数 = 所有 symbol 均价
all_days = set()
for s in symbols:
    all_days.update(prices[s].keys())
all_days = sorted(all_days)
print(f"Days with data: {len(all_days)}")
print(f"Day range: {all_days[0]}-{all_days[-1]}")

# 找缺失日
full_range = set(range(all_days[0], all_days[-1] + 1))
missing = sorted(full_range - set(all_days))
print(f"Missing days: {missing}")
print()

# 输出每天的大盘指数（均价）
print("Day  Index   Symbols_Present")
for d in range(1, 101):
    day_prices = [prices[s][d] for s in symbols if d in prices[s]]
    if day_prices:
        avg = sum(day_prices) / len(day_prices)
        print(f"{d:3d}  {avg:7.3f}  ({len(day_prices)}/{len(symbols)})")
    else:
        print(f"{d:3d}  -------  MISSING")
