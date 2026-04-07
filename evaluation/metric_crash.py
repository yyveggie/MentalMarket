"""Crash detection metrics:
1. NCSKEW & DUVOL (Chen, Hong & Stein, 2001)
2. Maximum Drawdown & CMAX crash indicator (Patel & Sarkar, 1998)
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

from metrics_plot_common import read_jsonl, safe_float, safe_int


# ──────────────────────────────────────────────────────────────
# 1. NCSKEW & DUVOL  (Chen, Hong & Stein, 2001)
# ──────────────────────────────────────────────────────────────

def compute_crash_ncskew_duvol(run_dir: Path, window: int = 20) -> list[dict]:
    """
    从 broad_index.jsonl 的日度收益率计算滚动 NCSKEW 和 DUVOL。

    NCSKEW_t = -[n(n-1)^{3/2} Σr³] / [(n-1)(n-2)(Σr²)^{3/2}]
    DUVOL_t  = log{ [(n_u-1) Σ_{down} r²] / [(n_d-1) Σ_{up} r²] }

    其中 r 为去均值后的日度收益率，window 为滚动窗口天数。

    返回行: {trading_day, ncskew, duvol, crash_risk_signal, window_n, log_price}

    参考: Chen, J., Hong, H., & Stein, J.C. (2001).
          Forecasting crashes: trading volume, past returns, and
          conditional skewness in stock prices.
          Journal of Financial Economics, 61(3), 345-381.
    """
    index_path = run_dir / "broad_index.jsonl"
    if not index_path.exists():
        return []

    idx_rows = read_jsonl(index_path)
    day_value: dict[int, float] = {}
    for r in idx_rows:
        day = safe_int(r.get("trading_day"))
        val = safe_float(r.get("value"))
        if day is not None and val is not None and val > 0:
            day_value[day] = val

    sorted_days = sorted(day_value.keys())
    if len(sorted_days) < window + 1:
        return []

    # 日度对数收益率
    log_returns: dict[int, float] = {}
    for i in range(1, len(sorted_days)):
        d_prev, d_curr = sorted_days[i - 1], sorted_days[i]
        log_returns[d_curr] = math.log(day_value[d_curr] / day_value[d_prev])

    result = []
    return_days = sorted_days[1:]  # 有收益率的日

    for idx, day in enumerate(return_days):
        row: dict = {
            "trading_day": day,
            "log_price": round(math.log(day_value[day]), 4),
        }

        if idx + 1 < window:
            result.append(row)
            continue

        # 取窗口内收益率
        win_days = return_days[idx - window + 1: idx + 1]
        rets = [log_returns[d] for d in win_days]
        n = len(rets)
        if n < 6:
            result.append(row)
            continue

        mean_r = sum(rets) / n
        demeaned = [r - mean_r for r in rets]

        # NCSKEW
        sum_r2 = sum(d ** 2 for d in demeaned)
        sum_r3 = sum(d ** 3 for d in demeaned)

        ncskew = None
        if sum_r2 > 1e-30:
            ncskew = -(n * (n - 1) ** 1.5 * sum_r3) / ((n - 1) * (n - 2) * sum_r2 ** 1.5)

        # DUVOL
        up_sq = sum(d ** 2 for d in demeaned if d >= 0)
        down_sq = sum(d ** 2 for d in demeaned if d < 0)
        n_up = sum(1 for d in demeaned if d >= 0)
        n_down = sum(1 for d in demeaned if d < 0)

        duvol = None
        if n_up > 1 and n_down > 1 and up_sq > 1e-30:
            duvol = math.log(((n_up - 1) * down_sq) / ((n_down - 1) * up_sq))

        if ncskew is not None:
            row["ncskew"] = round(ncskew, 4)
        if duvol is not None:
            row["duvol"] = round(duvol, 4)

        # 崩盘风险信号: NCSKEW > 0 且 DUVOL > 0 → 负偏度+下行波动率主导
        if ncskew is not None and duvol is not None:
            row["crash_risk_signal"] = 1 if (ncskew > 0 and duvol > 0) else 0

        row["window_n"] = n
        result.append(row)

    return result


# ──────────────────────────────────────────────────────────────
# 2. Maximum Drawdown & CMAX (Patel & Sarkar, 1998)
# ──────────────────────────────────────────────────────────────

def compute_crash_drawdown(run_dir: Path) -> list[dict]:
    """
    从 broad_index.jsonl 计算逐日最大回撤和 CMAX 崩盘指标。

    Drawdown_t = P_t / max(P_1..P_t) - 1          (≤0)
    CMAX_t     = P_t / max(P_1..P_t)               (0~1)
    crash_signal: CMAX_t < mean(CMAX) - 2*std(CMAX) → 1

    Drawdown Duration: 从峰值开始持续回撤的天数

    返回行: {trading_day, drawdown_pct, cmax, drawdown_duration,
             peak_price, current_price, crash_signal}

    参考: Patel, S.A. & Sarkar, A. (1998).
          Crises in developed and emerging stock markets.
          Financial Analysts Journal, 54(6), 50-61.
    """
    index_path = run_dir / "broad_index.jsonl"
    if not index_path.exists():
        return []

    idx_rows = read_jsonl(index_path)
    day_value: dict[int, float] = {}
    for r in idx_rows:
        day = safe_int(r.get("trading_day"))
        val = safe_float(r.get("value"))
        if day is not None and val is not None and val > 0:
            day_value[day] = val

    sorted_days = sorted(day_value.keys())
    if len(sorted_days) < 5:
        return []

    # 第一轮：计算每日 drawdown 和 CMAX
    peak = day_value[sorted_days[0]]
    peak_day = sorted_days[0]
    dd_duration = 0
    raw_results = []

    for day in sorted_days:
        price = day_value[day]
        if price >= peak:
            peak = price
            peak_day = day
            dd_duration = 0
        else:
            dd_duration += 1

        cmax = price / peak
        drawdown_pct = (cmax - 1) * 100  # 负值

        raw_results.append({
            "trading_day": day,
            "drawdown_pct": round(drawdown_pct, 4),
            "cmax": round(cmax, 6),
            "drawdown_duration": dd_duration,
            "peak_price": round(peak, 4),
            "current_price": round(price, 4),
        })

    # 第二轮：计算 CMAX 的均值和标准差，标记崩盘信号
    # 双重条件: z-score 异常 OR 绝对阈值（回撤超过 15%）
    cmax_values = [r["cmax"] for r in raw_results]
    n = len(cmax_values)
    mean_cmax = sum(cmax_values) / n
    var_cmax = sum((c - mean_cmax) ** 2 for c in cmax_values) / max(1, n - 1)
    std_cmax = var_cmax ** 0.5
    z_threshold = mean_cmax - 2 * std_cmax
    abs_threshold = 0.85  # CMAX < 0.85 即回撤 > 15%

    for r in raw_results:
        r["crash_signal"] = 1 if (r["cmax"] < z_threshold or r["cmax"] < abs_threshold) else 0

    return raw_results
