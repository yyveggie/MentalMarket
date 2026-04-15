#!/usr/bin/env python3
"""扩展拟合指标：KS检验、Wasserstein距离、DTW、MAPE、Theil's U、QLIKE、Ljung-Box Q差异、偏度/峰度匹配。

用法:
    python evaluation/metric_fit_extended.py <run_dir> \
        --real-curves data/index_volatility_curves.json \
        --profile-csv data/stock_profile.csv

输出: JSON 到 stdout + output/扩展拟合指标_{run_label}.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy import stats as sp_stats

# ── 加载辅助 (与 metric_fit_accuracy 同口径) ──
sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_loader import (
    load_real_curves,
    build_sim_close_by_day,
    remap_sim_close_to_trading_days,
    resolve_existing_path,
    resolve_calendar_news_file,
    load_closed_dates_from_calendar_news,
    resolve_include_closed_days,
    aligned_real_sim_with_day,
    _build_nonseed_close_map,
)
from metrics_plot_common import read_jsonl
from metric_fit_accuracy import (
    build_aligned_broad,
    build_weighted_close_by_day,
    BROAD_EQW_SYMBOL,
)


# ═══════════════════════════════════════════════════════════
# 1. KS 检验 (Kolmogorov-Smirnov)
# ═══════════════════════════════════════════════════════════
def ks_test(real_rets: np.ndarray, sim_rets: np.ndarray) -> dict:
    stat, pval = sp_stats.ks_2samp(real_rets, sim_rets)
    return {"ks_stat": float(stat), "ks_pvalue": float(pval)}


# ═══════════════════════════════════════════════════════════
# 2. Wasserstein 距离 (Earth Mover's Distance)
# ═══════════════════════════════════════════════════════════
def wasserstein(real_rets: np.ndarray, sim_rets: np.ndarray) -> dict:
    d = float(sp_stats.wasserstein_distance(real_rets, sim_rets))
    return {"wasserstein": d}


# ═══════════════════════════════════════════════════════════
# 3. DTW (Dynamic Time Warping)  —  轻量 O(n²) 实现
# ═══════════════════════════════════════════════════════════
def dtw_distance(s: np.ndarray, t: np.ndarray) -> float:
    n, m = len(s), len(t)
    dtw_mat = np.full((n + 1, m + 1), np.inf)
    dtw_mat[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(s[i - 1] - t[j - 1])
            dtw_mat[i, j] = cost + min(dtw_mat[i - 1, j], dtw_mat[i, j - 1], dtw_mat[i - 1, j - 1])
    return float(dtw_mat[n, m])


def dtw_metric(real_norm: np.ndarray, sim_norm: np.ndarray) -> dict:
    d = dtw_distance(real_norm, sim_norm)
    # 归一化为路径平均距离
    path_len = len(real_norm) + len(sim_norm)
    return {"dtw_raw": d, "dtw_normalized": d / path_len if path_len else 0.0}


# ═══════════════════════════════════════════════════════════
# 4. MAPE (Mean Absolute Percentage Error)
# ═══════════════════════════════════════════════════════════
def mape(real_norm: np.ndarray, sim_norm: np.ndarray) -> dict:
    mask = np.abs(real_norm) > 1e-9
    if mask.sum() == 0:
        return {"mape": None}
    v = float(np.mean(np.abs((real_norm[mask] - sim_norm[mask]) / real_norm[mask])) * 100)
    return {"mape": v}


# ═══════════════════════════════════════════════════════════
# 5. Theil's U statistic
# ═══════════════════════════════════════════════════════════
def theil_u(real_rets: np.ndarray, sim_rets: np.ndarray) -> dict:
    n = len(real_rets)
    if n < 2:
        return {"theil_u1": None, "theil_u2": None}
    # U1
    num1 = math.sqrt(np.mean((real_rets - sim_rets) ** 2))
    den1 = math.sqrt(np.mean(real_rets ** 2)) + math.sqrt(np.mean(sim_rets ** 2))
    u1 = num1 / den1 if den1 > 1e-12 else None

    # U2: relative to naive (no-change) forecast
    naive = np.zeros_like(real_rets)  # naive: 预测收益率为 0
    mse_model = float(np.mean((real_rets - sim_rets) ** 2))
    mse_naive = float(np.mean((real_rets - naive) ** 2))
    u2 = math.sqrt(mse_model / mse_naive) if mse_naive > 1e-12 else None

    return {"theil_u1": float(u1) if u1 is not None else None,
            "theil_u2": float(u2) if u2 is not None else None}


# ═══════════════════════════════════════════════════════════
# 6. QLIKE (Quasi-Likelihood for Volatility)
# ═══════════════════════════════════════════════════════════
def qlike(real_rets: np.ndarray, sim_rets: np.ndarray, window: int = 5) -> dict:
    """滚动窗口波动率 QLIKE 损失 (Patton 2011)。"""
    n = len(real_rets)
    if n < window + 1:
        return {"qlike": None}
    real_vol = np.array([np.var(real_rets[max(0, i - window):i]) for i in range(window, n)])
    sim_vol = np.array([np.var(sim_rets[max(0, i - window):i]) for i in range(window, n)])
    eps = 1e-8
    real_vol = np.maximum(real_vol, eps)
    sim_vol = np.maximum(sim_vol, eps)
    losses = real_vol / sim_vol - np.log(real_vol / sim_vol) - 1.0
    # Winsorize at 95th percentile
    cap = float(np.percentile(losses, 95))
    losses = np.minimum(losses, cap)
    return {"qlike": float(np.mean(losses))}


# ═══════════════════════════════════════════════════════════
# 7. Ljung-Box Q差异 (自相关结构对比)
# ═══════════════════════════════════════════════════════════
def ljung_box_compare(real_rets: np.ndarray, sim_rets: np.ndarray, max_lag: int = 10) -> dict:
    """比较真实/模拟绝对收益率的 Ljung-Box Q 统计量。"""
    def _lb_stat(x: np.ndarray, lags: int) -> float | None:
        n = len(x)
        if n < lags + 2:
            return None
        xm = x - np.mean(x)
        c0 = float(np.sum(xm ** 2))
        if c0 < 1e-15:
            return None
        q = 0.0
        for k in range(1, lags + 1):
            rk = float(np.sum(xm[:n - k] * xm[k:])) / c0
            q += rk ** 2 / (n - k)
        return n * (n + 2) * q

    qr = _lb_stat(np.abs(real_rets), max_lag)
    qs = _lb_stat(np.abs(sim_rets), max_lag)
    ratio = None
    if qr is not None and qs is not None and qr > 1e-12:
        ratio = qs / qr
    return {"lb_q_real": qr, "lb_q_sim": qs, "lb_q_ratio": ratio}


# ═══════════════════════════════════════════════════════════
# 8. 偏度 / 峰度匹配
# ═══════════════════════════════════════════════════════════
def moment_match(real_rets: np.ndarray, sim_rets: np.ndarray) -> dict:
    r_skew = float(sp_stats.skew(real_rets))
    s_skew = float(sp_stats.skew(sim_rets))
    r_kurt = float(sp_stats.kurtosis(real_rets, fisher=True))
    s_kurt = float(sp_stats.kurtosis(sim_rets, fisher=True))
    return {
        "real_skewness": r_skew, "sim_skewness": s_skew, "skew_diff": abs(r_skew - s_skew),
        "real_kurtosis": r_kurt, "sim_kurtosis": s_kurt, "kurt_diff": abs(r_kurt - s_kurt),
    }


# ═══════════════════════════════════════════════════════════
# 组装：per-symbol + overall
# ═══════════════════════════════════════════════════════════
def _returns(prices: np.ndarray) -> np.ndarray:
    return np.diff(prices) / np.maximum(np.abs(prices[:-1]), 1e-12)


def _norm_series(prices: np.ndarray) -> np.ndarray:
    return prices / prices[0] * 100 if abs(prices[0]) > 1e-9 else prices


def compute_extended_for_symbol(aligned: list[tuple[int, float, float]]) -> dict:
    if len(aligned) < 5:
        return {}
    days = np.array([a[0] for a in aligned])
    rp = np.array([a[1] for a in aligned])
    sp = np.array([a[2] for a in aligned])

    # 只取连续日
    consec = np.where(np.diff(days) == 1)[0]
    if len(consec) < 3:
        return {}
    rr = _returns(rp)[consec]
    sr = _returns(sp)[consec]
    rn = _norm_series(rp)
    sn = _norm_series(sp)

    result = {}
    result.update(ks_test(rr, sr))
    result.update(wasserstein(rr, sr))
    result.update(dtw_metric(rn, sn))
    result.update(mape(rn, sn))
    result.update(theil_u(rr, sr))
    result.update(qlike(rr, sr))
    result.update(ljung_box_compare(rr, sr))
    result.update(moment_match(rr, sr))
    return result


def _weighted_avg(vals: list[float | None], weights: list[float]) -> float | None:
    pairs = [(v, w) for v, w in zip(vals, weights) if v is not None]
    if not pairs:
        return None
    tw = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / tw if tw > 0 else None


def compute_overall_extended(per_sym: dict[str, dict], profile_weights: dict[str, float] | None) -> dict:
    syms = sorted(per_sym.keys())
    if not syms:
        return {}
    ws = [profile_weights.get(s, 1.0) if profile_weights else 1.0 for s in syms]
    keys = list(per_sym[syms[0]].keys()) if syms else []

    overall = {}
    for k in keys:
        vals = [per_sym[s].get(k) for s in syms]
        overall[k] = _weighted_avg(vals, ws)
    return overall


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════
def _load_profile_weights(path: Path) -> dict[str, float] | None:
    import csv
    if not path.exists():
        return None
    weights = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sym = row.get("stock_id", "").strip()
            w = float(row.get("weight", 0))
            if sym and w > 0:
                weights[sym] = w
    if not weights:
        return None
    total = sum(weights.values())
    return {s: w / total for s, w in weights.items()}


def main():
    parser = argparse.ArgumentParser(description="扩展拟合指标")
    parser.add_argument("run_dir")
    parser.add_argument("--real-curves", default="data/index_volatility_curves.json")
    parser.add_argument("--profile-csv", default="data/stock_profile.csv")
    parser.add_argument("--include-closed-days", default="auto")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    include_closed = resolve_include_closed_days(run_dir, args.include_closed_days)
    calendar_news_file = resolve_calendar_news_file(run_dir)
    closed_dates_hint = set() if include_closed else load_closed_dates_from_calendar_news(calendar_news_file)
    real_path = resolve_existing_path(args.real_curves, run_dir)
    _, real_close, _, open_day_of_all_day = load_real_curves(real_path, include_closed_days=include_closed, closed_dates_hint=closed_dates_hint)
    snapshot_rows = read_jsonl(run_dir / "market_snapshots.jsonl")
    sim_close_all = build_sim_close_by_day(snapshot_rows, nonseed_map=_build_nonseed_close_map(run_dir))
    sim_close = remap_sim_close_to_trading_days(sim_close_all, open_day_of_all_day)
    max_day = 0
    for dmap in sim_close.values():
        if dmap:
            max_day = max(max_day, max(dmap.keys()))

    symbols = sorted(set(real_close) & set(sim_close))
    profile_weights = None
    try:
        profile_weights = _load_profile_weights(resolve_existing_path(args.profile_csv, run_dir))
    except FileNotFoundError:
        pass

    per_symbol = {}
    for sym in symbols:
        aligned = aligned_real_sim_with_day(sym, real_close, sim_close, max_day)
        metrics = compute_extended_for_symbol(aligned)
        if metrics:
            per_symbol[sym] = metrics

    # 大盘合成（逐天取 real/sim 交集成分，确保两边一致）
    if len(symbols) >= 2:
        broad_real, broad_sim = build_aligned_broad(real_close, sim_close, symbols, max_day, weights=profile_weights)
        if broad_real and broad_sim:
            broad_aligned = []
            for d in sorted(broad_real):
                broad_aligned.append((d, broad_real[d], broad_sim[d]))
            bm = compute_extended_for_symbol(broad_aligned)
            if bm:
                per_symbol[BROAD_EQW_SYMBOL] = bm

    overall = compute_overall_extended(
        {s: v for s, v in per_symbol.items() if s != BROAD_EQW_SYMBOL},
        profile_weights,
    )

    run_label = run_dir.name
    report = {
        "run_dir": str(run_dir),
        "run_label": run_label,
        "overall": overall,
        "broad_index": per_symbol.get(BROAD_EQW_SYMBOL, {}),
        "per_symbol": {s: v for s, v in per_symbol.items() if s != BROAD_EQW_SYMBOL},
    }

    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"扩展拟合指标_{run_label}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"overall": overall, "broad_index": per_symbol.get(BROAD_EQW_SYMBOL, {}), "report": str(out_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
