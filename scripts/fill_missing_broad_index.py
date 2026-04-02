#!/usr/bin/env python3
"""补充 broad_index.jsonl 中缺失交易日的线性插值数据"""
import json
import sys

fpath = sys.argv[1]

with open(fpath, "r", encoding="utf-8") as f:
    rows = [json.loads(l) for l in f if l.strip()]

by_day = {r["trading_day"]: r for r in rows}
all_days = sorted(by_day.keys())
min_d, max_d = min(all_days), max(all_days)
missing = sorted(set(range(min_d, max_d + 1)) - set(all_days))

if not missing:
    print("没有缺失天数")
    sys.exit(0)

print(f"缺失天数: {missing}")

new_rows = []
for md in missing:
    # 找到前后存在的天
    prev_d = max(d for d in all_days if d < md)
    next_d = min(d for d in all_days if d > md)
    gap = next_d - prev_d
    t = (md - prev_d) / gap

    prev_r = by_day[prev_d]
    next_r = by_day[next_d]

    sim_time = round(prev_r["sim_time"] + t * (next_r["sim_time"] - prev_r["sim_time"]), 3)
    value = round(prev_r["value"] + t * (next_r["value"] - prev_r["value"]), 4)

    # pct_chg: 相对前一天
    if md - 1 in by_day:
        prev_val = by_day[md - 1]["value"]
    else:
        # 前一天也是插值的
        prev_interp = [r for r in new_rows if r["trading_day"] == md - 1]
        prev_val = prev_interp[0]["value"] if prev_interp else prev_r["value"]

    pct_chg = round((value - prev_val) / prev_val, 4) if prev_val > 0 else 0.0

    new_row = {
        "sim_time": sim_time,
        "value": value,
        "pct_chg": pct_chg,
        "trading_day": md,
    }
    new_rows.append(new_row)
    by_day[md] = new_row
    print(f"  Day {md}: value={value}, pct_chg={pct_chg}")

# 合并并按交易日排序写回
all_rows = rows + new_rows
all_rows.sort(key=lambda r: r["trading_day"])

with open(fpath, "w", encoding="utf-8") as f:
    for r in all_rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"已补充 {len(new_rows)} 天数据，总计 {len(all_rows)} 行")
