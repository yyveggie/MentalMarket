#!/usr/bin/env python3
"""Kyle lambda metric calculations (Kyle 1985)."""

from __future__ import annotations

from pathlib import Path

from metrics_plot_common import read_jsonl, safe_float, safe_int


def ols_slope(x: list[float], y: list[float]) -> tuple[float | None, float | None, int]:
    n = min(len(x), len(y))
    if n < 15:
        return None, None, n
    xx = x[:n]
    yy = y[:n]
    mx = sum(xx) / n
    my = sum(yy) / n
    vx = sum((v - mx) ** 2 for v in xx)
    if vx <= 1e-15:
        return None, None, n
    cov = sum((xx[i] - mx) * (yy[i] - my) for i in range(n))
    slope = cov / vx

    ss_tot = sum((v - my) ** 2 for v in yy)
    if ss_tot <= 1e-15:
        return slope, 0.0, n
    intercept = my - slope * mx
    ss_res = sum((yy[i] - (intercept + slope * xx[i])) ** 2 for i in range(n))
    r2 = 1.0 - ss_res / ss_tot
    return slope, r2, n


def build_daily_kyle_lambda(run_dir: Path, min_points: int) -> tuple[list[int], list[float], list[float], list[int]]:
    rows = read_jsonl(run_dir / "trades.jsonl")

    by_day_symbol: dict[int, dict[str, list[tuple[float, float, float]]]] = {}

    def signed_qty(row: dict) -> float | None:
        qty = safe_float(row.get("quantity"))
        if qty is None or qty <= 0:
            return None
        aggr = str(row.get("aggressor", "")).strip().lower()
        if aggr == "bid":
            s = 1.0
        elif aggr == "ask":
            s = -1.0
        else:
            return None
        return s * qty

    for row in rows:
        if bool(row.get("is_seed_trade")):
            continue
        day = safe_int(row.get("trading_day"))
        sym = str(row.get("symbol", "")).strip()
        tm = safe_float(row.get("sim_time"))
        px = safe_float(row.get("price"))
        q = signed_qty(row)
        if day is None or day <= 0 or not sym or tm is None or px is None or q is None:
            continue
        by_day_symbol.setdefault(day, {}).setdefault(sym, []).append((tm, px, q))

    out_days: list[int] = []
    out_lambda: list[float] = []
    out_r2: list[float] = []
    out_n: list[int] = []

    for day in sorted(by_day_symbol.keys()):
        sym_data = by_day_symbol[day]
        lambdas: list[float] = []
        r2s: list[float] = []
        ns: list[int] = []

        for obs in sym_data.values():
            obs.sort(key=lambda x: x[0])
            dps: list[float] = []
            qs: list[float] = []
            for i in range(1, len(obs)):
                p_prev = obs[i - 1][1]
                p_cur = obs[i][1]
                q = obs[i][2]
                dps.append(p_cur - p_prev)
                qs.append(q)

            lam, r2, n = ols_slope(qs, dps)
            if lam is None or n < min_points:
                continue
            lambdas.append(lam)
            r2s.append(r2 if r2 is not None else 0.0)
            ns.append(n)

        if not lambdas:
            continue

        w_sum = sum(ns)
        lam_day = sum(lambdas[i] * ns[i] for i in range(len(lambdas))) / w_sum
        r2_day = sum(r2s[i] * ns[i] for i in range(len(r2s))) / w_sum

        out_days.append(day)
        out_lambda.append(lam_day)
        out_r2.append(r2_day)
        out_n.append(w_sum)

    return out_days, out_lambda, out_r2, out_n
