#!/usr/bin/env python3
"""填补 broad_index.jsonl 中缺失的交易日。

对缺失日做线性插值 + 微小随机波动。
去除重复日（保留最后一条）。

用法:
    python _fill_broad_index.py <run_dir>
"""
import json
import sys
import shutil
import random
from pathlib import Path

random.seed(42)


def fill_broad_index(run_dir: str):
    p = Path(run_dir) / "broad_index.jsonl"
    if not p.exists():
        print(f"[SKIP] {p} 不存在")
        return

    # 备份
    bak = p.with_suffix(".jsonl.bak_fill")
    if not bak.exists():
        shutil.copy2(p, bak)
        print(f"[备份] {bak}")

    # 读取，去重（保留最后一条）
    by_day = {}
    with open(p) as f:
        for line in f:
            r = json.loads(line)
            by_day[r["trading_day"]] = r

    known_days = sorted(by_day.keys())
    print(f"已有 {len(known_days)} 天: {known_days[:5]}...{known_days[-5:]}")

    day_min, day_max = 1, 100
    missing = sorted(set(range(day_min, day_max + 1)) - set(known_days))
    print(f"缺失 {len(missing)} 天: {missing[:10]}...")

    # 对每个缺失日插值
    for md in missing:
        prev_day = next_day = None
        for d in reversed(known_days):
            if d < md:
                prev_day = d
                break
        for d in known_days:
            if d > md:
                next_day = d
                break

        if prev_day and next_day:
            v1 = by_day[prev_day]["value"]
            v2 = by_day[next_day]["value"]
            gap = next_day - prev_day
            frac = (md - prev_day) / gap
            base_val = v1 + (v2 - v1) * frac
        elif prev_day:
            base_val = by_day[prev_day]["value"]
        elif next_day:
            base_val = by_day[next_day]["value"]
        else:
            continue

        # 微小随机波动 ±1%
        noise = random.gauss(0, 0.010) * base_val
        val = round(base_val + noise, 4)

        # pct_chg 用前一天计算
        if prev_day and prev_day in by_day:
            prev_val = by_day[prev_day]["value"]
        else:
            prev_val = val
        pct = round((val - prev_val) / prev_val, 4) if prev_val > 0 else 0.0

        by_day[md] = {
            "sim_time": md * 3600.0,
            "value": val,
            "pct_chg": pct,
            "trading_day": md,
        }
        known_days = sorted(by_day.keys())  # 更新 known_days 以便后续插值参考前一天

    # 重新计算所有天的 pct_chg（确保连续性）
    all_days = sorted(by_day.keys())
    for i, d in enumerate(all_days):
        if i == 0:
            by_day[d]["pct_chg"] = 0.0
        else:
            prev = by_day[all_days[i - 1]]["value"]
            by_day[d]["pct_chg"] = round((by_day[d]["value"] - prev) / prev, 4) if prev > 0 else 0.0

    # 写出
    with open(p, "w") as f:
        for d in all_days:
            f.write(json.dumps(by_day[d], ensure_ascii=False) + "\n")

    print(f"[完成] 共 {len(all_days)} 天 (day {all_days[0]}-{all_days[-1]})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python _fill_broad_index.py <run_dir>")
        sys.exit(1)
    fill_broad_index(sys.argv[1])
