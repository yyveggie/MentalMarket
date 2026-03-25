"""纯技术指标计算函数（无外部依赖）。

被 agent.py（Prompt 嵌入层）和 dashboard/server.py（看板）复用。
"""

from __future__ import annotations

import math
from statistics import pstdev


def sma(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def ema(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    result = sum(values[:period]) / period
    for price in values[period:]:
        result = alpha * price + (1.0 - alpha) * result
    return result


def rsi(values: list[float], period: int) -> float | None:
    """Wilder RSI：使用指数平滑计算 avg_gain/avg_loss。"""
    if period <= 0 or len(values) < period + 1:
        return None
    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            avg_gain += delta
        else:
            avg_loss += -delta
    avg_gain /= period
    avg_loss /= period
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            avg_gain = (avg_gain * (period - 1) + delta) / period
            avg_loss = (avg_loss * (period - 1)) / period
        else:
            avg_gain = (avg_gain * (period - 1)) / period
            avg_loss = (avg_loss * (period - 1) + (-delta)) / period
    if avg_loss == 0:
        return 50.0 if avg_gain == 0 else 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def volatility(prices: list[float]) -> float | None:
    if len(prices) < 2:
        return None
    returns: list[float] = []
    for prev, curr in zip(prices[:-1], prices[1:]):
        if prev > 0:
            returns.append((curr - prev) / prev)
    if len(returns) < 2:
        return None
    return pstdev(returns)


def momentum(prices: list[float], period: int) -> float | None:
    if period <= 0 or len(prices) <= period:
        return None
    prev = prices[-period - 1]
    if prev <= 0:
        return None
    return (prices[-1] - prev) / prev


def vwap(trades) -> float | None:
    if not trades:
        return None
    total_notional = 0.0
    total_qty = 0
    for t in trades:
        total_notional += float(t.price) * int(t.quantity)
        total_qty += int(t.quantity)
    if total_qty <= 0:
        return None
    return total_notional / total_qty


def autocorrelation(returns: list[float], lag: int = 1) -> float | None:
    """计算收益率序列的自相关系数。"""
    n = len(returns)
    if n < lag + 2:
        return None
    mean = sum(returns) / n
    c0 = sum((r - mean) ** 2 for r in returns)
    if c0 <= 0:
        return None
    ck = sum((returns[i] - mean) * (returns[i - lag] - mean) for i in range(lag, n))
    return ck / c0


def variance_ratio(prices: list[float], period: int = 5) -> float | None:
    """方差比检验：VR(q) = Var(q期收益) / (q * Var(1期收益))。VR≈1 表示随机游走。"""
    n = len(prices)
    if n < period + 2:
        return None
    r1 = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, n) if prices[i - 1] > 0]
    rq = [(prices[i] - prices[i - period]) / prices[i - period]
          for i in range(period, n) if prices[i - period] > 0]
    if len(r1) < 2 or len(rq) < 2:
        return None
    var1 = pstdev(r1) ** 2
    varq = pstdev(rq) ** 2
    if var1 <= 0:
        return None
    return varq / (period * var1)


def amihud_illiquidity(daily_returns: list[float], daily_volumes: list[float]) -> float | None:
    """Amihud 非流动性指标（日度粒度）：average(|日收益率| / 日成交额)。
    
    参数为已聚合的日度数据序列：daily_returns[i] 对应第 i 日的收益率，
    daily_volumes[i] 对应第 i 日的总成交额。
    """
    n = min(len(daily_returns), len(daily_volumes))
    if n < 1:
        return None
    ratios: list[float] = []
    for i in range(n):
        if daily_volumes[i] <= 0:
            continue
        ratios.append(abs(daily_returns[i]) / daily_volumes[i])
    if not ratios:
        return None
    return sum(ratios) / len(ratios)


def hurst_exponent_rs(prices: list[float]) -> float | None:
    """R/S 分析法估算 Hurst 指数（多子区间平均）。H>0.5 趋势性，H<0.5 均值回归，H≈0.5 随机游走。"""
    n = len(prices)
    if n < 20:
        return None
    returns = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, n) if prices[i - 1] > 0]
    total = len(returns)
    if total < 16:
        return None

    from math import log

    def _rs_for_chunk(chunk: list[float]) -> float | None:
        size = len(chunk)
        if size < 4:
            return None
        mean = sum(chunk) / size
        cumdev = []
        s = 0.0
        for r in chunk:
            s += r - mean
            cumdev.append(s)
        range_val = max(cumdev) - min(cumdev)
        std_val = pstdev(chunk)
        return (range_val / std_val) if std_val > 0 else None

    rs_values: list[tuple[float, float]] = []
    for sub_size in [total // 8, total // 4, total // 2, total]:
        if sub_size < 4:
            continue
        n_subs = total // sub_size
        if n_subs < 1:
            continue
        sub_rs: list[float] = []
        for j in range(n_subs):
            chunk = returns[j * sub_size : (j + 1) * sub_size]
            val = _rs_for_chunk(chunk)
            if val is not None and val > 0:
                sub_rs.append(val)
        if sub_rs:
            avg_rs = sum(sub_rs) / len(sub_rs)
            rs_values.append((float(sub_size), avg_rs))

    if len(rs_values) < 2:
        return None
    log_n = [log(x[0]) for x in rs_values]
    log_rs = [log(x[1]) for x in rs_values]
    n_pts = len(log_n)
    mean_x = sum(log_n) / n_pts
    mean_y = sum(log_rs) / n_pts
    numer = sum((log_n[i] - mean_x) * (log_rs[i] - mean_y) for i in range(n_pts))
    denom = sum((log_n[i] - mean_x) ** 2 for i in range(n_pts))
    if denom <= 0:
        return None
    return numer / denom


def gini_coefficient(sorted_values: list[float]) -> float:
    """基尼系数：输入必须为升序排列的非负值列表。0=完全平等，1=完全不平等。"""
    n = len(sorted_values)
    if n < 2:
        return 0.0
    total = sum(sorted_values)
    if total <= 0:
        return 0.0
    weighted_sum = 0.0
    for i, v in enumerate(sorted_values):
        weighted_sum += (2 * (i + 1) - n - 1) * v
    return weighted_sum / (n * total)


def compute_trading_day(sim_time: float, snapshot_interval: float) -> int:
    """根据仿真时间和快照间隔计算交易日编号（从 1 开始）。"""
    if snapshot_interval <= 0:
        return 0
    return int(sim_time // snapshot_interval) + 1


def round_or_none(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        return None
    return round(float(value), digits)
