#!/usr/bin/env python3
"""Efficient Market Hypothesis (EMH) metric calculations.

弱式 EMH 检测:
- 收益率自相关 (Return ACF lag 1-5)
- Lo-MacKinlay 方差比 (Variance Ratio, k=2/5/10)
- Hurst 指数 (R/S 分析)
- 游程检验 (Runs Test)

References:
- Lo & MacKinlay (1988): variance ratio test
- Hurst (1951): R/S analysis for long memory
- Wald & Wolfowitz (1940): runs test
"""

from __future__ import annotations

import math


# ──────── Return Autocorrelation ────────

def _acf(series: list[float], lag: int) -> float:
    """Biased sample autocorrelation at given lag."""
    n = len(series)
    if n <= lag or n < 3:
        return 0.0
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series)
    if var <= 1e-15:
        return 0.0
    cov = sum((series[i] - mean) * (series[i + lag] - mean) for i in range(n - lag))
    return cov / var


def rolling_return_acf(
    days: list[int],
    returns: list[float],
    window: int,
    lags: list[int] | None = None,
) -> tuple[list[int], dict[int, list[float]]]:
    """Rolling autocorrelation of raw returns at multiple lags.

    Returns:
        (out_days, {lag: [acf_values]})
    """
    if lags is None:
        lags = [1, 2, 3, 4, 5]
    out_days: list[int] = []
    acf_by_lag: dict[int, list[float]] = {k: [] for k in lags}

    for i in range(window - 1, len(returns)):
        seg = returns[i - window + 1 : i + 1]
        out_days.append(days[i])
        for lag in lags:
            acf_by_lag[lag].append(_acf(seg, lag))

    return out_days, acf_by_lag


# ──────── Variance Ratio (Lo-MacKinlay 1988) ────────

def _variance_ratio(returns: list[float], k: int) -> float | None:
    """Compute VR(k) = Var(r_k) / (k * Var(r_1)).

    Under random walk, VR(k) = 1.
    VR > 1 → positive autocorrelation (momentum/trending).
    VR < 1 → negative autocorrelation (mean reversion).
    """
    n = len(returns)
    if n < k + 1:
        return None

    # 1-period variance
    mean1 = sum(returns) / n
    var1 = sum((r - mean1) ** 2 for r in returns) / (n - 1)
    if var1 <= 1e-15:
        return None

    # k-period returns
    k_returns: list[float] = []
    for i in range(k, n + 1):
        k_returns.append(sum(returns[i - k : i]))

    if len(k_returns) < 2:
        return None
    mean_k = sum(k_returns) / len(k_returns)
    var_k = sum((r - mean_k) ** 2 for r in k_returns) / (len(k_returns) - 1)

    vr = var_k / (k * var1)
    return vr


def rolling_variance_ratio(
    days: list[int],
    returns: list[float],
    window: int,
    k_list: list[int] | None = None,
) -> tuple[list[int], dict[int, list[float]]]:
    """Rolling variance ratio at multiple horizons.

    Returns:
        (out_days, {k: [vr_values]})
    """
    if k_list is None:
        k_list = [2, 5, 10]
    out_days: list[int] = []
    vr_by_k: dict[int, list[float]] = {k: [] for k in k_list}

    for i in range(window - 1, len(returns)):
        seg = returns[i - window + 1 : i + 1]
        out_days.append(days[i])
        for k in k_list:
            vr = _variance_ratio(seg, k)
            vr_by_k[k].append(vr if vr is not None else float("nan"))

    return out_days, vr_by_k


# ──────── Hurst Exponent (R/S Analysis) ────────

def _hurst_rs(series: list[float]) -> float | None:
    """Estimate Hurst exponent via rescaled range (R/S) analysis.

    H = 0.5 → random walk (EMH consistent)
    H > 0.5 → persistent / trending
    H < 0.5 → anti-persistent / mean reverting
    """
    n = len(series)
    if n < 20:
        return None

    # Geometric spacing with factor 1.4 for more OLS points
    sizes: list[int] = []
    s = max(8, n // 16)
    seen: set[int] = set()
    while s <= n:
        s_int = int(s)
        if s_int not in seen and s_int >= 8:
            sizes.append(s_int)
            seen.add(s_int)
        s *= 1.4
    # Ensure we include n itself if large enough
    if n not in seen and n >= 8:
        sizes.append(n)
    if len(sizes) < 2:
        return None

    log_ns: list[float] = []
    log_rs: list[float] = []

    for size in sizes:
        rs_vals: list[float] = []
        n_blocks = n // size
        if n_blocks < 1:
            continue
        for b in range(n_blocks):
            block = series[b * size : (b + 1) * size]
            mean_b = sum(block) / size
            deviations = [x - mean_b for x in block]

            # Cumulative deviation
            cumdev: list[float] = []
            acc = 0.0
            for d in deviations:
                acc += d
                cumdev.append(acc)

            R = max(cumdev) - min(cumdev)
            S = math.sqrt(sum(d ** 2 for d in deviations) / size)
            if S > 1e-15:
                rs_vals.append(R / S)

        if rs_vals:
            avg_rs = sum(rs_vals) / len(rs_vals)
            if avg_rs > 0:
                log_ns.append(math.log(size))
                log_rs.append(math.log(avg_rs))

    if len(log_ns) < 2:
        return None

    # OLS: log(R/S) = H * log(n) + c
    n_pts = len(log_ns)
    sx = sum(log_ns)
    sy = sum(log_rs)
    sxx = sum(x * x for x in log_ns)
    sxy = sum(x * y for x, y in zip(log_ns, log_rs))
    denom = n_pts * sxx - sx * sx
    if abs(denom) < 1e-15:
        return None
    H = (n_pts * sxy - sx * sy) / denom
    return max(0.0, min(1.0, H))


def rolling_hurst(
    days: list[int],
    returns: list[float],
    window: int,
) -> tuple[list[int], list[float]]:
    """Rolling Hurst exponent.

    Returns:
        (out_days, hurst_values)
    """
    out_days: list[int] = []
    hurst_vals: list[float] = []

    for i in range(window - 1, len(returns)):
        seg = returns[i - window + 1 : i + 1]
        h = _hurst_rs(seg)
        out_days.append(days[i])
        hurst_vals.append(h if h is not None else float("nan"))

    return out_days, hurst_vals


# ──────── Runs Test ────────

def _runs_test(series: list[float]) -> tuple[int, float] | None:
    """Non-parametric runs test for randomness.

    Returns:
        (n_runs, z_statistic)

    |Z| < 1.96 → cannot reject randomness at 95% confidence.
    Z >> 0 → too many runs (mean reversion).
    Z << 0 → too few runs (trending/momentum).
    """
    n = len(series)
    if n < 10:
        return None

    signs = [1 if x >= 0 else -1 for x in series]
    n_pos = sum(1 for s in signs if s == 1)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return None

    # Count runs
    runs = 1
    for i in range(1, n):
        if signs[i] != signs[i - 1]:
            runs += 1

    # Expected runs and variance under H0
    expected = 1.0 + (2.0 * n_pos * n_neg) / n
    var_r = (2.0 * n_pos * n_neg * (2.0 * n_pos * n_neg - n)) / (n * n * (n - 1.0))
    if var_r <= 0:
        return runs, 0.0
    z = (runs - expected) / math.sqrt(var_r)
    return runs, z


def rolling_runs_test(
    days: list[int],
    returns: list[float],
    window: int,
) -> tuple[list[int], list[int], list[float]]:
    """Rolling runs test.

    Returns:
        (out_days, runs_counts, z_statistics)
    """
    out_days: list[int] = []
    runs_list: list[int] = []
    z_list: list[float] = []

    for i in range(window - 1, len(returns)):
        seg = returns[i - window + 1 : i + 1]
        result = _runs_test(seg)
        out_days.append(days[i])
        if result is not None:
            runs_list.append(result[0])
            z_list.append(result[1])
        else:
            runs_list.append(0)
            z_list.append(float("nan"))

    return out_days, runs_list, z_list


# ──────── Semi-strong: Cumulative Abnormal Return ────────

def compute_event_car(
    event_days: list[int],
    all_days: list[int],
    returns: list[float],
    horizons: list[int] | None = None,
    estimation_window: int = 20,
) -> list[dict]:
    """Compute Cumulative Abnormal Returns (CAR) around news events.

    For each event day:
    1. Estimate expected return from the [t-estimation_window, t-1] window (mean return).
    2. For each horizon h in horizons, compute CAR(0, h) = sum of abnormal returns from t to t+h.

    Returns:
        list of {event_day, car_1, car_3, car_5, abs_car_1, abs_car_3, abs_car_5}
    """
    if horizons is None:
        horizons = [1, 3, 5]

    # Build day → index map
    day_to_idx: dict[int, int] = {}
    for idx, d in enumerate(all_days):
        day_to_idx[d] = idx

    results: list[dict] = []
    for ev_day in event_days:
        ev_idx = day_to_idx.get(ev_day)
        if ev_idx is None:
            continue

        # Estimation window: [ev_idx - estimation_window, ev_idx - 1]
        est_start = ev_idx - estimation_window
        if est_start < 0:
            est_start = 0
        est_end = ev_idx
        if est_end - est_start < 10:
            continue  # Too few samples for reliable expected return
        est_returns = returns[est_start:est_end]
        expected_r = sum(est_returns) / len(est_returns) if est_returns else 0.0

        row: dict = {"event_day": ev_day}
        for h in horizons:
            # CAR(0, +h) = sum of AR from t=0 to t=+h, inclusive → h+1 days
            end_idx = min(ev_idx + h + 1, len(returns))
            if ev_idx >= len(returns):
                row[f"car_{h}"] = float("nan")
                row[f"abs_car_{h}"] = float("nan")
                continue
            ar_sum = sum(returns[t] - expected_r for t in range(ev_idx, end_idx))
            row[f"car_{h}"] = ar_sum
            row[f"abs_car_{h}"] = abs(ar_sum)
        results.append(row)

    return results


def aggregate_car_by_day(
    car_records: list[dict],
    horizons: list[int] | None = None,
) -> list[dict]:
    """Aggregate CAR metrics per event day (average across events on same day).

    Returns list of {trading_day, avg_car_1, avg_car_3, avg_car_5,
                     avg_abs_car_1, avg_abs_car_3, avg_abs_car_5, event_count}.
    """
    if horizons is None:
        horizons = [1, 3, 5]

    by_day: dict[int, list[dict]] = {}
    for rec in car_records:
        d = rec["event_day"]
        by_day.setdefault(d, []).append(rec)

    results: list[dict] = []
    for day in sorted(by_day):
        recs = by_day[day]
        row: dict = {"trading_day": day, "event_count": len(recs)}
        for h in horizons:
            car_vals = [r[f"car_{h}"] for r in recs if not math.isnan(r.get(f"car_{h}", float("nan")))]
            abs_car_vals = [r[f"abs_car_{h}"] for r in recs if not math.isnan(r.get(f"abs_car_{h}", float("nan")))]
            row[f"avg_car_{h}"] = (sum(car_vals) / len(car_vals)) if car_vals else float("nan")
            row[f"avg_abs_car_{h}"] = (sum(abs_car_vals) / len(abs_car_vals)) if abs_car_vals else float("nan")
        results.append(row)
    return results
