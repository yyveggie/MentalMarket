#!/usr/bin/env python3
"""数据加载工具函数（双语说明）。

中文：
- 提供拟合评估脚本通用的数据读取与对齐函数。
- 负责真实曲线文件解析、模拟收盘价提取、交易日重映射等。

English:
- Shared data loading and alignment helpers for fit-accuracy evaluation.
- Handles real curve parsing, sim close extraction, and trading-day remapping.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from metrics_plot_common import group_last_row_by_day, read_jsonl, safe_float, safe_int


def infer_closed_from_row(row: dict[str, Any]) -> bool | None:
    raw_closed = row.get("is_closed")
    if isinstance(raw_closed, bool):
        return raw_closed
    if isinstance(raw_closed, (int, float)):
        return bool(raw_closed)

    status = str(row.get("market_status", "")).strip()
    if not status:
        return None
    status_lower = status.lower()
    return status.startswith("休市") or status_lower.startswith("closed")


def load_run_config(run_dir: Path) -> dict[str, Any]:
    cfg_path = run_dir / "config.yaml"
    if not cfg_path.exists():
        return {}
    try:
        cfg_obj = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return cfg_obj if isinstance(cfg_obj, dict) else {}


def resolve_calendar_news_file(run_dir: Path) -> Path | None:
    cfg_obj = load_run_config(run_dir)
    dashboard_cfg = cfg_obj.get("dashboard", {}) if isinstance(cfg_obj.get("dashboard", {}), dict) else {}
    news_cfg = cfg_obj.get("news_events_config", {}) if isinstance(cfg_obj.get("news_events_config", {}), dict) else {}

    candidate = (
        dashboard_cfg.get("real_calendar_news_file")
        or news_cfg.get("experimental_news_file")
        or news_cfg.get("news_file")
    )
    if not candidate:
        return None
    p = Path(str(candidate))
    if p.is_absolute():
        return p

    probes = [
        p,
        run_dir / p,
        run_dir.parent / p,
        run_dir.parent.parent / p,
    ]
    for q in probes:
        if q.exists():
            return q
    return p


def resolve_existing_path(path_text: str, run_dir: Path) -> Path:
    p = Path(str(path_text or "").strip()).expanduser()
    if p.is_absolute():
        if p.exists():
            return p
        raise FileNotFoundError(f"Path not found: {p}")

    probes = [
        p,
        run_dir / p,
        run_dir.parent / p,
        run_dir.parent.parent / p,
        Path(__file__).resolve().parents[1] / p,
    ]
    seen: set[Path] = set()
    for q in probes:
        if q in seen:
            continue
        seen.add(q)
        if q.exists():
            return q
    raise FileNotFoundError(
        f"Path not found: {path_text}; tried: {', '.join(str(x) for x in probes)}"
    )


def load_closed_dates_from_calendar_news(path: Path | None) -> set[str]:
    if path is None or (not path.exists()):
        return set()
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    rows = obj.get("news", []) if isinstance(obj, dict) else []
    if not isinstance(rows, list):
        return set()

    out: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = str(row.get("date", "")).strip()
        if not d:
            continue
        closed = infer_closed_from_row(row)
        if closed:
            out.add(d)
    return out


def load_real_curves(
    path: Path,
    include_closed_days: bool = False,
    closed_dates_hint: set[str] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[int, float]], list[str], dict[int, int]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    indices = obj.get("indices", {})
    if not isinstance(indices, dict) or not indices:
        raise ValueError(f"Invalid real curve file: {path}")

    all_dates: set[str] = set()
    for rows in indices.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            d = str(row.get("date", "")).strip()
            if d:
                all_dates.add(d)

    calendar_dates_all = sorted(all_dates)
    if not calendar_dates_all:
        raise ValueError(f"No calendar dates found in real curve file: {path}")

    day_of_date_all = {d: i + 1 for i, d in enumerate(calendar_dates_all)}

    date_is_closed: dict[str, bool] = {d: True for d in (closed_dates_hint or set())}
    for rows in indices.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            d = str(row.get("date", "")).strip()
            if not d:
                continue
            closed = infer_closed_from_row(row)
            if closed is None:
                continue
            prev = date_is_closed.get(d, False)
            date_is_closed[d] = bool(prev or closed)

    if include_closed_days:
        trading_dates = list(calendar_dates_all)
    else:
        trading_dates = [d for d in calendar_dates_all if not date_is_closed.get(d, False)]
        if not trading_dates:
            trading_dates = calendar_dates_all

    open_day_of_all_day: dict[int, int] = {}
    for open_day, d in enumerate(trading_dates, start=1):
        all_day = day_of_date_all[d]
        open_day_of_all_day[all_day] = open_day

    real_close_by_symbol_day: dict[str, dict[int, float]] = {}

    for symbol, rows in indices.items():
        if not isinstance(rows, list):
            continue
        day_map: dict[int, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            d = str(row.get("date", "")).strip()
            c = safe_float(row.get("close"))
            if not d or c is None:
                continue
            all_day = day_of_date_all.get(d)
            if all_day is None:
                continue
            day = open_day_of_all_day.get(all_day)
            if day is None:
                continue
            day_map[day] = c
        if day_map:
            real_close_by_symbol_day[str(symbol)] = day_map

    return indices, real_close_by_symbol_day, trading_dates, open_day_of_all_day


def remap_sim_close_to_trading_days(
    sim_close: dict[str, dict[int, float]],
    open_day_of_all_day: dict[int, int],
) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for symbol, day_map in sim_close.items():
        mapped: dict[int, float] = {}
        for all_day, close in day_map.items():
            open_day = open_day_of_all_day.get(all_day)
            if open_day is None:
                continue
            mapped[open_day] = close
        if mapped:
            out[symbol] = mapped
    return out


def load_include_closed_days_from_run_config(run_dir: Path, default: bool = False) -> bool:
    cfg_obj = load_run_config(run_dir)
    news_cfg = cfg_obj.get("news_events_config", {})
    if not isinstance(news_cfg, dict):
        return default
    return bool(news_cfg.get("reopen_include_closed_days", default))


def resolve_include_closed_days(run_dir: Path, mode: str) -> bool:
    m = str(mode).strip().lower()
    if m == "true":
        return True
    if m == "false":
        return False
    return load_include_closed_days_from_run_config(run_dir, default=False)


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


def build_sim_close_by_day(
    snapshot_rows: list[dict[str, Any]],
    nonseed_map: dict[str, dict[int, float]] | None = None,
) -> dict[str, dict[int, float]]:
    symbols = {
        str(r.get("symbol", "")).strip()
        for r in snapshot_rows
        if str(r.get("symbol", "")).strip() and not str(r.get("symbol", "")).startswith("__")
    }

    out: dict[str, dict[int, float]] = {}
    for symbol in sorted(symbols):
        points = group_last_row_by_day(snapshot_rows, symbol=symbol, day_key="trading_day", time_key="sim_time")
        sym_nonseed = nonseed_map.get(symbol.upper(), {}) if nonseed_map else {}
        day_map: dict[int, float] = {}
        for day, row in points:
            close = safe_float(row.get("last_price"))
            if close is None:
                continue
            if sym_nonseed:
                close = sym_nonseed.get(day, close)
            day_map[day] = close
        if day_map:
            out[symbol] = day_map
    return out


def aligned_real_sim_with_day(
    symbol: str,
    real_close_by_symbol_day: dict[str, dict[int, float]],
    sim_close: dict[str, dict[int, float]],
    max_day: int,
) -> list[tuple[int, float, float]]:
    real_by_day = real_close_by_symbol_day.get(symbol, {})
    sim_by_day = sim_close.get(symbol, {})
    if not real_by_day or not sim_by_day:
        return []

    aligned: list[tuple[int, float, float]] = []
    for day in range(1, max_day + 1):
        real_close = real_by_day.get(day)
        sim_close_day = sim_by_day.get(day)
        if real_close is None or sim_close_day is None:
            continue
        aligned.append((day, real_close, sim_close_day))
    return aligned
