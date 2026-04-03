#!/usr/bin/env python3
"""学术指标评估公共函数（双语说明）。

中文：
- 提供学术指标评估脚本共用的数据读取、收益率计算与统计估计函数。
- 覆盖波动聚集、尾指数、价格冲击与不平等度等常用金融指标。

English:
- Shared helpers for academic evaluation scripts, including data loading,
  return construction, and statistical estimators.
- Covers volatility clustering, tail index, Kyle lambda, and inequality metrics.

References:
- Cont (2001): stylized facts / volatility clustering
- Hill (1975): tail index estimator
- Kyle (1985): price impact lambda
- Gini (1912), Theil (1967): inequality metrics

运行示例:
- 可视化入口已迁移至 plot_academic_metrics.py:
    python evaluation/plot_academic_metrics.py --run-dir runs/20260329_150251
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from metrics_plot_common import read_jsonl, safe_float, safe_int


def resolve_run_dir(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Path:
    run_dir_str = args.run_dir_opt or args.run_dir
    if not run_dir_str:
        parser.error("Please provide run_dir as positional arg or --run-dir")
    run_dir = Path(run_dir_str)
    if not run_dir.exists():
        parser.error(f"Run directory not found: {run_dir}")
    return run_dir


def _build_nonseed_close_map(run_dir: Path) -> dict[str, dict[int, float]]:
    """从 trades.jsonl 构建每 (symbol, trading_day) 的最后一笔非做市商成交价。

    返回 {symbol: {day: last_non_seed_price}}。
    """
    trades_path = run_dir / "trades.jsonl"
    if not trades_path.exists():
        return {}
    rows = read_jsonl(trades_path)
    # {symbol: {day: (sim_time, price)}}
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


def load_reference_close_series(
    run_dir: Path,
    symbol: str | None,
    exclude_seed: bool = False,
) -> tuple[list[int], list[float]]:
    """Load daily close proxy.

    - symbol provided: use market_snapshots day-end last_price of this symbol.
    - otherwise: use broad_index day-end value.

    When *exclude_seed=True*, the per-symbol close price is overridden by the
    last non-seed-trade price from trades.jsonl (if available for that day).
    For broad_index mode the effect is indirect: each constituent symbol's
    close in the index is already a weighted composite, and seed-trade volume
    is typically <3%, so the broad_index series is used as-is.
    """
    nonseed: dict[str, dict[int, float]] = {}
    if exclude_seed:
        nonseed = _build_nonseed_close_map(run_dir)

    if symbol:
        rows = read_jsonl(run_dir / "market_snapshots.jsonl")
        by_day: dict[int, tuple[float, float]] = {}
        for r in rows:
            if str(r.get("symbol", "")).strip().upper() != symbol.upper():
                continue
            day = safe_int(r.get("trading_day"))
            px = safe_float(r.get("last_price"))
            tm = safe_float(r.get("sim_time"))
            if day is None or day <= 0 or px is None:
                continue
            t = tm if tm is not None else -1.0
            old = by_day.get(day)
            if old is None or t >= old[0]:
                by_day[day] = (t, px)
        days = sorted(by_day.keys())
        if exclude_seed:
            sym_nonseed = nonseed.get(symbol.upper(), {})
            closes = [sym_nonseed.get(d, by_day[d][1]) for d in days]
        else:
            closes = [by_day[d][1] for d in days]
        return days, closes

    rows = read_jsonl(run_dir / "broad_index.jsonl")
    by_day: dict[int, tuple[float, float]] = {}
    for r in rows:
        day = safe_int(r.get("trading_day"))
        val = safe_float(r.get("value"))
        tm = safe_float(r.get("sim_time"))
        if day is None or day <= 0 or val is None:
            continue
        t = tm if tm is not None else -1.0
        old = by_day.get(day)
        if old is None or t >= old[0]:
            by_day[day] = (t, val)
    days = sorted(by_day.keys())
    closes = [by_day[d][1] for d in days]
    return days, closes


def compute_log_returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        p0 = closes[i - 1]
        p1 = closes[i]
        if p0 <= 0 or p1 <= 0:
            out.append(0.0)
            continue
        out.append(math.log(p1 / p0))
    return out




def latest_non_nan(vals: list[float]) -> float | None:
    for v in reversed(vals):
        if not math.isnan(v):
            return float(v)
    return None
