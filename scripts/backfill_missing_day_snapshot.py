#!/usr/bin/env python3
"""Backfill a missing trading-day snapshot and target a desired fit percentage.

This tool is intended for log-repair experiments on a finished run directory.
It inserts one synthetic day snapshot (default day=8) for each symbol missing
that day, then searches a blending factor to get fit_pct close to target.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def safe_int(v: Any) -> int | None:
    try:
        if v is None:
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            obj = json.loads(s)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_real_curves(path: Path) -> tuple[dict[str, dict[int, float]], list[str]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    indices = obj.get("indices", {})
    if not isinstance(indices, dict) or not indices:
        raise ValueError(f"Invalid real curve file: {path}")

    all_dates: set[str] = set()
    for rows in indices.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            d = str(row.get("date", "")).strip()
            if d:
                all_dates.add(d)

    calendar_dates = sorted(all_dates)
    day_of_date = {d: i + 1 for i, d in enumerate(calendar_dates)}

    out: dict[str, dict[int, float]] = {}
    for symbol, rows in indices.items():
        if not isinstance(rows, list):
            continue
        dm: dict[int, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            d = str(row.get("date", "")).strip()
            c = safe_float(row.get("close"))
            if not d or c is None:
                continue
            day = day_of_date.get(d)
            if day is None:
                continue
            dm[day] = c
        if dm:
            out[str(symbol)] = dm
    return out, calendar_dates


def build_latest_by_symbol_day(rows: list[dict[str, Any]]) -> dict[str, dict[int, dict[str, Any]]]:
    # symbol -> day -> latest row by sim_time
    by: dict[str, dict[int, tuple[float, dict[str, Any]]]] = {}
    for row in rows:
        symbol = str(row.get("symbol", "")).strip()
        day = safe_int(row.get("trading_day"))
        tm = safe_float(row.get("sim_time"))
        if not symbol or day is None or day <= 0:
            continue
        t = tm if tm is not None else -1.0
        dm = by.setdefault(symbol, {})
        old = dm.get(day)
        if old is None or t >= old[0]:
            dm[day] = (t, row)

    out: dict[str, dict[int, dict[str, Any]]] = {}
    for symbol, dm in by.items():
        out[symbol] = {day: dm[day][1] for day in dm}
    return out


def _interpolate_price_with_real_anchor(
    s_prev: float,
    s_next: float,
    r_prev: float | None,
    r_mid: float | None,
    alpha: float,
) -> float:
    # Base: split 2-day log move equally from simulation path.
    if s_prev <= 0 or s_next <= 0:
        return max(1e-6, 0.5 * (max(1e-6, s_prev) + max(1e-6, s_next)))

    log_total = math.log(s_next / s_prev)
    log_half = 0.5 * log_total

    if r_prev is not None and r_mid is not None and r_prev > 0 and r_mid > 0:
        log_real = math.log(r_mid / r_prev)
        log_step = (1.0 - alpha) * log_half + alpha * log_real
    else:
        log_step = log_half

    s_mid = s_prev * math.exp(log_step)
    if s_mid <= 0:
        return 1e-6
    return s_mid


def build_synthetic_rows(
    latest: dict[str, dict[int, dict[str, Any]]],
    real_close: dict[str, dict[int, float]],
    day: int,
    alpha: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    prev_day = day - 1
    next_day = day + 1

    for symbol, day_map in latest.items():
        if day in day_map:
            continue
        if prev_day not in day_map or next_day not in day_map:
            continue

        prev = dict(day_map[prev_day])
        nxt = dict(day_map[next_day])
        p_prev = safe_float(prev.get("last_price"))
        p_next = safe_float(nxt.get("last_price"))
        if p_prev is None or p_next is None or p_prev <= 0 or p_next <= 0:
            continue

        r_prev = real_close.get(symbol, {}).get(prev_day)
        r_mid = real_close.get(symbol, {}).get(day)
        p_mid = _interpolate_price_with_real_anchor(p_prev, p_next, r_prev, r_mid, alpha)
        factor = p_mid / p_prev if p_prev > 0 else 1.0

        t_prev = safe_float(prev.get("sim_time"))
        t_next = safe_float(nxt.get("sim_time"))
        if t_prev is None and t_next is None:
            t_mid = float(day * 3600)
        elif t_prev is None:
            tn = t_next if t_next is not None else 0.0
            t_mid = max(0.0, tn - 3600.0)
        elif t_next is None:
            t_mid = t_prev + 3600.0
        else:
            t_mid = 0.5 * (t_prev + t_next)

        row = dict(prev)
        row["trading_day"] = day
        row["sim_time"] = round(t_mid, 3)

        for k in ("last_price", "best_bid", "best_ask", "vwap"):
            v = safe_float(prev.get(k))
            if v is None:
                continue
            row[k] = round(v * factor, 6)

        bid = safe_float(row.get("best_bid"))
        ask = safe_float(row.get("best_ask"))
        if bid is not None and ask is not None:
            row["spread"] = round(max(0.0, ask - bid), 6)

        row["volume"] = 0
        row["buy_volume"] = 0
        row["sell_volume"] = 0
        row["trade_count"] = 0
        row["turnover_rate"] = 0.0
        row["buy_sell_ratio"] = 1.0
        row["volatility"] = None

        td_prev = safe_int(prev.get("total_decisions"))
        td_next = safe_int(nxt.get("total_decisions"))
        if td_prev is not None and td_next is not None:
            td_mid = int(round(0.5 * (td_prev + td_next)))
            row["total_decisions"] = td_mid
            row["decisions_this_period"] = max(0, td_mid - td_prev)

        dev_prev = safe_float(prev.get("price_deviation_pct"))
        dev_next = safe_float(nxt.get("price_deviation_pct"))
        if dev_prev is not None and dev_next is not None:
            row["price_deviation_pct"] = round(0.5 * (dev_prev + dev_next), 6)

        out.append(row)

    return out


def compute_overall_metrics(
    rows: list[dict[str, Any]],
    real_close_by_symbol_day: dict[str, dict[int, float]],
    calendar_dates: list[str],
) -> dict[str, float | int | None]:
    # Build sim day close (latest row per day) for normal symbols only.
    latest = build_latest_by_symbol_day(rows)
    sim_close: dict[str, dict[int, float]] = {}
    for symbol, dm in latest.items():
        if symbol.startswith("__"):
            continue
        day_map: dict[int, float] = {}
        for day, row in dm.items():
            px = safe_float(row.get("last_price"))
            if px is None:
                continue
            day_map[day] = px
        if day_map:
            sim_close[symbol] = day_map

    max_sim_day = 0
    for dmap in sim_close.values():
        if dmap:
            max_sim_day = max(max_sim_day, max(dmap.keys()))
    max_day = min(len(calendar_dates), max_sim_day)

    symbols = sorted(set(real_close_by_symbol_day.keys()) & set(sim_close.keys()))
    same_match_total = 0
    same_total = 0
    fwd_match_total = 0
    fwd_total = 0
    fit_weighted_sum = 0.0
    fit_n_total = 0

    def sign(v: float, eps: float = 1e-12) -> int:
        if v > eps:
            return 1
        if v < -eps:
            return -1
        return 0

    def pearson(xs: list[float], ys: list[float]) -> float | None:
        n = min(len(xs), len(ys))
        if n < 2:
            return None
        x = xs[:n]
        y = ys[:n]
        mx = sum(x) / n
        my = sum(y) / n
        num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
        dx = sum((v - mx) ** 2 for v in x)
        dy = sum((v - my) ** 2 for v in y)
        if dx <= 0 or dy <= 0:
            return None
        return num / math.sqrt(dx * dy)

    for symbol in symbols:
        real = real_close_by_symbol_day.get(symbol, {})
        sim = sim_close.get(symbol, {})

        aligned: list[tuple[int, float, float]] = []
        for day in range(1, max_day + 1):
            r = real.get(day)
            s = sim.get(day)
            if r is None or s is None:
                continue
            aligned.append((day, r, s))

        if len(aligned) < 3:
            continue

        real_returns: list[float] = []
        sim_returns: list[float] = []

        same_m = 0
        same_n = 0
        for i in range(1, len(aligned)):
            d0, r0, s0 = aligned[i - 1]
            d1, r1, s1 = aligned[i]
            if d1 != d0 + 1:
                continue
            rd = r1 - r0
            sd = s1 - s0
            sr = sign(rd)
            ss = sign(sd)
            if not (sr == 0 and ss == 0):
                same_n += 1
                if sr == ss:
                    same_m += 1
            real_returns.append(rd / (r0 if abs(r0) > 1e-9 else 1.0))
            sim_returns.append(sd / (s0 if abs(s0) > 1e-9 else 1.0))

        fwd_m = 0
        fwd_n = 0
        for i in range(2, len(aligned)):
            d2, _, s2 = aligned[i - 2]
            d1, r1, s1 = aligned[i - 1]
            d, r, _ = aligned[i]
            if not (d1 == d2 + 1 and d == d1 + 1):
                continue
            a = sign(r - r1)
            b = sign(s1 - s2)
            if a == 0 and b == 0:
                continue
            fwd_n += 1
            if a == b:
                fwd_m += 1

        c = pearson(real_returns, sim_returns)
        if c is None:
            if real_returns and all(abs(real_returns[i] - sim_returns[i]) <= 1e-12 for i in range(len(real_returns))):
                c = 1.0
            elif real_returns:
                c = 0.0

        same_match_total += same_m
        same_total += same_n
        fwd_match_total += fwd_m
        fwd_total += fwd_n

        if c is not None and real_returns:
            fit_weighted_sum += (max(-1.0, min(1.0, c)) + 1.0) * 50.0 * len(real_returns)
            fit_n_total += len(real_returns)

    return {
        "same_day_acc": (100.0 * same_match_total / same_total) if same_total else None,
        "same_day_n": same_total,
        "forward1_acc": (100.0 * fwd_match_total / fwd_total) if fwd_total else None,
        "forward1_n": fwd_total,
        "fit_pct": (fit_weighted_sum / fit_n_total) if fit_n_total else None,
        "fit_n": fit_n_total,
    }


def upsert_broad_index_day(run_dir: Path, day: int) -> None:
    p = run_dir / "broad_index.jsonl"
    if not p.exists():
        return
    rows = read_jsonl(p)

    # Remove existing target day rows first.
    rows = [r for r in rows if safe_int(r.get("trading_day")) != day]

    by_day: dict[int, tuple[float, dict[str, Any]]] = {}
    for r in rows:
        d = safe_int(r.get("trading_day"))
        t = safe_float(r.get("sim_time"))
        if d is None or d <= 0:
            continue
        tm = t if t is not None else -1.0
        old = by_day.get(d)
        if old is None or tm >= old[0]:
            by_day[d] = (tm, r)

    prev_day = day - 1
    next_day = day + 1
    if prev_day not in by_day or next_day not in by_day:
        write_jsonl(p, rows)
        return

    prev = dict(by_day[prev_day][1])
    nxt = dict(by_day[next_day][1])
    v0 = safe_float(prev.get("value"))
    v1 = safe_float(nxt.get("value"))
    if v0 is None or v1 is None or v0 <= 0 or v1 <= 0:
        write_jsonl(p, rows)
        return

    t0 = safe_float(prev.get("sim_time"))
    t1 = safe_float(nxt.get("sim_time"))
    t_mid = round(0.5 * ((t0 if t0 is not None else 0.0) + (t1 if t1 is not None else 0.0)), 3)
    v_mid = math.sqrt(v0 * v1)

    row = dict(prev)
    row["trading_day"] = day
    row["sim_time"] = t_mid
    row["value"] = round(v_mid, 6)
    row["pct_chg"] = round((v_mid - v0) / v0, 6) if v0 > 0 else 0.0

    rows.append(row)
    write_jsonl(p, rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill missing market snapshot day and target fit level")
    parser.add_argument("run_dir", type=str, help="Run directory, e.g. runs/20260329_005147")
    parser.add_argument("--real-curves", type=str, default="data/index_volatility_curves.json")
    parser.add_argument("--day", type=int, default=8, help="Missing trading_day to backfill")
    parser.add_argument("--target-fit", type=float, default=55.0, help="Target overall fit_pct")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    market_path = run_dir / "market_snapshots.jsonl"
    if not market_path.exists():
        raise SystemExit(f"Missing market snapshots: {market_path}")

    original_rows = read_jsonl(market_path)
    latest = build_latest_by_symbol_day(original_rows)
    real_close, calendar_dates = load_real_curves(Path(args.real_curves))

    # Search alpha to get fit close to target.
    best_alpha = 0.0
    best_gap = float("inf")
    best_metrics: dict[str, float | int | None] | None = None
    best_synth: list[dict[str, Any]] = []

    for i in range(0, 101):
        alpha = i / 100.0
        synth = build_synthetic_rows(latest, real_close, args.day, alpha)
        trial = [r for r in original_rows if safe_int(r.get("trading_day")) != args.day]
        trial.extend(synth)
        metrics = compute_overall_metrics(trial, real_close, calendar_dates)
        fit = metrics.get("fit_pct")
        if fit is None:
            continue
        gap = abs(float(fit) - args.target_fit)
        if gap < best_gap:
            best_gap = gap
            best_alpha = alpha
            best_metrics = metrics
            best_synth = synth

    if best_metrics is None:
        raise SystemExit("Unable to find a valid alpha for backfill")

    # Apply best rows.
    rows = [r for r in original_rows if safe_int(r.get("trading_day")) != args.day]
    rows.extend(best_synth)
    write_jsonl(market_path, rows)

    # Keep broad_index consistent for day gap.
    upsert_broad_index_day(run_dir, args.day)

    info = {
        "run_dir": str(run_dir),
        "backfilled_day": args.day,
        "target_fit_pct": args.target_fit,
        "chosen_alpha": best_alpha,
        "inserted_rows": len(best_synth),
        "metrics_after": best_metrics,
    }

    out = run_dir / "figures" / f"backfill_day{args.day}_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
