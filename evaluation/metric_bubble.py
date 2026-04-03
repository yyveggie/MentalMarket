"""Bubble detection metrics: RD/RAD (Stöckl et al., 2010) and
GSADF date-stamping (Phillips, Shi & Yu, 2015)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from metrics_plot_common import read_jsonl, safe_int


# ──────────────────────────────────────────────────────────────
# 1. RD / RAD  (Stöckl, Huber & Kirchler, 2010)
# ──────────────────────────────────────────────────────────────

def compute_bubble_rd_rad(run_dir: Path, window: int = 20) -> list[dict]:
    """
    从 market_snapshots.jsonl 的 price_deviation_pct 计算逐日 RD/RAD。

    RD_t  = (1/N) Σ_i  dev_{i,t}           (带符号, 反映高估/低估方向)
    RAD_t = (1/N) Σ_i |dev_{i,t}|           (绝对值, 反映错误定价程度)
    rolling_RD  = (1/W) Σ_{s=t-W+1}^{t} RD_s
    rolling_RAD = (1/W) Σ_{s=t-W+1}^{t} RAD_s

    返回行: {trading_day, rd, rad, rolling_rd, rolling_rad,
             max_deviation, min_deviation, n_overpriced, n_underpriced}

    参考: Stöckl, T., Huber, J., & Kirchler, M. (2010).
          Bubble measures in experimental asset markets.
          Experimental Economics, 13(3), 284-298.
    """
    snap_path = run_dir / "market_snapshots.jsonl"
    if not snap_path.exists():
        return []

    rows = read_jsonl(snap_path)

    # 按天聚合所有股票的 deviation
    day_devs: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        day = safe_int(r.get("trading_day"))
        dev = r.get("price_deviation_pct")
        sym = r.get("symbol", "")
        if day is None or dev is None or sym.startswith("__"):
            continue
        day_devs[day].append(float(dev))

    sorted_days = sorted(day_devs.keys())
    if not sorted_days:
        return []

    # 计算每日 cross-sectional RD/RAD
    daily_rd: list[float] = []
    daily_rad: list[float] = []

    result = []
    for idx, day in enumerate(sorted_days):
        devs = day_devs[day]
        n = len(devs)
        rd = sum(devs) / n
        rad = sum(abs(d) for d in devs) / n
        daily_rd.append(rd)
        daily_rad.append(rad)

        # 滚动窗口
        rolling_rd = None
        rolling_rad = None
        if idx >= window - 1:
            win_rd = daily_rd[idx - window + 1: idx + 1]
            win_rad = daily_rad[idx - window + 1: idx + 1]
            rolling_rd = round(sum(win_rd) / window, 4)
            rolling_rad = round(sum(win_rad) / window, 4)

        row: dict = {
            "trading_day": day,
            "rd": round(rd, 4),
            "rad": round(rad, 4),
            "max_deviation": round(max(devs), 4),
            "min_deviation": round(min(devs), 4),
            "n_overpriced": sum(1 for d in devs if d > 5.0),
            "n_underpriced": sum(1 for d in devs if d < -5.0),
        }
        if rolling_rd is not None:
            row["rolling_rd"] = rolling_rd
        if rolling_rad is not None:
            row["rolling_rad"] = rolling_rad
        result.append(row)

    return result


# ──────────────────────────────────────────────────────────────
# 2. GSADF date-stamping (Phillips, Shi & Yu, 2015)
# ──────────────────────────────────────────────────────────────

def _ols_adf_stat(y: list[float]) -> float | None:
    """
    计算右尾 ADF(0) 检验统计量 (t-stat for β in Δy = α + β·y_{-1} + ε)。
    """
    n = len(y)
    if n < 6:
        return None

    # Δy_t = y_t - y_{t-1}, for t = 1..n-1
    dy = [y[t] - y[t - 1] for t in range(1, n)]
    y_lag = [y[t - 1] for t in range(1, n)]
    m = len(dy)

    # OLS: Δy = α + β·y_{-1}
    # X = [1, y_{-1}]  (m x 2), solve for [α, β]
    sx = sum(y_lag)
    sx2 = sum(v * v for v in y_lag)
    sy = sum(dy)
    sxy = sum(dy[i] * y_lag[i] for i in range(m))

    denom = m * sx2 - sx * sx
    if abs(denom) < 1e-30:
        return None

    beta = (m * sxy - sx * sy) / denom
    alpha = (sy - beta * sx) / m

    # 残差与标准误
    resid = [dy[i] - alpha - beta * y_lag[i] for i in range(m)]
    sse = sum(e * e for e in resid)
    s2 = sse / max(1, m - 2)

    se_beta_sq = s2 * m / denom
    if se_beta_sq <= 0:
        return None
    se_beta = se_beta_sq ** 0.5

    return beta / se_beta  # t-stat


def _bsadf_cv_95(T: int) -> float:
    """
    BSADF 95% 临界值的近似（基于 PSY 2015 Table S4 的插值）。

    对较短序列偏保守。
    """
    # PSY (2015) Monte Carlo tabulated values (selected T):
    # T=50 → ~1.68,  T=100 → ~1.49,  T=200 → ~1.34,  T=400 → ~1.21
    if T <= 50:
        return 1.68
    elif T <= 100:
        return 1.68 - (T - 50) / 50 * (1.68 - 1.49)
    elif T <= 200:
        return 1.49 - (T - 100) / 100 * (1.49 - 1.34)
    elif T <= 400:
        return 1.34 - (T - 200) / 200 * (1.34 - 1.21)
    else:
        return 1.10


def compute_bubble_gsadf(run_dir: Path) -> list[dict]:
    """
    从 broad_index.jsonl (或 market_snapshots 主力股) 计算 GSADF 泡沫日期标记。

    对每个端点 t, 计算:
        BSADF(t) = sup_{r1} ADF[r1 .. t]
    若 BSADF(t) > 95% 临界值 → bubble_signal = 1

    返回行: {trading_day, bsadf_stat, cv_95, bubble_signal, log_price}

    参考: Phillips, P.C.B., Shi, S., & Yu, J. (2015).
          Testing for multiple bubbles: Historical episodes of
          exuberance and collapse in the S&P 500.
          International Economic Review, 56(4), 1043-1078.
    """
    index_path = run_dir / "broad_index.jsonl"
    if not index_path.exists():
        return []

    idx_rows = read_jsonl(index_path)
    day_value: dict[int, float] = {}
    for r in idx_rows:
        day = safe_int(r.get("trading_day"))
        val = r.get("value")
        if day is not None and val is not None and float(val) > 0:
            day_value[day] = float(val)

    sorted_days = sorted(day_value.keys())
    T = len(sorted_days)
    if T < 20:
        return []

    import math
    log_prices = [math.log(day_value[d]) for d in sorted_days]

    # 最小窗口: r0 = 0.01 + 1.8/sqrt(T), 至少 15
    r0_frac = 0.01 + 1.8 / (T ** 0.5)
    min_win = max(15, int(T * r0_frac))

    cv = _bsadf_cv_95(T)

    result = []
    for idx, day in enumerate(sorted_days):
        bsadf = None

        if idx + 1 >= min_win:
            # 对所有起点 r1, 计算 ADF[r1 .. idx]
            max_stat = None
            # r1 从 0 到 idx - min_win + 1
            for r1 in range(0, idx - min_win + 2):
                segment = log_prices[r1: idx + 1]
                stat = _ols_adf_stat(segment)
                if stat is not None:
                    if max_stat is None or stat > max_stat:
                        max_stat = stat
            bsadf = max_stat

        row: dict = {
            "trading_day": day,
            "log_price": round(log_prices[idx], 4),
            "cv_95": round(cv, 4),
        }
        if bsadf is not None:
            row["bsadf_stat"] = round(bsadf, 4)
            row["bubble_signal"] = 1 if bsadf > cv else 0
        result.append(row)

    return result
