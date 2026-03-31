#!/usr/bin/env python3
"""评估绘图公共工具（双语说明）。

中文：
- 提供评估脚本共用的基础能力，如 JSONL 读取、类型安全转换、按日聚合、
    中文字体配置与输出目录管理。

English:
- Shared utilities for evaluation plotting scripts, including JSONL loading,
    safe type conversion, daily aggregation, Chinese font setup, and output path
    management.

运行示例:
- 本文件为公共工具模块，无独立绘图 CLI。
- 可用于语法检查:
    python -m py_compile evaluation/metrics_plot_common.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def configure_chinese_font() -> str:
    """Configure a Chinese-capable sans-serif font for matplotlib."""
    import matplotlib
    from matplotlib import font_manager

    candidates = [
        "PingFang SC",
        "Hiragino Sans GB",
        "Heiti SC",
        "STHeiti",
        "Songti SC",
        "Arial Unicode MS",
        "Noto Sans CJK SC",
        "SimHei",
        "Microsoft YaHei",
        "WenQuanYi Zen Hei",
        "DejaVu Sans",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = [name for name in candidates if name in available]
    if not chosen:
        chosen = ["DejaVu Sans"]

    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = chosen
    matplotlib.rcParams["axes.unicode_minus"] = False
    return chosen[0]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def safe_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(float(s))
        except ValueError:
            return None
    return None


def collect_symbols(rows: list[dict[str, Any]]) -> list[str]:
    symbols = {
        str(r.get("symbol", "")).strip()
        for r in rows
        if str(r.get("symbol", "")).strip() and not str(r.get("symbol", "")).startswith("__")
    }
    return sorted(symbols)


def group_last_row_by_day(
    rows: list[dict[str, Any]],
    symbol: str,
    day_key: str = "trading_day",
    time_key: str = "sim_time",
) -> list[tuple[int, dict[str, Any]]]:
    by_day: dict[int, tuple[float, dict[str, Any]]] = {}
    for row in rows:
        if str(row.get("symbol", "")).strip() != symbol:
            continue
        day = safe_int(row.get(day_key))
        if day is None or day <= 0:
            continue
        t = safe_float(row.get(time_key))
        sim_time = t if t is not None else -1.0
        old = by_day.get(day)
        if old is None or sim_time >= old[0]:
            by_day[day] = (sim_time, row)

    out = [(d, by_day[d][1]) for d in sorted(by_day.keys())]
    return out


def ensure_output_dir(run_dir: Path, output_dir: str | None) -> Path:
    if output_dir:
        out = Path(output_dir)
    else:
        out = run_dir / "figures"
    out.mkdir(parents=True, exist_ok=True)
    return out
