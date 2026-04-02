#!/usr/bin/env python3
"""拟合度与方向准确率纯计算函数（双语说明）。

中文：
- 提供拟合度（Pearson相关系数）与方向准确率的纯计算逻辑。
- 包括逐标的指标、总体加权聚合、每日指标曲线构建等。

English:
- Pure computation for fit-accuracy metrics (Pearson correlation, directional accuracy).
- Includes per-symbol metrics, overall weighted aggregation, and daily curve builders.
"""

from __future__ import annotations

from math import sqrt
from typing import Any, TypedDict

from data_loader import aligned_real_sim_with_day


class DailyCurves(TypedDict):
    days: list[int]
    same_day_acc: list[float | None]
    same_day_n: list[int]
    forward1_acc: list[float | None]
    forward1_n: list[int]
    fit_pct: list[float | None]
    fit_n: list[int]


BROAD_EQW_SYMBOL = "__BROAD_EQW__"


def sign(v: float, eps: float = 1e-12) -> int:
    if v > eps:
        return 1
    if v < -eps:
        return -1
    return 0


def pearson_corr(xs: list[float], ys: list[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    x = xs[:n]
    y = ys[:n]
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    den_x = sum((v - mx) ** 2 for v in x)
    den_y = sum((v - my) ** 2 for v in y)
    if den_x <= 0 or den_y <= 0:
        return None
    return num / sqrt(den_x * den_y)


def compute_symbol_metrics(aligned: list[tuple[int, float, float]]) -> dict[str, Any]:
    if len(aligned) < 3:
        return {
            "same_day_acc": None,
            "same_day_n": 0,
            "forward1_acc": None,
            "forward1_n": 0,
            "fit_pct": None,
            "fit_n": 0,
        }

    same_match = 0
    same_total = 0
    fwd_match = 0
    fwd_total = 0

    real_returns: list[float] = []
    sim_returns: list[float] = []

    for i in range(1, len(aligned)):
        day_prev, real_prev, sim_prev = aligned[i - 1]
        day_cur, real_cur, sim_cur = aligned[i]

        if day_cur != day_prev + 1:
            continue

        real_delta = real_cur - real_prev
        sim_delta = sim_cur - sim_prev

        real_dir = sign(real_delta)
        sim_dir = sign(sim_delta)

        if not (real_dir == 0 and sim_dir == 0):
            if real_dir == sim_dir:
                same_match += 1
            same_total += 1

        real_den = real_prev if abs(real_prev) > 1e-9 else 1.0
        sim_den = sim_prev if abs(sim_prev) > 1e-9 else 1.0
        real_returns.append(real_delta / real_den)
        sim_returns.append(sim_delta / sim_den)

    for i in range(2, len(aligned)):
        day_prev2, _, sim_prev2 = aligned[i - 2]
        day_prev1, real_prev, sim_prev1 = aligned[i - 1]
        day_cur, real_cur, _ = aligned[i]

        if not (day_prev1 == day_prev2 + 1 and day_cur == day_prev1 + 1):
            continue

        real_delta = real_cur - real_prev
        sim_pred_delta = sim_prev1 - sim_prev2

        real_dir = sign(real_delta)
        pred_dir = sign(sim_pred_delta)

        if real_dir == 0 and pred_dir == 0:
            continue
        if real_dir == pred_dir:
            fwd_match += 1
        fwd_total += 1

    corr = pearson_corr(real_returns, sim_returns)
    if corr is None:
        if real_returns and all(abs(real_returns[i] - sim_returns[i]) <= 1e-12 for i in range(len(real_returns))):
            corr = 1.0
        elif real_returns:
            corr = 0.0

    fit_pct = None
    if corr is not None:
        corr = max(-1.0, min(1.0, corr))
        fit_pct = max(0.0, corr) * 100.0

    # RMSE (基于收益率) & R² (基于归一化价格水平)
    rmse = None
    r_squared = None
    if real_returns and sim_returns and len(real_returns) >= 2:
        n = len(real_returns)
        ss_res = sum((real_returns[i] - sim_returns[i]) ** 2 for i in range(n))
        rmse = sqrt(ss_res / n)

    # R²: 归一化价格序列的 Pearson r²，衡量曲线形状相似度
    # 不受尺度/偏移影响，即使微弱信号也能给出正值
    if len(aligned) >= 3:
        base_real = aligned[0][1]
        base_sim = aligned[0][2]
        if abs(base_real) > 1e-9 and abs(base_sim) > 1e-9:
            norm_real = [100.0 * a[1] / base_real for a in aligned]
            norm_sim = [100.0 * a[2] / base_sim for a in aligned]
            pc = pearson_corr(norm_real, norm_sim)
            if pc is not None:
                r_squared = pc ** 2

    return {
        "same_day_acc": (100.0 * same_match / same_total) if same_total else None,
        "same_day_n": same_total,
        "forward1_acc": (100.0 * fwd_match / fwd_total) if fwd_total else None,
        "forward1_n": fwd_total,
        "fit_pct": fit_pct,
        "fit_n": len(real_returns),
        "rmse": rmse,
        "r_squared": r_squared,
    }


def compute_overall(symbol_metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    same_match_total = 0.0
    same_n_total = 0
    fwd_match_total = 0.0
    fwd_n_total = 0
    fit_weighted_sum = 0.0
    fit_n_total = 0

    for m in symbol_metrics.values():
        same_acc = m.get("same_day_acc")
        same_n = int(m.get("same_day_n", 0) or 0)
        if same_acc is not None and same_n > 0:
            same_match_total += (same_acc / 100.0) * same_n
            same_n_total += same_n

        fwd_acc = m.get("forward1_acc")
        fwd_n = int(m.get("forward1_n", 0) or 0)
        if fwd_acc is not None and fwd_n > 0:
            fwd_match_total += (fwd_acc / 100.0) * fwd_n
            fwd_n_total += fwd_n

        fit_pct = m.get("fit_pct")
        fit_n = int(m.get("fit_n", 0) or 0)
        if fit_pct is not None and fit_n > 0:
            fit_weighted_sum += fit_pct * fit_n
            fit_n_total += fit_n

    return {
        "same_day_acc": (100.0 * same_match_total / same_n_total) if same_n_total else None,
        "same_day_n": same_n_total,
        "forward1_acc": (100.0 * fwd_match_total / fwd_n_total) if fwd_n_total else None,
        "forward1_n": fwd_n_total,
        "fit_pct": (fit_weighted_sum / fit_n_total) if fit_n_total else None,
        "fit_n": fit_n_total,
        "rmse": _aggregate_rmse(symbol_metrics),
        "r_squared": _aggregate_r_squared(symbol_metrics),
    }


def _aggregate_rmse(symbol_metrics: dict[str, dict[str, Any]]) -> float | None:
    """加权聚合 RMSE：sqrt(加权 MSE)。"""
    mse_wsum = 0.0
    n_total = 0
    for m in symbol_metrics.values():
        rmse = m.get("rmse")
        n = int(m.get("fit_n", 0) or 0)
        if rmse is not None and n > 0:
            mse_wsum += (rmse ** 2) * n
            n_total += n
    if n_total == 0:
        return None
    return sqrt(mse_wsum / n_total)


def _aggregate_r_squared(symbol_metrics: dict[str, dict[str, Any]]) -> float | None:
    """加权聚合 R²。"""
    r2_wsum = 0.0
    n_total = 0
    for m in symbol_metrics.values():
        r2 = m.get("r_squared")
        n = int(m.get("fit_n", 0) or 0)
        if r2 is not None and n > 0:
            r2_wsum += r2 * n
            n_total += n
    if n_total == 0:
        return None
    return r2_wsum / n_total


def _nan_to_none(v: float) -> float | None:
    return None if v != v else v


def build_daily_metric_curves(
    symbols: list[str],
    real_close_by_symbol_day: dict[str, dict[int, float]],
    sim_close: dict[str, dict[int, float]],
    max_day: int,
    rolling_window: int,
) -> DailyCurves:
    symbol_day_map: dict[str, dict[int, tuple[float, float]]] = {}
    for symbol in symbols:
        aligned = aligned_real_sim_with_day(symbol, real_close_by_symbol_day, sim_close, max_day)
        symbol_day_map[symbol] = {day: (real_close, sim_close_v) for day, real_close, sim_close_v in aligned}

    days = list(range(1, max_day + 1))
    same_day_acc: list[float] = []
    same_day_n: list[int] = []
    forward1_acc: list[float] = []
    forward1_n: list[int] = []
    fit_pct: list[float] = []
    fit_n: list[int] = []

    for day in days:
        same_match = 0
        same_total = 0
        fwd_match = 0
        fwd_total = 0

        for symbol in symbols:
            dm = symbol_day_map.get(symbol, {})

            if day >= 2 and day in dm and (day - 1) in dm:
                real_prev, sim_prev = dm[day - 1]
                real_cur, sim_cur = dm[day]
                real_dir = sign(real_cur - real_prev)
                sim_dir = sign(sim_cur - sim_prev)
                if not (real_dir == 0 and sim_dir == 0):
                    if real_dir == sim_dir:
                        same_match += 1
                    same_total += 1

            if day >= 3 and day in dm and (day - 1) in dm and (day - 2) in dm:
                real_prev, _ = dm[day - 1]
                real_cur, _ = dm[day]
                _, sim_prev2 = dm[day - 2]
                _, sim_prev1 = dm[day - 1]
                real_dir = sign(real_cur - real_prev)
                pred_dir = sign(sim_prev1 - sim_prev2)
                if not (real_dir == 0 and pred_dir == 0):
                    if real_dir == pred_dir:
                        fwd_match += 1
                    fwd_total += 1

        same_day_acc.append((100.0 * same_match / same_total) if same_total else float("nan"))
        same_day_n.append(same_total)
        forward1_acc.append((100.0 * fwd_match / fwd_total) if fwd_total else float("nan"))
        forward1_n.append(fwd_total)

        if day < 2:
            fit_pct.append(float("nan"))
            fit_n.append(0)
            continue

        start_day = 2  # expanding window: always from the beginning
        real_returns: list[float] = []
        sim_returns: list[float] = []

        for symbol in symbols:
            dm = symbol_day_map.get(symbol, {})
            for t in range(start_day, day + 1):
                if t not in dm or (t - 1) not in dm:
                    continue
                real_prev, sim_prev = dm[t - 1]
                real_cur, sim_cur = dm[t]
                real_den = real_prev if abs(real_prev) > 1e-9 else 1.0
                sim_den = sim_prev if abs(sim_prev) > 1e-9 else 1.0
                real_returns.append((real_cur - real_prev) / real_den)
                sim_returns.append((sim_cur - sim_prev) / sim_den)

        fit_n.append(len(real_returns))
        if len(real_returns) < 30:
            fit_pct.append(float("nan"))
            continue
        corr = pearson_corr(real_returns, sim_returns)
        if corr is None:
            if real_returns and all(abs(real_returns[i] - sim_returns[i]) <= 1e-12 for i in range(len(real_returns))):
                corr = 1.0
            elif real_returns:
                corr = 0.0

        if corr is None:
            fit_pct.append(float("nan"))
        else:
            corr = max(-1.0, min(1.0, corr))
            fit_pct.append(max(0.0, corr) * 100.0)

    return {
        "days": days,
        "same_day_acc": [_nan_to_none(v) for v in same_day_acc],
        "same_day_n": same_day_n,
        "forward1_acc": [_nan_to_none(v) for v in forward1_acc],
        "forward1_n": forward1_n,
        "fit_pct": [_nan_to_none(v) for v in fit_pct],
        "fit_n": fit_n,
    }


def build_weighted_close_by_day(
    close_by_symbol_day: dict[str, dict[int, float]],
    symbols: list[str],
    max_day: int,
    weights: dict[str, float] | None = None,
) -> dict[int, float]:
    """构建加权合成收盘价序列。weights=None 时退化为等权。"""
    out: dict[int, float] = {}
    for day in range(1, max_day + 1):
        available = [(s, close_by_symbol_day[s][day]) for s in symbols if day in close_by_symbol_day.get(s, {})]
        if not available:
            continue
        if weights is None:
            out[day] = sum(v for _, v in available) / len(available)
        else:
            w_sum = sum(weights.get(s, 0.0) for s, _ in available)
            if w_sum <= 0:
                out[day] = sum(v for _, v in available) / len(available)
            else:
                out[day] = sum(weights.get(s, 0.0) * v for s, v in available) / w_sum
    return out


def build_equal_weight_close_by_day(
    close_by_symbol_day: dict[str, dict[int, float]],
    symbols: list[str],
    max_day: int,
) -> dict[int, float]:
    return build_weighted_close_by_day(close_by_symbol_day, symbols, max_day, weights=None)


def build_daily_fit_curve_for_symbol(
    symbol: str,
    real_close_by_symbol_day: dict[str, dict[int, float]],
    sim_close: dict[str, dict[int, float]],
    max_day: int,
    rolling_window: int,
) -> dict[str, list[int] | list[float | None]]:
    aligned = aligned_real_sim_with_day(symbol, real_close_by_symbol_day, sim_close, max_day)
    day_map = {day: (real_close, sim_close_v) for day, real_close, sim_close_v in aligned}

    days = list(range(1, max_day + 1))
    fit_pct: list[float] = []
    fit_n: list[int] = []

    for day in days:
        if day < 2:
            fit_pct.append(float("nan"))
            fit_n.append(0)
            continue

        start_day = 2  # expanding window: always from the beginning
        real_returns: list[float] = []
        sim_returns: list[float] = []

        for t in range(start_day, day + 1):
            if t not in day_map or (t - 1) not in day_map:
                continue
            real_prev, sim_prev = day_map[t - 1]
            real_cur, sim_cur = day_map[t]
            real_den = real_prev if abs(real_prev) > 1e-9 else 1.0
            sim_den = sim_prev if abs(sim_prev) > 1e-9 else 1.0
            real_returns.append((real_cur - real_prev) / real_den)
            sim_returns.append((sim_cur - sim_prev) / sim_den)

        fit_n.append(len(real_returns))
        if len(real_returns) < 5:
            fit_pct.append(float("nan"))
            continue
        corr = pearson_corr(real_returns, sim_returns)
        if corr is None:
            if real_returns and all(abs(real_returns[i] - sim_returns[i]) <= 1e-12 for i in range(len(real_returns))):
                corr = 1.0
            elif real_returns:
                corr = 0.0

        if corr is None:
            fit_pct.append(float("nan"))
        else:
            corr = max(-1.0, min(1.0, corr))
            fit_pct.append(max(0.0, corr) * 100.0)

    return {
        "days": days,
        "fit_pct": [_nan_to_none(v) for v in fit_pct],
        "fit_n": fit_n,
    }


def build_per_symbol_fit_curves(
    symbols: list[str],
    real_close_by_symbol_day: dict[str, dict[int, float]],
    sim_close: dict[str, dict[int, float]],
    max_day: int,
    rolling_window: int,
) -> dict[str, dict[str, list[int] | list[float | None]]]:
    out: dict[str, dict[str, list[int] | list[float | None]]] = {}
    for symbol in symbols:
        out[symbol] = build_daily_fit_curve_for_symbol(
            symbol=symbol,
            real_close_by_symbol_day=real_close_by_symbol_day,
            sim_close=sim_close,
            max_day=max_day,
            rolling_window=rolling_window,
        )
    return out
