#!/usr/bin/env python3
"""查看 tom2 的 market_snapshots 数据结构和前 55 天价格。"""
import json
from collections import defaultdict

run = "runs/20260323_213251_tom2"
rows = []
with open(f"{run}/market_snapshots.jsonl") as f:
    for line in f:
        rows.append(json.loads(line))

# 按 trading_day 取最后一条 snapshot（收盘价）
by_day = {}
for r in rows:
    d = r.get("trading_day", 0)
    by_day[d] = r

days = sorted(by_day.keys())
print(f"Total days: {len(days)}, range: {days[0]}-{days[-1]}")
print()

# 看第一条记录的 keys
r0 = by_day[days[0]]
print(f"Keys: {sorted(r0.keys())}")
print()

# 输出前 55 天每天各符号的收盘价
for d in days[:55]:
    r = by_day[d]
    prices = r.get("prices", r.get("close_prices", r.get("market_prices", {})))
    if isinstance(prices, dict) and prices:
        syms = sorted(prices.keys())
        vals = "  ".join(f"{s}={prices[s]:.2f}" for s in syms[:5])
        print(f"Day {d:3d}: {vals} ...")
    else:
        # 尝试其他字段
        for k in ["last_price", "price", "index_value", "composite_index"]:
            v = r.get(k)
            if v is not None:
                print(f"Day {d:3d}: {k}={v}")
                break
        else:
            print(f"Day {d:3d}: (no price field found)")
