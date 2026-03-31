#!/usr/bin/env python3
"""价格与波动率评估脚本（双语说明）。

中文：
- 从实验日志构建各标的价格序列与滚动波动率序列。
- 输出用于对比价格路径与风险变化的双轴/双面板图。

English:
- Builds per-symbol price series and rolling volatility series from run logs.
- Produces charts for jointly inspecting price paths and risk dynamics.

运行示例:
- 项目根目录执行:
    python evaluation/plot_price_volatility.py runs/20260329_150251
- 项目根目录执行（仅大盘）:
    python evaluation/plot_price_volatility.py runs/20260329_150251 --broad-index
- evaluation 目录执行:
    python plot_price_volatility.py ../runs/20260329_150251
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


def _build_nonseed_close_map(run_dir: Path) -> dict[str, dict[int, float]]:
    """从 trades.jsonl 构建每 (symbol, trading_day) 的最后一笔非做市商成交价。"""
    trades_path = run_dir / "trades.jsonl"
    if not trades_path.exists():
        return {}
    rows = read_jsonl(trades_path)
    by_sym_day: dict[str, dict[int, tuple[float, float]]] = {}
    for r in rows:
        if bool(r.get("is_seed_trade")):
            continue
        sym = str(r.get("symbol", "")).strip().upper()
        day = safe_int(r.get("trading_day"))
        px = safe_float(r.get("price"))
        tm = safe_float(r.get("sim_time"))
        if not sym or day is None or day <= 0 or px is None:
            continue
        t = tm if tm is not None else -1.0
        dm = by_sym_day.setdefault(sym, {})
        old = dm.get(day)
        if old is None or t >= old[0]:
            dm[day] = (t, px)
    return {sym: {d: v[1] for d, v in dm.items()} for sym, dm in by_sym_day.items()}


def rolling_std(values: list[float], window: int) -> list[float]:
    out: list[float] = []
    for i in range(len(values)):
        j = max(0, i - window + 1)
        seg = values[j : i + 1]
        if len(seg) < 2:
            out.append(0.0)
            continue
        mean = sum(seg) / len(seg)
        var = sum((x - mean) ** 2 for x in seg) / (len(seg) - 1)
        out.append(var ** 0.5)
    return out


def build_series(rows: list[dict], symbol: str, nonseed_map: dict[str, dict[int, float]] | None = None) -> tuple[list[int], list[float]]:
    points = group_last_row_by_day(rows, symbol=symbol, day_key="trading_day", time_key="sim_time")
    days: list[int] = []
    closes: list[float] = []
    sym_nonseed = nonseed_map.get(symbol.upper(), {}) if nonseed_map else {}
    for day, row in points:
        close = safe_float(row.get("last_price"))
        if close is None:
            continue
        if sym_nonseed:
            close = sym_nonseed.get(day, close)
        days.append(day)
        closes.append(close)
    return days, closes


def build_broad_index_series(run_dir: Path) -> tuple[list[int], list[float]]:
    rows = read_jsonl(run_dir / "broad_index.jsonl")
    by_day: dict[int, tuple[float, float]] = {}

    for row in rows:
        day = safe_int(row.get("trading_day"))
        value = safe_float(row.get("value"))
        tm = safe_float(row.get("sim_time"))
        if day is None or day <= 0 or value is None:
            continue
        t = tm if tm is not None else -1.0
        old = by_day.get(day)
        if old is None or t >= old[0]:
            by_day[day] = (t, value)

    days = sorted(by_day.keys())
    closes = [by_day[d][1] for d in days]
    return days, closes


def plot_symbol(days: list[int], closes: list[float], symbol: str, out_path: Path, vol_window: int) -> None:
    if len(days) < 3:
        return

    returns: list[float] = []
    ret_days: list[int] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        denom = prev if abs(prev) > 1e-9 else 1.0
        returns.append((cur - prev) / denom)
        ret_days.append(days[i])

    vol = rolling_std(returns, window=max(2, vol_window))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, dpi=140)

    ax1.plot(days, closes, color="#1f77b4", linewidth=1.8, label="收盘价")
    ax1.set_title(f"{symbol} 价格曲线")
    ax1.set_ylabel("价格")
    ax1.grid(alpha=0.2)
    ax1.legend(loc="upper left")

    ax2.plot(ret_days, vol, color="#d62728", linewidth=1.6, label=f"滚动波动率（{vol_window}日）")
    ax2.fill_between(ret_days, vol, color="#d62728", alpha=0.15)
    ax2.set_title(f"{symbol} 收益率波动")
    ax2.set_xlabel("交易日")
    ax2.set_ylabel("波动率")
    ax2.grid(alpha=0.2)
    ax2.legend(loc="upper left")

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot price and rolling volatility from market_snapshots.jsonl")
    parser.add_argument("run_dir", type=str, help="Run directory path, e.g., runs/20260329_005147")
    parser.add_argument("--symbol", type=str, default="", help="Optional symbol; if omitted, all symbols are plotted")
    parser.add_argument(
        "--broad-index",
        action="store_true",
        help="Plot broad index from broad_index.jsonl (single chart)",
    )
    parser.add_argument("--vol-window", type=int, default=10, help="Rolling window (trading days) for volatility")
    parser.add_argument("--exclude-seed", action="store_true", help="Exclude market-maker (seed) trades from close prices")
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

    nonseed_map = _build_nonseed_close_map(run_dir) if args.exclude_seed else None

    if args.broad_index:
        if args.symbol:
            raise SystemExit("--broad-index cannot be used together with --symbol")
        days, closes = build_broad_index_series(run_dir)
        if len(days) < 3:
            raise SystemExit(f"Not enough broad_index.jsonl data found in {run_dir}")
        out_path = out_dir / "broad_index_price_volatility.png"
        plot_symbol(days, closes, "大盘（broad_index）", out_path, vol_window=max(2, args.vol_window))
        print(f"Generated 1 chart in {out_dir}")
        return

    created = 0
    for symbol in symbols:
        days, closes = build_series(rows, symbol, nonseed_map=nonseed_map)
        if len(days) < 3:
            continue
        out_path = out_dir / f"{symbol}_price_volatility.png"
        plot_symbol(days, closes, symbol, out_path, vol_window=max(2, args.vol_window))
        created += 1

    print(f"Generated {created} charts in {out_dir}")


if __name__ == "__main__":
    main()
