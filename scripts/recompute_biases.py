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
from typing import Any


def as_float(v: object, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def as_int(v: object, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


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


def extract_action_symbols(action_executed: Any) -> set[str]:
    symbols: set[str] = set()
    if not isinstance(action_executed, dict):
        return symbols

    sym = str(action_executed.get("symbol", "")).strip()
    if sym:
        symbols.add(sym)

    sub_orders = action_executed.get("sub_orders")
    if isinstance(sub_orders, list):
        for sub in sub_orders:
            if not isinstance(sub, dict):
                continue
            sub_sym = str(sub.get("symbol", "")).strip()
            if sub_sym:
                symbols.add(sub_sym)

    return symbols


def load_decision_snapshots(decisions_path: Path) -> dict[int, list[dict[str, Any]]]:
    timelines: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if not decisions_path.exists():
        return {}

    seq = 0
    with open(decisions_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            seq += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            aid = as_int(rec.get("agent_id"), -1)
            sim_time = as_float(rec.get("sim_time"), -1.0)
            if aid < 0 or sim_time < 0:
                continue

            snap = rec.get("agent_snapshot")
            if not isinstance(snap, dict):
                continue

            pos_raw = snap.get("positions")
            avg_raw = snap.get("avg_buy_price_by_symbol")
            if not isinstance(pos_raw, dict) or not isinstance(avg_raw, dict):
                continue

            positions: dict[str, int] = {}
            for k, v in pos_raw.items():
                key = str(k).strip()
                if not key:
                    continue
                positions[key] = as_int(v, 0)

            avg_buy_map: dict[str, float] = {}
            for k, v in avg_raw.items():
                key = str(k).strip()
                if not key:
                    continue
                avg_buy_map[key] = as_float(v, 0.0)

            timelines[aid].append(
                {
                    "sim_time": sim_time,
                    "seq": seq,
                    "positions": positions,
                    "avg_buy": avg_buy_map,
                    "symbols": extract_action_symbols(rec.get("action_executed")),
                }
            )

    for aid in timelines:
        timelines[aid].sort(key=lambda x: (x["sim_time"], x["seq"]))

    return dict(timelines)


def pick_snapshot_for_row(
    timeline: list[dict[str, Any]],
    cursor: int,
    sim_time: float,
    symbol: str,
) -> tuple[int, dict[str, Any] | None]:
    if not timeline:
        return cursor, None

    i = cursor
    n = len(timeline)
    while i + 1 < n and float(timeline[i + 1]["sim_time"]) <= sim_time + 1e-9:
        i += 1

    if i < 0 or float(timeline[i]["sim_time"]) > sim_time + 1e-9:
        return i, None

    chosen = timeline[i]

    # 同一 sim_time 可能有多条决策，优先匹配包含当前 symbol 的决策快照。
    if symbol and abs(float(chosen["sim_time"]) - sim_time) <= 1e-6:
        j = i
        while j >= 0 and abs(float(timeline[j]["sim_time"]) - sim_time) <= 1e-6:
            if symbol in timeline[j].get("symbols", set()):
                chosen = timeline[j]
                break
            j -= 1

    return i, chosen


def main():
    parser = argparse.ArgumentParser(description="重计算行为偏差指标")
    parser.add_argument("run_dir", help="实验目录路径 (如 runs/20260322_132820_tom0)")
    parser.add_argument("--output", default=None, help="输出文件路径 (默认: run_dir/behavioral_biases_v2.jsonl)")
    parser.add_argument("--oc-threshold", type=float, default=0.5, help="过度自信换手率阈值")
    parser.add_argument(
        "--allow-missing-snapshot",
        action="store_true",
        help="允许缺失决策快照时降级为0机会集（默认严格模式：缺失即报错）",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    bias_path = run_dir / "behavioral_biases.jsonl"
    trades_path = run_dir / "trades.jsonl"
    decisions_path = run_dir / "decisions.jsonl"

    if not bias_path.exists():
        print(f"Error: {bias_path} not found", file=sys.stderr)
        sys.exit(1)
    if not decisions_path.exists():
        print(f"Error: {decisions_path} not found (strict snapshot reconstruction required)", file=sys.stderr)
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

    print(f"Loading {decisions_path} ...")
    decision_snapshots = load_decision_snapshots(decisions_path)
    decision_snapshot_rows = sum(len(v) for v in decision_snapshots.values())
    print(f"  → {decision_snapshot_rows} snapshots for {len(decision_snapshots)} agents")
    if decision_snapshot_rows == 0:
        print("Error: no usable snapshots in decisions.jsonl", file=sys.stderr)
        sys.exit(1)

    # --- 按 sim_time, agent_id 排序，近似复现在线时序 ---
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

    # 交易次数：日志中无 total_trade_count，使用累计成功成交笔数近似。
    cumulative_ok_trades: dict[int, int] = defaultdict(int)

    # 运行态近似：维护全市场最近价格，用于评估未卖出持仓盈亏状态。
    latest_market_by_symbol: dict[str, float] = {}

    # 决策快照游标：用于高效按时序匹配每个 agent 的最近快照。
    decision_cursor: dict[int, int] = defaultdict(lambda: -1)
    missing_snapshot_count = 0

    # 与在线逻辑一致：LSV 使用全局累计买卖占比，并在当前动作写入前计算。
    global_peer_actions: dict[str, int] = {"buy": 0, "sell": 0}
    symbol_peer_actions: dict[str, dict[str, int]] = defaultdict(lambda: {"buy": 0, "sell": 0})

    # 第二遍: 逐条重计算
    output_path = Path(args.output) if args.output else run_dir / "behavioral_biases_v2.jsonl"
    upgraded_count = 0

    with open(output_path, "w", encoding="utf-8") as out:
        for r in biases:
            aid = as_int(r.get("agent_id"), 0)
            action = str(r.get("action", ""))
            status = str(r.get("status", ""))
            avg_buy = as_float(r.get("avg_buy_price"), 0.0)
            target_price = as_float(r.get("target_price"), 0.0)
            sym = str(r.get("symbol", ""))
            sim_time = as_float(r.get("sim_time"), 0.0)
            position_qty = as_int(r.get("position_qty"), 0)
            return_pct = as_float(r.get("cumulative_return_pct"), 0.0)
            turnover = as_float(r.get("turnover_rate"), 0.0)
            market_px = as_float(r.get("market_price"), 0.0)

            if sym and market_px > 0:
                latest_market_by_symbol[sym] = market_px

            timeline = decision_snapshots.get(aid, [])
            cur, snapshot = pick_snapshot_for_row(
                timeline=timeline,
                cursor=decision_cursor[aid],
                sim_time=sim_time,
                symbol=sym,
            )
            decision_cursor[aid] = cur

            if snapshot is None:
                missing_snapshot_count += 1
                if not args.allow_missing_snapshot:
                    print(
                        f"Error: snapshot not found for agent={aid} sim_time={sim_time:.3f} symbol={sym}",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            positions_map = snapshot.get("positions", {}) if snapshot else {}
            avg_buy_map = snapshot.get("avg_buy", {}) if snapshot else {}

            # --- 1. PGR / PLR ---
            gains_available = 0
            losses_available = 0

            iter_symbols: set[str] = set(positions_map.keys())
            if sym and position_qty > 0 and avg_buy > 0:
                iter_symbols.add(sym)

            for state_sym in iter_symbols:
                qty = as_int(positions_map.get(state_sym), 0)
                sym_avg = as_float(avg_buy_map.get(state_sym), 0.0)

                if state_sym == sym and position_qty > 0 and avg_buy > 0:
                    qty = position_qty
                    sym_avg = avg_buy

                if qty <= 0 or sym_avg <= 0:
                    continue
                px = latest_market_by_symbol.get(state_sym)
                if px is None and state_sym == sym and market_px > 0:
                    px = market_px
                if px is None:
                    continue
                if px > sym_avg:
                    gains_available += 1
                elif px < sym_avg:
                    losses_available += 1

            cum_ga[aid] += gains_available
            cum_la[aid] += losses_available

            is_sell_ok = action == "sell" and status == "ok" and avg_buy > 0
            if is_sell_ok and target_price > avg_buy:
                cum_rg[aid] += 1
            elif is_sell_ok and target_price <= avg_buy:
                cum_rl[aid] += 1

            pgr = round(cum_rg[aid] / cum_ga[aid], 4) if cum_ga[aid] > 0 else None
            plr = round(cum_rl[aid] / cum_la[aid], 4) if cum_la[aid] > 0 else None
            de_odean = round(pgr - plr, 4) if pgr is not None and plr is not None else None
            r["pgr"] = pgr
            r["plr"] = plr
            r["de_odean"] = de_odean

            # --- 2. 过度自信: 越亏越交易 ---
            if action in ("buy", "sell") and status == "ok":
                cumulative_ok_trades[aid] += 1
            r["loss_trading_flag"] = (
                return_pct < -3.0
                and cumulative_ok_trades[aid] >= 10
                and turnover > args.oc_threshold * 0.5
            )

            # --- 3. LSV 羊群效应 ---
            lsv = None
            if action in ("buy", "sell") and sym:
                ds = symbol_peer_actions.get(sym)
                total_buy = global_peer_actions["buy"]
                total_sell = global_peer_actions["sell"]
                st = (ds["buy"] + ds["sell"]) if ds else 0
                tt = total_buy + total_sell
                if ds and st > 0 and tt > 0:
                    p_i = ds["buy"] / st
                    p_bar = total_buy / tt
                    lsv = round(abs(p_i - p_bar), 4)
            r["lsv_herding"] = lsv

            if action in ("buy", "sell") and sym:
                symbol_peer_actions[sym][action] += 1
                global_peer_actions[action] += 1

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
    if missing_snapshot_count > 0:
        print(f"  [warn] missing snapshots: {missing_snapshot_count}")

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
