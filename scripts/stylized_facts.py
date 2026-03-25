#!/usr/bin/env python3
"""
Stylized Facts Analysis — Rama Cont (2001) 11 项金融典型事实检验

用法:
  python scripts/stylized_facts.py runs/20260323_213251_tom2
  python scripts/stylized_facts.py runs/20260325_095857 --symbol CGEI
  python scripts/stylized_facts.py runs/20260323_213251_tom2 --interval 3600  # 按交易日聚合

参考文献:
  Cont, R. (2001). Empirical properties of asset returns: stylized facts
  and statistical issues. Quantitative finance, 1(2), 223.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


def load_trades(run_dir: str, symbol: str | None = None) -> list[dict]:
    path = Path(run_dir) / "trades.jsonl"
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)
    trades = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            t = json.loads(line)
            if t.get("is_seed_trade"):
                continue
            if symbol and str(t.get("symbol", "")).upper() != symbol.upper():
                continue
            trades.append(t)
    trades.sort(key=lambda t: float(t.get("sim_time", 0)))
    return trades


def aggregate_returns(trades: list[dict], interval: float) -> tuple[list[float], list[float], list[float]]:
    """按固定时间窗口聚合成交数据，返回 (returns, volumes, timestamps)。"""
    if not trades:
        return [], [], []

    by_bucket: dict[int, list[dict]] = defaultdict(list)
    for t in trades:
        bucket = int(float(t["sim_time"]) // interval)
        by_bucket[bucket].append(t)

    sorted_buckets = sorted(by_bucket.keys())
    prices = []
    volumes = []
    timestamps = []
    for b in sorted_buckets:
        bucket_trades = by_bucket[b]
        total_qty = sum(int(t.get("quantity", 0)) for t in bucket_trades)
        total_amount = sum(float(t.get("price", 0)) * int(t.get("quantity", 0)) for t in bucket_trades)
        vwap = total_amount / total_qty if total_qty > 0 else float(bucket_trades[-1].get("price", 0))
        prices.append(vwap)
        volumes.append(float(total_qty))
        timestamps.append(b * interval)

    returns = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0:
            returns.append(math.log(prices[i] / prices[i - 1]))
        else:
            returns.append(0.0)

    return returns, volumes[1:], timestamps[1:]


def autocorrelation(series: list[float], lag: int) -> float | None:
    n = len(series)
    if n <= lag or n < 3:
        return None
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series)
    if var < 1e-15:
        return 0.0
    cov = sum((series[i] - mean) * (series[i + lag] - mean) for i in range(n - lag))
    return cov / var


def kurtosis(series: list[float]) -> float | None:
    n = len(series)
    if n < 4:
        return None
    mean = sum(series) / n
    m2 = sum((x - mean) ** 2 for x in series) / n
    m4 = sum((x - mean) ** 4 for x in series) / n
    if m2 < 1e-15:
        return 0.0
    return m4 / (m2 ** 2) - 3.0  # excess kurtosis


def skewness(series: list[float]) -> float | None:
    n = len(series)
    if n < 3:
        return None
    mean = sum(series) / n
    m2 = sum((x - mean) ** 2 for x in series) / n
    m3 = sum((x - mean) ** 3 for x in series) / n
    if m2 < 1e-15:
        return 0.0
    return m3 / (m2 ** 1.5)


def pearson_corr(x: list[float], y: list[float]) -> float | None:
    n = min(len(x), len(y))
    if n < 3:
        return None
    mx = sum(x[:n]) / n
    my = sum(y[:n]) / n
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    dx = sum((x[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((y[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx * dy < 1e-15:
        return 0.0
    return num / (dx * dy)


def fano_factor(events: list[int], window: int = 10) -> float | None:
    """法诺因子：方差/均值，>1 表示聚集性。"""
    if len(events) < window * 2:
        return None
    counts = []
    for i in range(0, len(events) - window + 1, window):
        counts.append(sum(events[i:i + window]))
    if not counts:
        return None
    mean_c = sum(counts) / len(counts)
    if mean_c < 1e-10:
        return None
    var_c = sum((c - mean_c) ** 2 for c in counts) / len(counts)
    return var_c / mean_c


def fit_simple_garch(returns: list[float]) -> tuple[list[float], float, float, float]:
    """GARCH(1,1) 拟合，返回 (残差序列, omega, alpha, beta)。
    优先使用 scipy 做 MLE 估计，不可用时退化为矩估计。"""
    n = len(returns)
    if n < 20:
        return returns, 0, 0, 0

    var_unconditional = sum(r ** 2 for r in returns) / n

    def _garch_loglik(params: tuple[float, float, float]) -> float:
        omega_p, alpha_p, beta_p = params
        if omega_p <= 0 or alpha_p < 0 or beta_p < 0 or alpha_p + beta_p >= 1:
            return 1e10
        s2 = var_unconditional
        ll = 0.0
        for i in range(n):
            if i > 0:
                s2 = omega_p + alpha_p * returns[i - 1] ** 2 + beta_p * s2
            s2 = max(s2, 1e-10)
            ll += math.log(s2) + returns[i] ** 2 / s2
        return ll

    omega, alpha, beta = var_unconditional * 0.05, 0.10, 0.85
    try:
        from scipy.optimize import minimize
        res = minimize(_garch_loglik, (omega, alpha, beta),
                       method="Nelder-Mead", options={"maxiter": 500, "xatol": 1e-6})
        if res.success and res.x[0] > 0 and res.x[1] >= 0 and res.x[2] >= 0 and res.x[1] + res.x[2] < 1:
            omega, alpha, beta = float(res.x[0]), float(res.x[1]), float(res.x[2])
    except ImportError:
        pass

    sigma2 = [var_unconditional]
    for i in range(1, n):
        s2 = omega + alpha * returns[i - 1] ** 2 + beta * sigma2[i - 1]
        sigma2.append(max(s2, 1e-10))

    residuals = [returns[i] / math.sqrt(sigma2[i]) if sigma2[i] > 1e-10 else 0.0 for i in range(n)]
    return residuals, omega, alpha, beta


def compute_all_stylized_facts(returns: list[float], volumes: list[float], interval: float) -> dict:
    n = len(returns)
    results: dict[str, dict] = {}

    # SF1: Absence of autocorrelations
    ac_lags = [1, 2, 5, 10]
    ac_values = {}
    for lag in ac_lags:
        ac = autocorrelation(returns, lag)
        if ac is not None:
            ac_values[f"lag_{lag}"] = round(ac, 4)
    max_ac = max(abs(v) for v in ac_values.values()) if ac_values else None
    results["SF01_自相关性缺失"] = {
        "autocorrelations": ac_values,
        "max_abs_autocorr": round(max_ac, 4) if max_ac is not None else None,
        "passed": max_ac is not None and max_ac < 0.1,
        "interpretation": "max |AC| < 0.1 → 符合自相关性缺失（有效市场特征）",
    }

    # SF2: Heavy tails
    kurt = kurtosis(returns)
    results["SF02_长尾分布"] = {
        "excess_kurtosis": round(kurt, 4) if kurt is not None else None,
        "passed": kurt is not None and kurt > 0,
        "interpretation": "excess kurtosis > 0 → 厚尾分布（极端事件概率高于正态）",
    }

    # SF3: Gain/loss asymmetry
    skew = skewness(returns)
    results["SF03_收益损失不对称性"] = {
        "skewness": round(skew, 4) if skew is not None else None,
        "passed": skew is not None and skew < -0.1,
        "interpretation": "skewness < -0.1 → 负偏（大跌比大涨更常见）。注：现代市场此特征常不显著",
    }

    # SF4: Aggregational Gaussianity
    agg_kurtosis = {}
    for scale in [1, 2, 5, 10]:
        if scale == 1:
            agg_kurtosis[f"scale_{scale}"] = round(kurt, 4) if kurt is not None else None
        else:
            agg_returns = []
            for i in range(0, n - scale + 1, scale):
                agg_returns.append(sum(returns[i:i + scale]))
            k = kurtosis(agg_returns)
            agg_kurtosis[f"scale_{scale}"] = round(k, 4) if k is not None else None
    vals = [v for v in agg_kurtosis.values() if v is not None]
    decreasing = len(vals) >= 2 and vals[-1] < vals[0]
    results["SF04_聚集高斯性"] = {
        "kurtosis_by_scale": agg_kurtosis,
        "passed": decreasing,
        "interpretation": "随时间窗口增大，峰度递减趋近0（趋向正态分布）",
    }

    # SF5: Intermittency
    abs_returns = [abs(r) for r in returns]
    if abs_returns:
        threshold = sorted(abs_returns)[int(len(abs_returns) * 0.99)] if len(abs_returns) > 100 else max(abs_returns) * 0.8
        extreme_flags = [1 if abs(r) >= threshold else 0 for r in returns]
        ff = fano_factor(extreme_flags, window=max(5, n // 20))
    else:
        ff = None
    results["SF05_间歇性"] = {
        "fano_factor": round(ff, 4) if ff is not None else None,
        "passed": ff is not None and ff > 1.0,
        "interpretation": "Fano factor > 1 → 极端事件聚集出现（非泊松过程）",
    }

    # SF6: Volatility clustering
    abs_ac_values = {}
    for lag in [1, 2, 5, 10]:
        ac = autocorrelation(abs_returns, lag)
        if ac is not None:
            abs_ac_values[f"lag_{lag}"] = round(ac, 4)
    ac1 = abs_ac_values.get("lag_1")
    results["SF06_波动率聚集"] = {
        "abs_return_autocorrelations": abs_ac_values,
        "passed": ac1 is not None and ac1 > 0.05,
        "interpretation": "|returns| 的自相关 > 0 → 高波动后继续高波动（聚集效应）",
    }

    # SF7: Conditional heavy tails
    residuals, omega, alpha, beta = fit_simple_garch(returns)
    resid_kurt = kurtosis(residuals)
    results["SF07_条件长尾"] = {
        "garch_params": {"omega": round(omega, 6), "alpha": round(alpha, 4), "beta": round(beta, 4)},
        "residual_kurtosis": round(resid_kurt, 4) if resid_kurt is not None else None,
        "passed": resid_kurt is not None and resid_kurt > 0,
        "interpretation": "GARCH 残差仍有正峰度 → 即使去除波动率聚集后仍有厚尾",
    }

    # SF8: Slow decay of autocorrelation in absolute returns
    decay_lags = [1, 5, 10, 20, 50]
    decay_values = {}
    for lag in decay_lags:
        ac = autocorrelation(abs_returns, lag)
        if ac is not None:
            decay_values[f"lag_{lag}"] = round(ac, 4)
    vals_decay = [v for v in decay_values.values() if v is not None]
    slow_decay = len(vals_decay) >= 3 and vals_decay[-1] > 0.01
    results["SF08_绝对收益自相关缓慢衰减"] = {
        "abs_return_autocorrelations_extended": decay_values,
        "passed": slow_decay,
        "interpretation": "高滞后阶数的绝对收益自相关仍显著 → 长程依赖",
    }

    # SF9: Leverage effect
    sq_returns = [r ** 2 for r in returns]
    if n >= 5:
        shifted_returns = returns[:-1]
        shifted_sq = sq_returns[1:]
        lev_corr = pearson_corr(shifted_returns, shifted_sq)
    else:
        lev_corr = None
    results["SF09_杠杆效应"] = {
        "return_volatility_correlation": round(lev_corr, 4) if lev_corr is not None else None,
        "passed": lev_corr is not None and lev_corr < -0.05,
        "interpretation": "r(t) 与 r²(t+1) 负相关 → 下跌时波动率放大。注：现代市场常不显著",
    }

    # SF10: Volume/volatility correlation
    if volumes and len(volumes) == n:
        vol_corr = pearson_corr(volumes, abs_returns)
    else:
        vol_corr = None
    results["SF10_成交量波动率相关"] = {
        "volume_volatility_correlation": round(vol_corr, 4) if vol_corr is not None else None,
        "passed": vol_corr is not None and vol_corr > 0.05,
        "interpretation": "成交量与波动率正相关 → 大波动伴随大成交量",
    }

    # SF11: Asymmetry in time scales
    if n >= 20:
        fine_vol = abs_returns
        coarse_vol = []
        coarse_window = 5
        for i in range(len(fine_vol) - coarse_window + 1):
            coarse_vol.append(sum(fine_vol[i:i + coarse_window]) / coarse_window)
        coarse_to_fine = pearson_corr(coarse_vol[:-1], fine_vol[coarse_window:coarse_window + len(coarse_vol) - 1]) if len(coarse_vol) > 1 else None
        fine_to_coarse = pearson_corr(fine_vol[:len(coarse_vol) - 1], coarse_vol[1:]) if len(coarse_vol) > 1 else None
    else:
        coarse_to_fine = None
        fine_to_coarse = None
    results["SF11_时间尺度不对称性"] = {
        "coarse_predicts_fine": round(coarse_to_fine, 4) if coarse_to_fine is not None else None,
        "fine_predicts_coarse": round(fine_to_coarse, 4) if fine_to_coarse is not None else None,
        "passed": (coarse_to_fine is not None and fine_to_coarse is not None
                   and coarse_to_fine > fine_to_coarse + 0.02),
        "interpretation": "粗粒度波动率对细粒度的预测力 > 反向 → 时间尺度不对称",
    }

    return results


def main():
    parser = argparse.ArgumentParser(description="Stylized Facts Analysis (Cont 2001)")
    parser.add_argument("run_dir", help="实验运行目录路径 (如 runs/20260323_213251_tom2)")
    parser.add_argument("--symbol", default=None, help="仅分析指定标的 (如 CGEI)，默认分析全部")
    parser.add_argument("--interval", type=float, default=600, help="收益率聚合间隔（秒），默认=600（盘中10分钟窗口，约600个观测值/100天）")
    parser.add_argument("--json", action="store_true", help="输出JSON格式")
    args = parser.parse_args()

    trades = load_trades(args.run_dir, args.symbol)
    if not trades:
        print("No trades found.", file=sys.stderr)
        sys.exit(1)

    returns, volumes, timestamps = aggregate_returns(trades, args.interval)
    if len(returns) < 10:
        print(f"Warning: only {len(returns)} return observations. Results may be unreliable.", file=sys.stderr)

    results = compute_all_stylized_facts(returns, volumes, args.interval)

    meta = {
        "run_dir": args.run_dir,
        "symbol": args.symbol or "ALL",
        "interval_seconds": args.interval,
        "total_trades": len(trades),
        "return_observations": len(returns),
    }

    if args.json:
        print(json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'=' * 70}")
        print(f"Stylized Facts Analysis — Rama Cont (2001)")
        print(f"{'=' * 70}")
        print(f"Run: {meta['run_dir']}")
        print(f"Symbol: {meta['symbol']}  |  Interval: {meta['interval_seconds']}s")
        print(f"Trades: {meta['total_trades']:,}  |  Return obs: {meta['return_observations']}")
        print(f"{'=' * 70}\n")

        passed_count = 0
        total_count = 0
        for name, result in results.items():
            total_count += 1
            passed = result.get("passed", False)
            if passed:
                passed_count += 1
            status = "PASS" if passed else "FAIL"
            print(f"[{status}] {name}")
            for k, v in result.items():
                if k in ("passed", "interpretation"):
                    continue
                print(f"       {k}: {v}")
            print(f"       → {result.get('interpretation', '')}")
            print()

        print(f"{'=' * 70}")
        print(f"Summary: {passed_count}/{total_count} stylized facts reproduced")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
