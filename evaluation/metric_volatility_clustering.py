#!/usr/bin/env python3
"""Volatility-clustering metric calculations (Cont 2001)."""

from __future__ import annotations


def autocorrelation(series: list[float], lag: int) -> float | None:
    n = len(series)
    if n <= lag or n < 3:
        return None
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series)
    if var <= 1e-15:
        return 0.0
    cov = sum((series[i] - mean) * (series[i + lag] - mean) for i in range(n - lag))
    return cov / var


def rolling_acf(
    days: list[int],
    returns: list[float],
    window: int,
) -> tuple[list[int], list[float], list[float]]:
    out_days: list[int] = []
    ac_abs_1: list[float] = []
    ac_sq_1: list[float] = []

    for i in range(window - 1, len(returns)):
        seg = returns[i - window + 1 : i + 1]
        abs_seg = [abs(x) for x in seg]
        sq_seg = [x * x for x in seg]
        a1 = autocorrelation(abs_seg, lag=1)
        b1 = autocorrelation(sq_seg, lag=1)
        out_days.append(days[i + 1])
        ac_abs_1.append(a1 if a1 is not None else 0.0)
        ac_sq_1.append(b1 if b1 is not None else 0.0)

    return out_days, ac_abs_1, ac_sq_1
