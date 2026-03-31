#!/usr/bin/env python3
"""市场微观结构评估脚本（双语说明）。

中文：
- 从 market_snapshots 日志提取成交量、买卖比、价差等微观结构指标。
- 按标的绘制日度变化图，用于观察流动性与交易结构演化。

English:
- Extracts microstructure metrics such as volume, buy/sell ratio, and spread
    from market_snapshots logs.
- Plots daily per-symbol trajectories for liquidity and trading-structure
    analysis.

运行示例:
- 项目根目录执行:
    python evaluation/plot_market_microstructure.py runs/20260329_150251
- evaluation 目录执行:
    python plot_market_microstructure.py ../runs/20260329_150251
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from metrics_plot_common import (
    collect_symbols,
    configure_chinese_font,
    ensure_output_dir,
    group_last_row_by_day,
    read_jsonl,
    safe_float,
    safe_int,
)

configure_chinese_font()


def _build_nonseed_microstructure(run_dir: Path) -> dict[str, dict[int, dict[str, float]]]:
    """从 trades.jsonl 按 (symbol, trading_day) 聚合非做市商的成交量、买卖量。

    返回 {symbol: {day: {"volume": ..., "buy_volume": ..., "sell_volume": ..., "trade_count": ...}}}
    """
    trades_path = run_dir / "trades.jsonl"
    if not trades_path.exists():
        return {}
    rows = read_jsonl(trades_path)
    out: dict[str, dict[int, dict[str, float]]] = {}
    for r in rows:
        if bool(r.get("is_seed_trade")):
            continue
        sym = str(r.get("symbol", "")).strip().upper()
        day = safe_int(r.get("trading_day"))
        qty = safe_float(r.get("quantity"))
        if not sym or day is None or day <= 0 or qty is None or qty <= 0:
            continue
        dm = out.setdefault(sym, {}).setdefault(day, {"volume": 0.0, "buy_volume": 0.0, "sell_volume": 0.0, "trade_count": 0})
        dm["volume"] += qty
        dm["trade_count"] += 1
        aggr = str(r.get("aggressor", "")).strip().lower()
        if aggr == "bid":
            dm["buy_volume"] += qty
        elif aggr == "ask":
            dm["sell_volume"] += qty
    return out


def pick_float(row: dict, *keys: str) -> float | None:
    for k in keys:
        v = safe_float(row.get(k))
        if v is not None:
            return v
    return None


def series_for_symbol(
    rows: list[dict],
    symbol: str,
    nonseed_micro: dict[str, dict[int, dict[str, float]]] | None = None,
) -> tuple[list[int], list[float], list[float], list[float]]:
    points = group_last_row_by_day(rows, symbol=symbol, day_key="trading_day", time_key="sim_time")
    sym_ns = nonseed_micro.get(symbol.upper(), {}) if nonseed_micro else {}
    days: list[int] = []
    volumes: list[float] = []
    ratios: list[float] = []
    spreads: list[float] = []

    for day, row in points:
        ns = sym_ns.get(day)
        if ns:
            volume = ns["volume"]
            bv = ns["buy_volume"]
            sv = ns["sell_volume"]
            ratio = round(bv / sv, 4) if sv > 0 else (999.0 if bv > 0 else 1.0)
        else:
            volume = pick_float(row, "period_volume", "volume")
            ratio = pick_float(row, "buy_sell_ratio")
        spread = pick_float(row, "spread")

        if volume is None and ratio is None and spread is None:
            continue

        days.append(day)
        volumes.append(volume if volume is not None else 0.0)
        ratios.append(ratio if ratio is not None else 0.0)
        spreads.append(spread if spread is not None else 0.0)

    return days, volumes, ratios, spreads


def plot_symbol(
    symbol: str,
    days: list[int],
    volumes: list[float],
    ratios: list[float],
    spreads: list[float],
    out_path: Path,
) -> None:
    if len(days) < 2:
        return

    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, dpi=140)

    ax1, ax2, ax3 = axes

    ax1.bar(days, volumes, color="#6baed6", alpha=0.9)
    ax1.set_title(f"{symbol} 交易日成交量")
    ax1.set_ylabel("成交量")
    ax1.grid(alpha=0.2)

    ax2.plot(days, ratios, color="#31a354", linewidth=1.7)
    ax2.axhline(1.0, color="#999999", linestyle="--", linewidth=1.0, alpha=0.7)
    ax2.set_title(f"{symbol} 买卖量比")
    ax2.set_ylabel("比值")
    ax2.grid(alpha=0.2)

    ax3.plot(days, spreads, color="#756bb1", linewidth=1.7)
    ax3.fill_between(days, spreads, color="#756bb1", alpha=0.15)
    ax3.set_title(f"{symbol} 买卖价差")
    ax3.set_ylabel("价差")
    ax3.set_xlabel("交易日")
    ax3.grid(alpha=0.2)

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot microstructure metrics from market_snapshots.jsonl")
    parser.add_argument("run_dir", type=str, help="Run directory path, e.g., runs/20260329_005147")
    parser.add_argument("--symbol", type=str, default="", help="Optional symbol; if omitted, all symbols are plotted")
    parser.add_argument("--exclude-seed", action="store_true", help="Exclude market-maker (seed) trades from volume/ratio metrics")
    parser.add_argument("--output-dir", type=str, default="", help="Output directory (default: <run_dir>/figures)")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    rows = read_jsonl(run_dir / "market_snapshots.jsonl")
    if not rows:
        raise SystemExit(f"No market_snapshots.jsonl data found in {run_dir}")

    symbols = collect_symbols(rows)
    if args.symbol:
        symbols = [args.symbol]

    out_dir = ensure_output_dir(run_dir, args.output_dir or None)

    nonseed_micro = _build_nonseed_microstructure(run_dir) if args.exclude_seed else None

    created = 0
    for symbol in symbols:
        days, volumes, ratios, spreads = series_for_symbol(rows, symbol, nonseed_micro=nonseed_micro)
        if len(days) < 2:
            continue
        out_path = out_dir / f"{symbol}_microstructure.png"
        plot_symbol(symbol, days, volumes, ratios, spreads, out_path)
        created += 1

    print(f"Generated {created} charts in {out_dir}")


if __name__ == "__main__":
    main()
