"""
学术恐慌/市场压力指标
====================

基于已有仿真数据（broad_index.jsonl + trades.jsonl）
事后计算市场恐慌信号，替代原有自定义 panic_flag。

指标:
1. Amihud 非流动性比率 (Amihud, 2002)
2. 成交量异常倍率
3. 已实现波动率 z-score
4. 综合恐慌信号（三合一）
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path


def _iter_jsonl(path: Path):
    try:
        import orjson
        with open(path, "rb") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield orjson.loads(line)
                    except Exception:
                        continue
    except ImportError:
        import json
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except Exception:
                        continue


def compute_panic_indicators(
    run_dir: Path | str,
    vol_window: int = 10,
    amihud_window: int = 10,
    volume_window: int = 10,
    zscore_threshold: float = 2.0,
) -> list[dict]:
    """
    计算学术恐慌指标。

    Parameters
    ----------
    run_dir : Path
        仿真运行目录
    vol_window : int
        已实现波动率滚动窗口（天），默认 10
    amihud_window : int
        Amihud 非流动性滚动窗口（天），默认 10
    volume_window : int
        成交量滚动基准窗口（天），默认 10
    zscore_threshold : float
        z-score 阈值，超过此值视为异常，默认 2.0

    Returns
    -------
    list[dict]
        每日一行，包含:
        - trading_day
        - log_return: 对数收益率
        - realized_vol: 滚动已实现波动率
        - vol_zscore: 波动率相对历史均值的 z-score
        - daily_volume: 日成交量（股）
        - daily_turnover: 日成交额
        - volume_ratio: 成交量 / 滚动均值
        - amihud_illiq: Amihud 非流动性 = |r| / 成交额
        - amihud_zscore: Amihud 相对历史均值的 z-score
        - panic_flag: 综合恐慌信号 (0/1)
    """
    run_dir = Path(run_dir)

    # ── 1. 读取 broad_index → 日收益率 ──
    bi_path = run_dir / "broad_index.jsonl"
    if not bi_path.exists():
        return []

    day_close: dict[int, float] = {}
    for rec in _iter_jsonl(bi_path):
        d = rec.get("trading_day")
        v = rec.get("value")
        if d is not None and v is not None:
            day_close[d] = v

    if len(day_close) < 3:
        return []

    sorted_days = sorted(day_close.keys())

    # 对数收益率
    log_returns: dict[int, float] = {}
    for i in range(1, len(sorted_days)):
        d_prev, d_curr = sorted_days[i - 1], sorted_days[i]
        p_prev, p_curr = day_close[d_prev], day_close[d_curr]
        if p_prev > 0 and p_curr > 0:
            log_returns[d_curr] = math.log(p_curr / p_prev)

    # ── 2. 读取 trades → 日成交量 & 成交额 ──
    trades_path = run_dir / "trades.jsonl"
    day_volume: dict[int, int] = defaultdict(int)
    day_turnover: dict[int, float] = defaultdict(float)

    if trades_path.exists():
        for rec in _iter_jsonl(trades_path):
            if rec.get("is_seed_trade"):
                continue
            d = rec.get("trading_day")
            qty = rec.get("quantity", 0)
            px = rec.get("price", 0)
            if d is not None:
                day_volume[d] += qty
                day_turnover[d] += px * qty

    # ── 3. 滚动计算 ──
    def _rolling_mean_std(values: list, window: int, idx: int):
        """返回 idx 之前 window 个值的 (mean, std)"""
        start = max(0, idx - window)
        segment = values[start:idx]
        if len(segment) < 2:
            return None, None
        m = sum(segment) / len(segment)
        var = sum((x - m) ** 2 for x in segment) / (len(segment) - 1)
        return m, var ** 0.5

    # 按交易日排序构建时间序列
    active_days = sorted(d for d in sorted_days if d in log_returns)
    if not active_days:
        return []

    returns_list = [log_returns[d] for d in active_days]
    volumes_list = [day_volume.get(d, 0) for d in active_days]
    turnovers_list = [day_turnover.get(d, 0) for d in active_days]

    # Amihud 非流动性: |r_t| / turnover_t
    amihud_list = []
    for r, tv in zip(returns_list, turnovers_list):
        if tv > 0:
            amihud_list.append(abs(r) / tv)
        else:
            amihud_list.append(0.0)

    # 已实现波动率: 滚动 std(r)
    # 先计算每天的 realized_vol，再统一做 z-score
    realized_vols: list[float | None] = []
    for i in range(len(active_days)):
        if i >= vol_window:
            segment = returns_list[i - vol_window:i]
            m = sum(segment) / len(segment)
            rv = (sum((x - m) ** 2 for x in segment) / (len(segment) - 1)) ** 0.5
            realized_vols.append(rv)
        else:
            realized_vols.append(None)

    rows = []
    for i, d in enumerate(active_days):
        ret = returns_list[i]
        vol = volumes_list[i]
        tv = turnovers_list[i]
        ami = amihud_list[i]
        realized_vol = realized_vols[i]

        # ━━ 波动率 z-score（对 realized_vol 序列自身做 z-score）━━
        vol_zscore = None
        if realized_vol is not None:
            past_rvs: list[float] = [v for v in realized_vols[vol_window:i] if v is not None]
            if len(past_rvs) >= 2:
                rv_m = sum(past_rvs) / len(past_rvs)
                rv_s = (sum((x - rv_m) ** 2 for x in past_rvs) / (len(past_rvs) - 1)) ** 0.5
                if rv_s > 1e-12:
                    vol_zscore = (realized_vol - rv_m) / rv_s

        # ━━ 成交量异常倍率 ━━
        vm_mean, _ = _rolling_mean_std(volumes_list, volume_window, i)
        volume_ratio = vol / vm_mean if vm_mean and vm_mean > 0 else None

        # ━━ Amihud z-score ━━
        ami_mean, ami_std = _rolling_mean_std(amihud_list, amihud_window, i)
        amihud_zscore = None
        if ami_mean is not None and ami_std is not None and ami_std > 1e-12:
            amihud_zscore = (ami - ami_mean) / ami_std

        # ━━ 综合恐慌信号 ━━
        # 三条件: (1) 负收益 (2) 至少一项异常飙升 (3) Amihud 或波动率 z-score 超阈值
        is_negative_return = ret < 0
        vol_spike = vol_zscore is not None and vol_zscore > zscore_threshold
        ami_spike = amihud_zscore is not None and amihud_zscore > zscore_threshold
        volume_spike = volume_ratio is not None and volume_ratio > (1 + zscore_threshold * 0.5)
        panic = is_negative_return and (vol_spike or ami_spike) and (ami_spike or volume_spike)

        rows.append({
            "trading_day": d,
            "log_return": round(ret, 6),
            "realized_vol": round(realized_vol, 6) if realized_vol is not None else None,
            "vol_zscore": round(vol_zscore, 4) if vol_zscore is not None else None,
            "daily_volume": vol,
            "daily_turnover": round(tv, 2),
            "volume_ratio": round(volume_ratio, 4) if volume_ratio is not None else None,
            "amihud_illiq": round(ami, 10) if ami else 0,
            "amihud_zscore": round(amihud_zscore, 4) if amihud_zscore is not None else None,
            "panic_flag": 1 if panic else 0,
        })

    return rows
