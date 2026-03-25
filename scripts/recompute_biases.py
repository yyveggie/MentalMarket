#!/usr/bin/env python3
"""
重计算行为偏差指标 (Recompute Behavioral Biases)

读取旧实验的 behavioral_biases.jsonl 和 trades.jsonl，
使用升级后的权威方法重新计算以下指标：
  1. PGR / PLR / DE_Odean  — Odean (1998)
  2. loss_trading_flag      — Barber & Odean (2001) 越亏越交易
  3. lsv_herding             — LSV (1992) 标准化
  4. recent_skewness         — Kumar (2009) 偏度
  5. lambda_estimate         — Kahneman & Tversky λ 系数

用法:
  python scripts/recompute_biases.py runs/20260322_132820_tom0
  python scripts/recompute_biases.py runs/20260322_132820_tom0 --output runs/20260322_132820_tom0/behavioral_biases_v2.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def build_price_history(trades: list[dict]) -> dict[str, list[tuple[float, float]]]:
    """按标的构建 (sim_time, price) 时序。"""
    history: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for t in trades:
        sym = t.get("symbol", "")
        if sym:
            history[sym].append((float(t["sim_time"]), float(t["price"])))
    for sym in history:
        history[sym].sort()
    return dict(history)


def get_recent_prices(
    price_history: dict[str, list[tuple[float, float]]],
    symbol: str,
    sim_time: float,
    window: int = 11,
) -> list[float]:
    """获取 sim_time 之前的最近 window 条价格。"""
    h = price_history.get(symbol, [])
    if not h:
        return []
    prices = [p for t, p in h if t <= sim_time]
    return prices[-window:]


def compute_skewness(prices: list[float]) -> float | None:
    if len(prices) < 4:
        return None
    returns = [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(1, len(prices))
        if prices[i - 1] > 0
    ]
    if len(returns) < 3:
        return None
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = var ** 0.5
    if std < 1e-12:
        return None
    skew = sum((r - mean) ** 3 for r in returns) / n / (std ** 3)
    return round(skew, 4)


def main():
    parser = argparse.ArgumentParser(description="重计算行为偏差指标")
    parser.add_argument("run_dir", help="实验目录路径 (如 runs/20260322_132820_tom0)")
    parser.add_argument("--output", default=None, help="输出文件路径 (默认: run_dir/behavioral_biases_v2.jsonl)")
    parser.add_argument("--oc-threshold", type=float, default=0.5, help="过度自信换手率阈值")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    bias_path = run_dir / "behavioral_biases.jsonl"
    trades_path = run_dir / "trades.jsonl"

    if not bias_path.exists():
        print(f"Error: {bias_path} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {bias_path} ...")
    biases = load_jsonl(bias_path)
    print(f"  → {len(biases)} records")

    price_history: dict[str, list[tuple[float, float]]] = {}
    if trades_path.exists():
        print(f"Loading {trades_path} ...")
        trades = load_jsonl(trades_path)
        print(f"  → {len(trades)} trades")
        price_history = build_price_history(trades)
    else:
        print(f"Warning: {trades_path} not found, skewness will not be computed")

    # --- 按 agent_id 排序然后按时间排序 ---
    biases.sort(key=lambda r: (r.get("sim_time", 0), r.get("agent_id", 0)))

    # --- 累计器 ---
    # PGR/PLR
    cum_ga: dict[int, int] = defaultdict(int)
    cum_la: dict[int, int] = defaultdict(int)
    cum_rg: dict[int, int] = defaultdict(int)
    cum_rl: dict[int, int] = defaultdict(int)

    # λ 系数
    gain_mags: dict[int, list[float]] = defaultdict(list)
    loss_mags: dict[int, list[float]] = defaultdict(list)

    # LSV: 按 (trading_day, symbol) 累计 buy/sell
    day_sym_actions: dict[tuple[int, str], dict[str, int]] = defaultdict(lambda: {"buy": 0, "sell": 0})
    day_total_actions: dict[int, dict[str, int]] = defaultdict(lambda: {"buy": 0, "sell": 0})

    # 第一遍: 累计 LSV 统计量
    for r in biases:
        day = int(r.get("trading_day", 0))
        sym = str(r.get("symbol", ""))
        action = str(r.get("action", ""))
        if action in ("buy", "sell") and sym:
            day_sym_actions[(day, sym)][action] += 1
            day_total_actions[day][action] += 1

    # 第二遍: 逐条重计算
    output_path = Path(args.output) if args.output else run_dir / "behavioral_biases_v2.jsonl"
    upgraded_count = 0

    with open(output_path, "w", encoding="utf-8") as out:
        for r in biases:
            aid = int(r.get("agent_id", 0))
            action = str(r.get("action", ""))
            status = str(r.get("status", ""))
            avg_buy = float(r.get("avg_buy_price", 0))
            target_price = float(r.get("target_price", 0))
            sym = str(r.get("symbol", ""))
            day = int(r.get("trading_day", 0))
            sim_time = float(r.get("sim_time", 0))
            position_qty = int(r.get("position_qty", 0))
            return_pct = float(r.get("cumulative_return_pct", 0))
            turnover = float(r.get("turnover_rate", 0))
            total_trades = int(r.get("daily_trade_count", 0))

            # --- 1. PGR / PLR ---
            if avg_buy > 0 and position_qty > 0:
                market_px = float(r.get("market_price", 0))
                if market_px > avg_buy:
                    cum_ga[aid] += 1
                elif market_px < avg_buy:
                    cum_la[aid] += 1

            is_sell_ok = action == "sell" and status == "ok" and avg_buy > 0
            if is_sell_ok and target_price > avg_buy:
                cum_rg[aid] += 1
            elif is_sell_ok and target_price < avg_buy:
                cum_rl[aid] += 1

            pgr = round(cum_rg[aid] / cum_ga[aid], 4) if cum_ga[aid] > 0 else None
            plr = round(cum_rl[aid] / cum_la[aid], 4) if cum_la[aid] > 0 else None
            de_odean = round(pgr - plr, 4) if pgr is not None and plr is not None else None
            r["pgr"] = pgr
            r["plr"] = plr
            r["de_odean"] = de_odean

            # --- 2. 过度自信: 越亏越交易 ---
            r["loss_trading_flag"] = return_pct < -3.0 and total_trades >= 10 and turnover > args.oc_threshold * 0.5

            # --- 3. LSV 羊群效应 ---
            lsv = None
            if action in ("buy", "sell") and sym:
                ds = day_sym_actions.get((day, sym))
                dt = day_total_actions.get(day)
                if ds and dt:
                    sb, ss = ds["buy"], ds["sell"]
                    st = sb + ss
                    tb, ts_ = dt["buy"], dt["sell"]
                    tt = tb + ts_
                    if st > 0 and tt > 0:
                        p_i = sb / st
                        p_bar = tb / tt
                        lsv = round(abs(p_i - p_bar), 4)
            r["lsv_herding"] = lsv

            # --- 4. 偏度 (彩票偏好) ---
            skewness = None
            if action == "buy" and status == "ok" and price_history:
                prices = get_recent_prices(price_history, sym, sim_time)
                skewness = compute_skewness(prices)
            r["recent_skewness"] = skewness
            r["positive_skew_flag"] = skewness is not None and skewness > 0.5

            # --- 5. λ 系数 ---
            if is_sell_ok and avg_buy > 0:
                pnl_pct = abs((target_price - avg_buy) / avg_buy * 100.0)
                if target_price > avg_buy:
                    gain_mags[aid].append(pnl_pct)
                    if len(gain_mags[aid]) > 200:
                        gain_mags[aid] = gain_mags[aid][-200:]
                else:
                    loss_mags[aid].append(pnl_pct)
                    if len(loss_mags[aid]) > 200:
                        loss_mags[aid] = loss_mags[aid][-200:]

            lam = None
            if gain_mags[aid] and loss_mags[aid]:
                avg_g = sum(gain_mags[aid]) / len(gain_mags[aid])
                avg_l = sum(loss_mags[aid]) / len(loss_mags[aid])
                if avg_g > 0.01:
                    lam = round(avg_l / avg_g, 4)
            r["lambda_estimate"] = lam

            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            upgraded_count += 1

    print(f"\nDone! {upgraded_count} records → {output_path}")

    # 统计摘要
    agents_with_de = sum(1 for a in set(cum_ga.keys()) | set(cum_la.keys())
                         if cum_ga.get(a, 0) > 0 and cum_la.get(a, 0) > 0)
    agents_with_lambda = sum(1 for a in gain_mags if gain_mags[a] and loss_mags.get(a))
    print(f"\nSummary:")
    print(f"  Agents with valid DE (PGR/PLR): {agents_with_de}")
    print(f"  Agents with valid λ estimate:   {agents_with_lambda}")
    lsv_count = sum(1 for r in biases if r.get("lsv_herding") is not None)
    skew_count = sum(1 for r in biases if r.get("recent_skewness") is not None)
    print(f"  Records with LSV herding:       {lsv_count}")
    print(f"  Records with skewness:          {skew_count}")


if __name__ == "__main__":
    main()
