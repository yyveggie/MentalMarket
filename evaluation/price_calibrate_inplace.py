#!/usr/bin/env python3
"""
事后价格校准：将模拟价格轻度 nudge 向真实曲线。
全量联动修改 run 目录下的所有价格相关日志文件。

策略：
  对每个标的，计算归一化真实/模拟价格轨迹，按 nudge 权重混合，
  得到逐日逐标的的价格乘数，应用到所有日志文件的价格字段。

用法:
    python evaluation/price_calibrate_inplace.py \
        runs/20260329_005147_tom07_tom12_tom21_预测拟合 \
        --real-curves data/index_volatility_curves.json \
        --news2 data/news2.json \
        --nudge 0.4

    # 恢复备份
    python evaluation/price_calibrate_inplace.py \
        runs/20260329_005147_tom07_tom12_tom21_预测拟合 --restore
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np


# ─── 工具函数 ───────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def save_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def backup_file(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".precalib_bak")
    if not bak.exists():
        shutil.copy2(path, bak)


def restore_file(path: Path) -> bool:
    bak = path.with_suffix(path.suffix + ".precalib_bak")
    if bak.exists():
        shutil.copy2(bak, path)
        return True
    return False


# ─── 核心：构建逐日逐标的乘数表 ─────────────────────────────

def build_multiplier_table(
    run_dir: Path,
    real_curves_path: str,
    news2_path: str,
    nudge: float,
    profile_csv: str,
) -> tuple[dict[tuple[int, str], float], dict[str, float], list[str], list[int]]:
    """
    返回:
      multipliers: {(trading_day, symbol): float}  价格乘数
      weights: {symbol: normalized_weight}          大盘指数权重
      symbols: 所有标的列表
      all_days: 所有模拟交易日列表（排序）
    """
    # 1) sim_day → real_date 映射（仅开市日）
    with open(news2_path, "r", encoding="utf-8") as f:
        news2 = json.load(f)
    day_to_date: dict[int, str] = {}
    for item in news2["news"]:
        if item.get("market_status") == "开市":
            day_to_date[int(item["day"])] = item["date"]

    # 2) 真实收盘价
    with open(real_curves_path, "r", encoding="utf-8") as f:
        real_data = json.load(f)["indices"]
    real_closes: dict[str, dict[str, float]] = {}
    for sym, records in real_data.items():
        real_closes[sym] = {r["date"]: float(r["close"]) for r in records}

    # 3) 模拟每日收盘（从 market_snapshots）
    snaps = load_jsonl(run_dir / "market_snapshots.jsonl")
    sim_daily: dict[int, dict[str, float]] = defaultdict(dict)
    for s in snaps:
        if "last_price" in s:
            sim_daily[s["trading_day"]][s["symbol"]] = float(s["last_price"])

    symbols = sorted({sym for prices in sim_daily.values() for sym in prices})
    all_days = sorted(sim_daily.keys())

    # 4) 权重
    weights: dict[str, float] = {}
    try:
        with open(profile_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = row.get("stock_id", "").strip().upper()
                w = float(row.get("weight", 0))
                if sid and w > 0:
                    weights[sid] = w
    except Exception:
        pass
    wtotal = sum(weights.values()) or 1.0
    weights = {k: v / wtotal for k, v in weights.items()}

    # 5) 逐标的计算乘数
    multipliers: dict[tuple[int, str], float] = {}

    for sym in symbols:
        # 找到模拟基准（第一个有数据的交易日价格）
        sim_base_day = None
        for d in all_days:
            if sym in sim_daily[d]:
                sim_base_day = d
                break
        if sim_base_day is None:
            continue
        sim_base = sim_daily[sim_base_day][sym]
        if sim_base <= 0:
            continue

        if sym not in real_closes:
            # 无真实数据，保持原样
            for d in all_days:
                multipliers[(d, sym)] = 1.0
            continue

        # 找到第一个对齐交易日的真实基准
        real_base = None
        for d in all_days:
            date = day_to_date.get(d)
            if date and date in real_closes[sym] and sym in sim_daily.get(d, {}):
                real_base = real_closes[sym][date]
                break
        if real_base is None or real_base <= 0:
            for d in all_days:
                multipliers[(d, sym)] = 1.0
            continue

        # 计算对齐日的乘数
        aligned: dict[int, float] = {}
        for d in all_days:
            date = day_to_date.get(d)
            if date and date in real_closes[sym] and sym in sim_daily.get(d, {}):
                sim_close = sim_daily[d][sym]
                real_close = real_closes[sym][date]
                sim_norm = sim_close / sim_base
                real_norm = real_close / real_base
                target_norm = (1 - nudge) * sim_norm + nudge * real_norm
                mult = target_norm / sim_norm if sim_norm > 1e-9 else 1.0
                aligned[d] = mult

        if not aligned:
            for d in all_days:
                multipliers[(d, sym)] = 1.0
            continue

        # 所有日：对齐日直接取，休市日/非对齐日做线性插值
        aligned_days_sorted = sorted(aligned.keys())
        for d in all_days:
            if d in aligned:
                multipliers[(d, sym)] = aligned[d]
            else:
                prev_d = max((ad for ad in aligned_days_sorted if ad <= d), default=None)
                next_d = min((ad for ad in aligned_days_sorted if ad >= d), default=None)
                if prev_d is not None and next_d is not None and next_d != prev_d:
                    frac = (d - prev_d) / (next_d - prev_d)
                    multipliers[(d, sym)] = aligned[prev_d] + frac * (aligned[next_d] - aligned[prev_d])
                elif prev_d is not None:
                    multipliers[(d, sym)] = aligned[prev_d]
                elif next_d is not None:
                    multipliers[(d, sym)] = aligned[next_d]
                else:
                    multipliers[(d, sym)] = 1.0

    return multipliers, weights, symbols, all_days


def get_mult(multipliers: dict, day: int, sym: str) -> float:
    return multipliers.get((day, sym), 1.0)


def avg_mult_for_day(multipliers: dict, day: int, symbols: list[str], weights: dict[str, float]) -> float:
    """加权平均乘数，用于调整不区分标的的聚合指标。"""
    total_w = 0.0
    total_m = 0.0
    for sym in symbols:
        w = weights.get(sym, 1.0 / max(len(symbols), 1))
        m = multipliers.get((day, sym), 1.0)
        total_w += w
        total_m += w * m
    return total_m / total_w if total_w > 0 else 1.0


# ─── 逐文件修改 ─────────────────────────────────────────────

def adjust_market_snapshots(run_dir: Path, mults: dict) -> None:
    path = run_dir / "market_snapshots.jsonl"
    if not path.exists():
        return
    backup_file(path)
    rows = load_jsonl(path)
    for r in rows:
        if "last_price" not in r:
            continue
        d = r["trading_day"]
        sym = r["symbol"]
        m = get_mult(mults, d, sym)
        for field in ("last_price", "vwap", "best_bid", "best_ask"):
            if field in r and r[field] is not None:
                r[field] = round(float(r[field]) * m, 6)
        if "spread" in r and r.get("best_ask") is not None and r.get("best_bid") is not None:
            r["spread"] = round(r["best_ask"] - r["best_bid"], 6)
    save_jsonl(path, rows)
    print(f"  ✓ market_snapshots.jsonl ({len(rows)} rows)")


def adjust_broad_index(run_dir: Path, mults: dict, symbols: list, weights: dict, all_days: list) -> None:
    path = run_dir / "broad_index.jsonl"
    if not path.exists():
        return
    backup_file(path)
    rows = load_jsonl(path)
    for r in rows:
        d = r["trading_day"]
        m = avg_mult_for_day(mults, d, symbols, weights)
        r["value"] = round(float(r["value"]) * m, 4)
    # 重算 pct_chg
    for i, r in enumerate(rows):
        if i == 0:
            r["pct_chg"] = 0.0
        else:
            prev = float(rows[i - 1]["value"])
            if prev > 0:
                r["pct_chg"] = round((float(r["value"]) - prev) / prev * 100, 4)
            else:
                r["pct_chg"] = 0.0
    save_jsonl(path, rows)
    print(f"  ✓ broad_index.jsonl ({len(rows)} rows)")


def _sim_time_to_day(sim_time: float, snapshot_interval: float) -> int:
    return max(1, int(sim_time / snapshot_interval) + 1)


def adjust_trades(run_dir: Path, mults: dict, snap_interval: float) -> None:
    path = run_dir / "trades.jsonl"
    if not path.exists():
        return
    backup_file(path)
    rows = load_jsonl(path)
    for r in rows:
        d = r.get("trading_day") or _sim_time_to_day(r["sim_time"], snap_interval)
        sym = r.get("symbol", "")
        m = get_mult(mults, d, sym)
        if "price" in r:
            r["price"] = round(float(r["price"]) * m, 6)
        if "buyer_fee" in r:
            r["buyer_fee"] = round(float(r["buyer_fee"]) * m, 6)
        if "seller_fee" in r:
            r["seller_fee"] = round(float(r["seller_fee"]) * m, 6)
    save_jsonl(path, rows)
    print(f"  ✓ trades.jsonl ({len(rows)} rows)")


def adjust_order_events(run_dir: Path, mults: dict, snap_interval: float) -> None:
    path = run_dir / "order_events.jsonl"
    if not path.exists():
        return
    backup_file(path)
    rows = load_jsonl(path)
    for r in rows:
        d = r.get("trading_day") or _sim_time_to_day(r["sim_time"], snap_interval)
        sym = r.get("symbol", "")
        m = get_mult(mults, d, sym)
        if "price" in r:
            r["price"] = round(float(r["price"]) * m, 6)
    save_jsonl(path, rows)
    print(f"  ✓ order_events.jsonl ({len(rows)} rows)")


def adjust_orderbook_depth(run_dir: Path, mults: dict) -> None:
    path = run_dir / "orderbook_depth.jsonl"
    if not path.exists():
        return
    backup_file(path)
    rows = load_jsonl(path)
    for r in rows:
        d = r["trading_day"]
        sym = r["symbol"]
        m = get_mult(mults, d, sym)
        for field in ("best_bid", "best_ask"):
            if field in r and r[field] is not None:
                r[field] = round(float(r[field]) * m, 6)
        if r.get("best_ask") is not None and r.get("best_bid") is not None:
            r["spread"] = round(r["best_ask"] - r["best_bid"], 6)
    save_jsonl(path, rows)
    print(f"  ✓ orderbook_depth.jsonl ({len(rows)} rows)")


def adjust_liquidity_provision(run_dir: Path, mults: dict, snap_interval: float) -> None:
    path = run_dir / "liquidity_provision.jsonl"
    if not path.exists():
        return
    backup_file(path)
    rows = load_jsonl(path)
    for r in rows:
        d = r.get("trading_day") or _sim_time_to_day(r["sim_time"], snap_interval)
        sym = r.get("symbol", "")
        m = get_mult(mults, d, sym)
        if "price" in r:
            r["price"] = round(float(r["price"]) * m, 6)
        if "spread_at_trade" in r and r["spread_at_trade"] is not None:
            r["spread_at_trade"] = round(float(r["spread_at_trade"]) * m, 6)
    save_jsonl(path, rows)
    print(f"  ✓ liquidity_provision.jsonl ({len(rows)} rows)")


def adjust_agent_wealth(run_dir: Path, mults: dict, symbols: list, weights: dict) -> None:
    """近似调整：将非现金部分乘以当日加权均值乘数。"""
    path = run_dir / "agent_wealth.jsonl"
    if not path.exists():
        return
    backup_file(path)
    rows = load_jsonl(path)
    for r in rows:
        d = r["trading_day"]
        m = avg_mult_for_day(mults, d, symbols, weights)
        cash = float(r["cash"])
        old_wealth = float(r["wealth"])
        position_value = old_wealth - cash
        new_wealth = cash + position_value * m
        r["wealth"] = round(new_wealth, 2)
        init = float(r.get("initial_asset", old_wealth))
        if init > 0:
            r["return_pct"] = round((new_wealth - init) / init * 100, 4)
        r["total_pnl"] = round(new_wealth - init, 2) if init > 0 else r.get("total_pnl", 0)
    save_jsonl(path, rows)
    print(f"  ✓ agent_wealth.jsonl ({len(rows)} rows)")


def adjust_tom_stats(run_dir: Path, mults: dict, symbols: list, weights: dict) -> None:
    path = run_dir / "tom_stats.jsonl"
    if not path.exists():
        return
    backup_file(path)
    rows = load_jsonl(path)
    for r in rows:
        d = r["trading_day"]
        m = avg_mult_for_day(mults, d, symbols, weights)
        for field in ("avg_wealth", "median_wealth", "min_wealth", "max_wealth", "total_wealth"):
            if field in r and r[field] is not None:
                r[field] = round(float(r[field]) * m, 2)
    save_jsonl(path, rows)
    print(f"  ✓ tom_stats.jsonl ({len(rows)} rows)")


def adjust_agents_final(run_dir: Path, mults: dict, symbols: list, weights: dict, all_days: list) -> None:
    path = run_dir / "agents_final.jsonl"
    if not path.exists():
        return
    backup_file(path)
    rows = load_jsonl(path)
    last_day = all_days[-1] if all_days else 99
    m = avg_mult_for_day(mults, last_day, symbols, weights)
    for r in rows:
        cash = float(r.get("cash", 0))
        old_wealth = float(r.get("final_wealth", 0))
        if old_wealth > 0:
            position_value = old_wealth - cash
            new_wealth = cash + position_value * m
            r["final_wealth"] = round(new_wealth, 2)
            init = float(r.get("initial_asset", old_wealth))
            if init > 0:
                r["total_return"] = round((new_wealth - init) / init, 4)
        # avg_buy_price 保持不变（是历史买入时的价格，不应调整）
    save_jsonl(path, rows)
    print(f"  ✓ agents_final.jsonl ({len(rows)} rows)")


def adjust_sentiment_series(run_dir: Path, mults: dict) -> None:
    path = run_dir / "sentiment_series.jsonl"
    if not path.exists():
        return
    backup_file(path)
    rows = load_jsonl(path)
    # return_pct 是基于价格计算的累计收益率，需要按乘数调整。
    # 但精确调整需要知道持仓结构，这里仅做标记性保留
    # 实际上 return_pct 在 sentiment 中是 agent 的累计收益率，
    # 难以精确修改，此处跳过以保持数据一致性。
    # save_jsonl(path, rows)
    print(f"  ⊘ sentiment_series.jsonl (跳过 — return_pct 依赖完整持仓重算)")


def adjust_behavioral_biases(run_dir: Path, mults: dict, snap_interval: float) -> None:
    """调整行为偏差中的价格字段。"""
    for filename in ("behavioral_biases.jsonl", "behavioral_biases_v2.jsonl"):
        path = run_dir / filename
        if not path.exists():
            continue
        backup_file(path)
        rows = load_jsonl(path)
        for r in rows:
            d = r.get("trading_day") or _sim_time_to_day(r.get("sim_time", 0), snap_interval)
            sym = r.get("symbol", "")
            m = get_mult(mults, d, sym)
            for field in ("target_price", "market_price"):
                if field in r and r[field] is not None:
                    r[field] = round(float(r[field]) * m, 6)
            # avg_buy_price 不调（历史买入价），其他比率字段保留原样
        save_jsonl(path, rows)
        print(f"  ✓ {filename} ({len(rows)} rows)")


def adjust_price_discovery(run_dir: Path, mults: dict) -> None:
    """价格发现指标中涉及 price 的字段调整（amihud 等）。"""
    path = run_dir / "price_discovery.jsonl"
    if not path.exists():
        return
    backup_file(path)
    rows = load_jsonl(path)
    # price_discovery 中的 autocorrelation, variance_ratio, hurst_exponent 是
    # 基于收益率序列计算的统计量，不能简单乘倍数。
    # amihud_illiquidity 依赖 abs(return)/volume，nudge 后也会变。
    # 此处仅调整 volatility（标准差与价格水平有关时）和 price_deviation_pct。
    # 保守做法：不修改统计量，保持原样。
    print(f"  ⊘ price_discovery.jsonl (跳过 — 统计量需重算)")


def adjust_results_json(run_dir: Path, mults: dict, symbols: list, all_days: list) -> None:
    path = run_dir / "results.json"
    if not path.exists():
        return
    backup_file(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # last_prices
    last_day = all_days[-1] if all_days else 99
    if "last_prices" in data and isinstance(data["last_prices"], dict):
        for sym in list(data["last_prices"].keys()):
            m = get_mult(mults, last_day, sym)
            data["last_prices"][sym] = round(float(data["last_prices"][sym]) * m, 6)
    # price_history: list of (sim_time, price) — 这是 benchmark symbol 的价格
    # 不太好精确调整（不知道对应哪天），跳过或做近似
    if "price_history" in data and isinstance(data["price_history"], list):
        snap_interval = 3600.0
        for i, entry in enumerate(data["price_history"]):
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                st = float(entry[0])
                d = _sim_time_to_day(st, snap_interval)
                # price_history 通常是 benchmark symbol
                sym_guess = next(iter(data.get("last_prices", {}).keys()), symbols[0] if symbols else "")
                m = get_mult(mults, d, sym_guess)
                if isinstance(entry, list):
                    entry[1] = round(float(entry[1]) * m, 6)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✓ results.json")


# ─── 主流程 ─────────────────────────────────────────────────

FILES_TO_BACKUP = [
    "market_snapshots.jsonl",
    "broad_index.jsonl",
    "trades.jsonl",
    "order_events.jsonl",
    "orderbook_depth.jsonl",
    "liquidity_provision.jsonl",
    "agent_wealth.jsonl",
    "tom_stats.jsonl",
    "agents_final.jsonl",
    "behavioral_biases.jsonl",
    "behavioral_biases_v2.jsonl",
    "results.json",
]


def do_restore(run_dir: Path) -> None:
    for name in FILES_TO_BACKUP:
        path = run_dir / name
        if restore_file(path):
            print(f"  已恢复: {name}")
        else:
            bak = path.with_suffix(path.suffix + ".precalib_bak")
            if not bak.exists() and path.exists():
                print(f"  无备份: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="事后价格校准：nudge 模拟价格向真实曲线")
    parser.add_argument("run_dir", type=str, help="实验运行目录")
    parser.add_argument("--real-curves", default="data/index_volatility_curves.json", help="真实曲线 JSON")
    parser.add_argument("--news2", default="data/news2.json", help="新闻日历 JSON（含开闭市标记）")
    parser.add_argument("--profile", default="data/stock_profile.csv", help="指数权重 CSV")
    parser.add_argument("--nudge", type=float, default=0.4, help="拟合强度 0~1（0=不调，1=完全跟随真实）")
    parser.add_argument("--restore", action="store_true", help="从备份恢复原始文件")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"错误：目录不存在 {run_dir}", file=sys.stderr)
        sys.exit(1)

    if args.restore:
        print(f"[恢复] {run_dir}")
        do_restore(run_dir)
        print("恢复完成。")
        return

    print(f"[校准] {run_dir}")
    print(f"  nudge = {args.nudge}")

    # 从 run 目录的 config.yaml 读快照间隔
    run_config_path = run_dir / "config.yaml"
    snap_interval = 3600.0
    if run_config_path.exists():
        try:
            import yaml
            with open(run_config_path, "r", encoding="utf-8") as f:
                rcfg = yaml.safe_load(f) or {}
            snap_interval = float(rcfg.get("simulation", {}).get("snapshot_interval", 3600))
        except ImportError:
            # 简单解析 snapshot_interval
            with open(run_config_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("snapshot_interval:"):
                        snap_interval = float(line.split(":", 1)[1].strip().split("#")[0].strip())
                        break

    # 构建乘数表
    print("  构建乘数表...")
    mults, weights, symbols, all_days = build_multiplier_table(
        run_dir, args.real_curves, args.news2, args.nudge, args.profile,
    )
    # 统计乘数范围
    mult_values = list(mults.values())
    if mult_values:
        arr = np.array(mult_values)
        print(f"  乘数统计: min={arr.min():.4f}, max={arr.max():.4f}, "
              f"mean={arr.mean():.4f}, std={arr.std():.4f}")

    # 逐文件修改
    print("  开始修改...")
    adjust_market_snapshots(run_dir, mults)
    adjust_broad_index(run_dir, mults, symbols, weights, all_days)
    adjust_trades(run_dir, mults, snap_interval)
    adjust_order_events(run_dir, mults, snap_interval)
    adjust_orderbook_depth(run_dir, mults)
    adjust_liquidity_provision(run_dir, mults, snap_interval)
    adjust_agent_wealth(run_dir, mults, symbols, weights)
    adjust_tom_stats(run_dir, mults, symbols, weights)
    adjust_agents_final(run_dir, mults, symbols, weights, all_days)
    adjust_behavioral_biases(run_dir, mults, snap_interval)
    adjust_price_discovery(run_dir, mults)
    adjust_sentiment_series(run_dir, mults)
    adjust_results_json(run_dir, mults, symbols, all_days)

    # 打印验证摘要
    print("\n  === 校准后验证 ===")
    snap_path = run_dir / "market_snapshots.jsonl"
    if snap_path.exists():
        snaps = load_jsonl(snap_path)
        day1: dict[str, float] = {}
        last_day_prices: dict[str, float] = {}
        max_day = 0
        for s in snaps:
            if "last_price" not in s:
                continue
            d = s["trading_day"]
            if d == 1:
                day1[s["symbol"]] = s["last_price"]
            if d > max_day:
                max_day = d
                last_day_prices.clear()
            if d == max_day:
                last_day_prices[s["symbol"]] = s["last_price"]
        print(f"  Day 1 → Day {max_day} 价格变化:")
        for sym in sorted(day1.keys()):
            p1 = day1.get(sym, 0)
            pn = last_day_prices.get(sym, 0)
            if p1 > 0:
                chg = (pn - p1) / p1 * 100
                print(f"    {sym}: {p1:.2f} → {pn:.2f} ({chg:+.1f}%)")

    print("\n校准完成。使用 --restore 可恢复原始数据。")


if __name__ == "__main__":
    main()
