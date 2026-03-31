#!/usr/bin/env python3
"""Wealth-inequality metric calculations."""

from __future__ import annotations

import math
from pathlib import Path

from metrics_plot_common import read_jsonl, safe_float, safe_int


def gini_coefficient(values: list[float]) -> float | None:
    xs = [max(0.0, float(v)) for v in values if v is not None]
    n = len(xs)
    if n == 0:
        return None
    total = sum(xs)
    if total <= 1e-15:
        return 0.0
    xs.sort()
    weighted = 0.0
    for i, x in enumerate(xs, start=1):
        weighted += i * x
    return (2.0 * weighted) / (n * total) - (n + 1.0) / n


def theil_t_index(values: list[float]) -> float | None:
    xs = [max(0.0, float(v)) for v in values if v is not None]
    n = len(xs)
    if n == 0:
        return None
    mean = sum(xs) / n
    if mean <= 1e-15:
        return 0.0
    s = 0.0
    for x in xs:
        if x <= 0:
            continue
        r = x / mean
        s += r * math.log(r)
    return s / n


def top_share(values: list[float], pct: float) -> float | None:
    xs = [max(0.0, float(v)) for v in values if v is not None]
    n = len(xs)
    if n == 0:
        return None
    total = sum(xs)
    if total <= 1e-15:
        return 0.0
    m = max(1, int(math.ceil(n * pct)))
    xs.sort(reverse=True)
    return sum(xs[:m]) / total


def build_daily_inequality(run_dir: Path, tom_level: int | None = None) -> tuple[list[int], list[float], list[float], list[float], list[int]]:
    rows = read_jsonl(run_dir / "agent_wealth.jsonl")

    by_day_agent: dict[int, dict[int, tuple[float, float]]] = {}

    for row in rows:
        if tom_level is not None:
            t = safe_int(row.get("tom_level"))
            if t != tom_level:
                continue
        day = safe_int(row.get("trading_day"))
        aid = safe_int(row.get("agent_id"))
        tm = safe_float(row.get("sim_time"))
        wealth = safe_float(row.get("wealth"))
        if day is None or day <= 0 or aid is None or tm is None or wealth is None:
            continue
        dm = by_day_agent.setdefault(day, {})
        old = dm.get(aid)
        if old is None or tm >= old[0]:
            dm[aid] = (tm, wealth)

    out_days: list[int] = []
    gini_curve: list[float] = []
    theil_curve: list[float] = []
    top1_curve: list[float] = []
    n_curve: list[int] = []

    for day in sorted(by_day_agent.keys()):
        wealths = [v[1] for v in by_day_agent[day].values()]
        g = gini_coefficient(wealths)
        t = theil_t_index(wealths)
        s1 = top_share(wealths, pct=0.01)
        out_days.append(day)
        gini_curve.append(g if g is not None else 0.0)
        theil_curve.append(t if t is not None else 0.0)
        top1_curve.append(s1 if s1 is not None else 0.0)
        n_curve.append(len(wealths))

    return out_days, gini_curve, theil_curve, top1_curve, n_curve
