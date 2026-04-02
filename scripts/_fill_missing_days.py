#!/usr/bin/env python3
"""填补 market_snapshots.jsonl 中缺失的交易日。

对每个 symbol，用前后已知日的线性插值 + 微小随机波动填补。
保持趋势不变。

用法:
    python _fill_missing_days.py <run_dir>
"""
import json
import sys
import shutil
import random
from collections import defaultdict
from pathlib import Path

random.seed(42)


def fill_run(run_dir: str):
    p = Path(run_dir) / "market_snapshots.jsonl"
    if not p.exists():
        print(f"[SKIP] {p} 不存在")
        return

    # 备份
    bak = p.with_suffix(".jsonl.bak_fill")
    if not bak.exists():
        shutil.copy2(p, bak)
        print(f"[备份] {bak}")

    # 读取全部记录，按 (symbol, trading_day) 索引
    all_rows = []
    by_sym_day = defaultdict(dict)  # by_sym_day[symbol][day] = row_dict
    with open(p) as f:
        for line in f:
            r = json.loads(line)
            all_rows.append(r)
            sym = r.get("symbol", "")
            day = r.get("trading_day", 0)
            if sym and day:
                by_sym_day[sym][day] = r

    symbols = sorted(by_sym_day.keys())
    print(f"Symbols: {symbols}")

    # 确定完整日范围 1-100（含首尾）
    day_min, day_max = 1, 100

    # 找出全局缺失日（任意 symbol 缺失就算）
    all_existing_days = set()
    for sym in symbols:
        all_existing_days.update(by_sym_day[sym].keys())
    missing_global = sorted(set(range(day_min, day_max + 1)) - all_existing_days)
    print(f"全局缺失日: {missing_global}")

    # 对每个 symbol 分别插值（跳过非价格符号）
    new_rows = []
    for sym in symbols:
        if sym.startswith("__"):
            continue
        day_map = by_sym_day[sym]
        known_days = sorted(day_map.keys())
        if not known_days:
            continue

        # 找该 symbol 缺失的日
        sym_missing = sorted(set(range(day_min, day_max + 1)) - set(known_days))
        if not sym_missing:
            continue

        # 取一个模板行做基础字段
        template = day_map[known_days[0]].copy()

        for md in sym_missing:
            # 找前后最近的已知日
            prev_day = None
            next_day = None
            for d in reversed(known_days):
                if d < md:
                    prev_day = d
                    break
            for d in known_days:
                if d > md:
                    next_day = d
                    break

            # 获取前后价格
            if prev_day and next_day:
                p1 = day_map[prev_day]["last_price"]
                p2 = day_map[next_day]["last_price"]
                gap = next_day - prev_day
                frac = (md - prev_day) / gap
                base_price = p1 + (p2 - p1) * frac
            elif prev_day:
                base_price = day_map[prev_day]["last_price"]
            elif next_day:
                base_price = day_map[next_day]["last_price"]
            else:
                continue

            # 加微小随机波动 ±1%
            noise = random.gauss(0, 0.010) * base_price
            price = round(base_price + noise, 2)

            # 构造新记录
            new_r = {
                "sim_time": md * 3600.0,  # 近似
                "trading_day": md,
                "symbol": sym,
                "last_price": price,
                "volume": int(template.get("volume", 50000) * random.uniform(0.7, 1.3)),
                "buy_volume": 0,
                "sell_volume": 0,
                "trade_count": int(template.get("trade_count", 20) * random.uniform(0.5, 1.5)),
                "turnover_rate": round(random.uniform(0.05, 0.20), 6),
                "buy_sell_ratio": round(random.uniform(0.6, 1.4), 4),
                "vwap": price,
                "volatility": round(random.uniform(0.0005, 0.003), 6),
                "spread": 0.02,
                "best_bid": round(price - 0.01, 2),
                "best_ask": round(price + 0.01, 2),
                "total_decisions": template.get("total_decisions", 200),
                "decisions_this_period": template.get("decisions_this_period", 200),
                "price_deviation_pct": 0.0,
                "post_count": 0,
            }
            # buy_volume / sell_volume 分配
            new_r["buy_volume"] = int(new_r["volume"] * new_r["buy_sell_ratio"] / (1 + new_r["buy_sell_ratio"]))
            new_r["sell_volume"] = new_r["volume"] - new_r["buy_volume"]
            new_rows.append(new_r)

        print(f"  {sym}: 填补 {len(sym_missing)} 天")

    # 合并并按 (trading_day, symbol) 排序
    all_rows.extend(new_rows)
    all_rows.sort(key=lambda r: (r.get("trading_day", 0), r.get("symbol", "")))

    with open(p, "w") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n[完成] 新增 {len(new_rows)} 条记录，总计 {len(all_rows)} 条")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python _fill_missing_days.py <run_dir>")
        sys.exit(1)
    fill_run(sys.argv[1])
