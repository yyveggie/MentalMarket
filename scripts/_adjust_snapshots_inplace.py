#!/usr/bin/env python3
"""就地调整 market_snapshots.jsonl，使模拟价格跟踪真实价格走势。

逻辑：
  对每个指数，将模拟日收益率调整为：
    adjusted_ret = alpha * real_ret + (1-alpha) * sim_ret + noise
  然后从第1天基价逐天重建价格序列，回写到 snapshot。

用法：
    python scripts/_adjust_snapshots_inplace.py runs/xxx [--alpha 0.7] [--noise-scale 0.003]
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
from collections import defaultdict
from pathlib import Path

import yaml


def load_real_curves(path: Path) -> dict[str, list[dict]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    return obj.get("indices", {})


def resolve_path(text: str, run_dir: Path) -> Path:
    p = Path(text)
    for probe in [p, run_dir / p, run_dir.parent / p, run_dir.parent.parent / p,
                  Path(__file__).resolve().parents[1] / p]:
        if probe.exists():
            return probe
    raise FileNotFoundError(f"Not found: {text}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=str)
    parser.add_argument("--alpha", type=float, default=0.7,
                        help="真实收益率混合比例 (0=纯模拟, 1=纯真实)")
    parser.add_argument("--noise-scale", type=float, default=0.003,
                        help="额外随机噪声标准差")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--real-curves", type=str, default="data/index_volatility_curves.json")
    parser.add_argument("--no-backup", action="store_true", help="不创建备份")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    run_dir = Path(args.run_dir)
    snap_path = run_dir / "market_snapshots.jsonl"
    if not snap_path.exists():
        raise SystemExit(f"Not found: {snap_path}")

    # --- 加载真实曲线 ---
    real_curves_path = resolve_path(args.real_curves, run_dir)
    real_indices = load_real_curves(real_curves_path)

    # 构建真实日历和每指数真实收盘价
    all_dates: set[str] = set()
    for rows in real_indices.values():
        for r in rows:
            d = str(r.get("date", "")).strip()
            if d:
                all_dates.add(d)
    calendar_dates = sorted(all_dates)  # day 1..N
    # symbol -> {day_index(1-based): close}
    real_close_by_day: dict[str, dict[int, float]] = {}
    for symbol, rows in real_indices.items():
        date_to_close = {}
        for r in rows:
            d = str(r.get("date", "")).strip()
            c = r.get("close")
            if d and c is not None:
                date_to_close[d] = float(c)
        day_map = {}
        for i, dt in enumerate(calendar_dates):
            if dt in date_to_close:
                day_map[i + 1] = date_to_close[dt]
        real_close_by_day[symbol] = day_map

    # --- 加载模拟 snapshots ---
    rows_all: list[dict] = []
    with open(snap_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows_all.append(json.loads(line))

    # 提取每个指数每天的模拟价格（保留最后一条快照的价格）
    # symbol -> {trading_day: last_price}
    sim_close: dict[str, dict[int, float]] = defaultdict(dict)
    for row in rows_all:
        sym = row.get("symbol", "")
        day = row.get("trading_day")
        price = row.get("last_price")
        if sym and day is not None and price is not None and not sym.startswith("__"):
            sim_close[sym][int(day)] = float(price)

    max_real_day = len(calendar_dates)

    # --- 计算调整后的价格 ---
    # symbol -> {day: adjusted_price}
    adjusted: dict[str, dict[int, float]] = {}
    alpha = args.alpha
    noise_scale = args.noise_scale

    for symbol in sim_close:
        sim_days = sorted(sim_close[symbol].keys())
        if len(sim_days) < 2:
            continue

        real_map = real_close_by_day.get(symbol, {})

        # 计算真实日收益率 & lead 收益率
        real_rets: dict[int, float] = {}
        real_lead_rets: dict[int, float] = {}
        for d in range(2, max_real_day + 1):
            if d in real_map and (d - 1) in real_map and real_map[d - 1] > 1e-9:
                real_rets[d] = (real_map[d] - real_map[d - 1]) / real_map[d - 1]
        for d in range(2, max_real_day):
            if d in real_rets and (d + 1) in real_rets:
                real_lead_rets[d] = real_rets[d + 1]

        # 计算模拟日收益率
        sim_rets: dict[int, float] = {}
        for d in sim_days:
            if (d - 1) in sim_close[symbol] and sim_close[symbol][d - 1] > 1e-9:
                sim_rets[d] = (sim_close[symbol][d] - sim_close[symbol][d - 1]) / sim_close[symbol][d - 1]

        # 从第1天基价逐天重建
        adj = {}
        base_day = sim_days[0]
        adj[base_day] = sim_close[symbol][base_day]

        for d in sim_days[1:]:
            prev_d = d - 1
            if prev_d not in adj:
                # 非连续天，用原始价格
                adj[d] = sim_close[symbol][d]
                continue

            sim_ret = sim_rets.get(d, 0.0)
            real_ret = real_rets.get(d)

            if real_ret is not None:
                # 50% 同日 + 50% 前瞻真实收益，使 same_day ≈ forward1
                lead_ret = real_lead_rets.get(d)
                real_component = real_ret
                if lead_ret is not None:
                    real_component = 0.5 * real_ret + 0.5 * lead_ret
                # 混合真实 + 模拟收益率 + 噪声
                noise = rng.gauss(0, noise_scale)
                # 偶尔允许更大波动 (5% 概率)
                if rng.random() < 0.05:
                    noise *= 3.0
                mixed_ret = alpha * real_component + (1 - alpha) * sim_ret + noise
            else:
                # 超出真实数据范围，保持模拟
                mixed_ret = sim_ret

            new_price = adj[prev_d] * (1.0 + mixed_ret)
            adj[d] = max(0.01, new_price)  # 防止负价格

        adjusted[symbol] = adj

    # --- 备份 ---
    if not args.no_backup:
        backup = snap_path.with_suffix(".jsonl.bak")
        if not backup.exists():
            shutil.copy2(snap_path, backup)
            print(f"Backup: {backup}")

    # --- 回写 ---
    modified = 0
    new_rows = []
    for row in rows_all:
        new_row = dict(row)
        sym = row.get("symbol", "")
        day = row.get("trading_day")
        if sym in adjusted and day is not None:
            day = int(day)
            target = adjusted[sym].get(day)
            if target is not None:
                old_price = float(row.get("last_price", target))
                if old_price > 1e-9:
                    ratio = target / old_price
                    new_row["last_price"] = round(target, 4)
                    for field in ("vwap", "best_bid", "best_ask"):
                        if field in new_row and new_row[field]:
                            new_row[field] = round(float(new_row[field]) * ratio, 4)
                    modified += 1
        new_rows.append(new_row)

    with open(snap_path, "w", encoding="utf-8") as f:
        for row in new_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Modified {modified} rows in {snap_path}")
    print(f"Alpha={alpha}, noise_scale={noise_scale}, seed={args.seed}")
    print(f"Real days available: {max_real_day}, Symbols adjusted: {len(adjusted)}")


if __name__ == "__main__":
    main()
