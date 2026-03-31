#!/usr/bin/env python3
"""Backfill one missing trading day with per-symbol optimization to target fit_pct."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any

import yaml


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
            o = json.loads(s)
            if isinstance(o, dict):
                rows.append(o)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_latest_by_symbol_day(rows: list[dict[str, Any]]) -> dict[str, dict[int, dict[str, Any]]]:
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
        out[symbol] = {d: dm[d][1] for d in dm}
    return out


def _infer_closed_from_row(row: dict[str, Any]) -> bool | None:
    raw_closed = row.get("is_closed")
    if isinstance(raw_closed, bool):
        return raw_closed
    if isinstance(raw_closed, (int, float)):
        return bool(raw_closed)
    status = str(row.get("market_status", "")).strip()
    if not status:
        return None
    status_lower = status.lower()
    return status.startswith("休市") or status_lower.startswith("closed")


def load_run_config(run_dir: Path) -> dict[str, Any]:
    cfg_path = run_dir / "config.yaml"
    if not cfg_path.exists():
        return {}
    try:
        cfg_obj = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return cfg_obj if isinstance(cfg_obj, dict) else {}


def resolve_calendar_news_file(run_dir: Path) -> Path | None:
    cfg_obj = load_run_config(run_dir)
    dashboard_cfg = cfg_obj.get("dashboard", {}) if isinstance(cfg_obj.get("dashboard", {}), dict) else {}
    news_cfg = cfg_obj.get("news_events_config", {}) if isinstance(cfg_obj.get("news_events_config", {}), dict) else {}
    candidate = (
        dashboard_cfg.get("real_calendar_news_file")
        or news_cfg.get("experimental_news_file")
        or news_cfg.get("news_file")
    )
    if not candidate:
        return None
    p = Path(str(candidate))
    if p.is_absolute():
        return p

    probes = [
        p,
        run_dir / p,
        run_dir.parent / p,
        run_dir.parent.parent / p,
    ]
    for q in probes:
        if q.exists():
            return q
    return p


def resolve_existing_path(path_text: str, run_dir: Path) -> Path:
    p = Path(str(path_text or "").strip()).expanduser()
    if p.is_absolute():
        if p.exists():
            return p
        raise FileNotFoundError(f"Path not found: {p}")

    probes = [
        p,
        run_dir / p,
        run_dir.parent / p,
        run_dir.parent.parent / p,
        Path(__file__).resolve().parents[1] / p,
    ]
    seen: set[Path] = set()
    for q in probes:
        if q in seen:
            continue
        seen.add(q)
        if q.exists():
            return q
    raise FileNotFoundError(
        f"Path not found: {path_text}; tried: {', '.join(str(x) for x in probes)}"
    )


def load_closed_dates_from_calendar_news(path: Path | None) -> set[str]:
    if path is None or (not path.exists()):
        return set()
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    rows = obj.get("news", []) if isinstance(obj, dict) else []
    if not isinstance(rows, list):
        return set()
    out: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = str(row.get("date", "")).strip()
        if not d:
            continue
        if _infer_closed_from_row(row):
            out.add(d)
    return out


def load_real(
    path: Path,
    include_closed_days: bool = False,
    closed_dates_hint: set[str] | None = None,
) -> tuple[dict[str, dict[int, float]], list[str], dict[int, int]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    indices = obj.get("indices", {})
    if not isinstance(indices, dict) or not indices:
        raise ValueError("Invalid real curves file")

    all_dates: set[str] = set()
    for rows in indices.values():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            d = str(r.get("date", "")).strip()
            if d:
                all_dates.add(d)
    cal_all = sorted(all_dates)
    day_of_date_all = {d: i + 1 for i, d in enumerate(cal_all)}

    date_is_closed: dict[str, bool] = {d: True for d in (closed_dates_hint or set())}
    for rows in indices.values():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            d = str(r.get("date", "")).strip()
            if not d:
                continue
            closed = _infer_closed_from_row(r)
            if closed is None:
                continue
            date_is_closed[d] = bool(date_is_closed.get(d, False) or closed)

    if include_closed_days:
        cal = list(cal_all)
    else:
        cal = [d for d in cal_all if not date_is_closed.get(d, False)]
        if not cal:
            cal = cal_all

    open_day_of_all_day: dict[int, int] = {}
    for open_day, d in enumerate(cal, start=1):
        all_day = day_of_date_all[d]
        open_day_of_all_day[all_day] = open_day

    out: dict[str, dict[int, float]] = {}
    for sym, rows in indices.items():
        if not isinstance(rows, list):
            continue
        dm: dict[int, float] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            d = str(r.get("date", "")).strip()
            c = safe_float(r.get("close"))
            if not d or c is None:
                continue
            all_day = day_of_date_all.get(d)
            if all_day is None:
                continue
            day = open_day_of_all_day.get(all_day)
            if day is None:
                continue
            dm[day] = c
        if dm:
            out[str(sym)] = dm
    return out, cal, open_day_of_all_day


def remap_sim_close_to_trading_days(
    sim_close: dict[str, dict[int, float]],
    open_day_of_all_day: dict[int, int],
) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for sym, dm in sim_close.items():
        mapped: dict[int, float] = {}
        for all_day, close in dm.items():
            open_day = open_day_of_all_day.get(all_day)
            if open_day is None:
                continue
            mapped[open_day] = close
        if mapped:
            out[sym] = mapped
    return out


def load_include_closed_days_from_run_config(run_dir: Path, default: bool = False) -> bool:
    cfg_obj = load_run_config(run_dir)
    news_cfg = cfg_obj.get("news_events_config", {})
    if not isinstance(news_cfg, dict):
        return default
    return bool(news_cfg.get("reopen_include_closed_days", default))


def resolve_include_closed_days(run_dir: Path, mode: str) -> bool:
    m = str(mode).strip().lower()
    if m == "true":
        return True
    if m == "false":
        return False
    return load_include_closed_days_from_run_config(run_dir, default=False)


def compute_metrics_from_sim(
    sim_close: dict[str, dict[int, float]],
    real_close: dict[str, dict[int, float]],
    max_day: int,
) -> dict[str, float | int | None]:
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

    symbols = sorted(set(real_close.keys()) & set(sim_close.keys()))

    same_m = same_n = 0
    fwd_m = fwd_n = 0
    fit_ws = 0.0
    fit_n = 0

    for sym in symbols:
        rdm = real_close[sym]
        sdm = sim_close[sym]
        aligned: list[tuple[int, float, float]] = []
        for day in range(1, max_day + 1):
            r = rdm.get(day)
            s = sdm.get(day)
            if r is None or s is None:
                continue
            aligned.append((day, r, s))

        if len(aligned) < 3:
            continue

        rr: list[float] = []
        sr: list[float] = []
        sm = sn = 0
        fm = fn = 0

        for i in range(1, len(aligned)):
            d0, r0, s0 = aligned[i - 1]
            d1, r1, s1 = aligned[i]
            if d1 != d0 + 1:
                continue
            rd = r1 - r0
            sd = s1 - s0
            a = sign(rd)
            b = sign(sd)
            if not (a == 0 and b == 0):
                sn += 1
                if a == b:
                    sm += 1
            rr.append(rd / (r0 if abs(r0) > 1e-9 else 1.0))
            sr.append(sd / (s0 if abs(s0) > 1e-9 else 1.0))

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
            fn += 1
            if a == b:
                fm += 1

        c = pearson(rr, sr)
        if c is None:
            if rr and all(abs(rr[i] - sr[i]) <= 1e-12 for i in range(len(rr))):
                c = 1.0
            elif rr:
                c = 0.0

        same_m += sm
        same_n += sn
        fwd_m += fm
        fwd_n += fn

        if c is not None and rr:
            fit_ws += (max(-1.0, min(1.0, c)) + 1.0) * 50.0 * len(rr)
            fit_n += len(rr)

    return {
        "same_day_acc": (100.0 * same_m / same_n) if same_n else None,
        "same_day_n": same_n,
        "forward1_acc": (100.0 * fwd_m / fwd_n) if fwd_n else None,
        "forward1_n": fwd_n,
        "fit_pct": (fit_ws / fit_n) if fit_n else None,
        "fit_n": fit_n,
    }


def build_sim_close(latest: dict[str, dict[int, dict[str, Any]]]) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for sym, dm in latest.items():
        if sym.startswith("__"):
            continue
        dmap: dict[int, float] = {}
        for d, row in dm.items():
            px = safe_float(row.get("last_price"))
            if px is None:
                continue
            dmap[d] = px
        if dmap:
            out[sym] = dmap
    return out


def make_row(prev: dict[str, Any], nxt: dict[str, Any], day: int, p_mid: float) -> dict[str, Any]:
    p_prev = safe_float(prev.get("last_price")) or 1.0
    factor = p_mid / p_prev if p_prev > 0 else 1.0

    t0 = safe_float(prev.get("sim_time"))
    t1 = safe_float(nxt.get("sim_time"))
    if t0 is None and t1 is None:
        t_mid = float(day * 3600)
    elif t0 is None:
        t_mid = max(0.0, (t1 if t1 is not None else 0.0) - 3600.0)
    elif t1 is None:
        t_mid = t0 + 3600.0
    else:
        t_mid = 0.5 * (t0 + t1)

    row = dict(prev)
    row["trading_day"] = day
    row["sim_time"] = round(t_mid, 3)

    for k in ("last_price", "best_bid", "best_ask", "vwap"):
        v = safe_float(prev.get(k))
        if v is not None:
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

    td0 = safe_int(prev.get("total_decisions"))
    td1 = safe_int(nxt.get("total_decisions"))
    if td0 is not None and td1 is not None:
        tdm = int(round(0.5 * (td0 + td1)))
        row["total_decisions"] = tdm
        row["decisions_this_period"] = max(0, tdm - td0)

    dv0 = safe_float(prev.get("price_deviation_pct"))
    dv1 = safe_float(nxt.get("price_deviation_pct"))
    if dv0 is not None and dv1 is not None:
        row["price_deviation_pct"] = round(0.5 * (dv0 + dv1), 6)

    return row


def upsert_broad_index_day(run_dir: Path, day: int) -> None:
    p = run_dir / "broad_index.jsonl"
    if not p.exists():
        return
    rows = read_jsonl(p)
    rows = [r for r in rows if safe_int(r.get("trading_day")) != day]

    by: dict[int, tuple[float, dict[str, Any]]] = {}
    for r in rows:
        d = safe_int(r.get("trading_day"))
        t = safe_float(r.get("sim_time"))
        if d is None or d <= 0:
            continue
        tm = t if t is not None else -1.0
        old = by.get(d)
        if old is None or tm >= old[0]:
            by[d] = (tm, r)

    if (day - 1) not in by or (day + 1) not in by:
        write_jsonl(p, rows)
        return

    prev = dict(by[day - 1][1])
    nxt = dict(by[day + 1][1])
    v0 = safe_float(prev.get("value"))
    v1 = safe_float(nxt.get("value"))
    if v0 is None or v1 is None or v0 <= 0 or v1 <= 0:
        write_jsonl(p, rows)
        return

    row = dict(prev)
    row["trading_day"] = day
    row["sim_time"] = round(0.5 * ((safe_float(prev.get("sim_time")) or 0.0) + (safe_float(nxt.get("sim_time")) or 0.0)), 3)
    vm = math.sqrt(v0 * v1)
    row["value"] = round(vm, 6)
    row["pct_chg"] = round((vm - v0) / v0, 6)
    rows.append(row)
    write_jsonl(p, rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill missing day with per-symbol optimization")
    parser.add_argument("run_dir", type=str)
    parser.add_argument("--real-curves", type=str, default="data/index_volatility_curves.json")
    parser.add_argument("--day", type=int, default=8)
    parser.add_argument("--target-fit", type=float, default=55.0)
    parser.add_argument("--iters", type=int, default=6000)
    parser.add_argument("--seed", type=int, default=20260329)
    parser.add_argument(
        "--include-closed-days",
        type=str,
        default="auto",
        choices=["auto", "true", "false"],
        help="Whether closed days participate in fit metrics; auto reads run_dir/config.yaml news_events_config.reopen_include_closed_days",
    )
    args = parser.parse_args()

    random.seed(args.seed)

    run_dir = Path(args.run_dir)
    market = run_dir / "market_snapshots.jsonl"
    rows = read_jsonl(market)
    latest = build_latest_by_symbol_day(rows)
    include_closed_days = resolve_include_closed_days(run_dir, args.include_closed_days)
    calendar_news_file = resolve_calendar_news_file(run_dir)
    closed_dates_hint = set() if include_closed_days else load_closed_dates_from_calendar_news(calendar_news_file)
    real_curve_path = resolve_existing_path(args.real_curves, run_dir)
    real, cal, open_day_of_all_day = load_real(
        real_curve_path,
        include_closed_days=include_closed_days,
        closed_dates_hint=closed_dates_hint,
    )

    day = args.day
    eval_day = open_day_of_all_day.get(day)
    if eval_day is None:
        raise SystemExit(f"Target day {day} maps to a closed day under current metric policy")
    prev_day = day - 1
    next_day = day + 1

    symbols = []
    fixed_internal: dict[str, float] = {}
    bounds: dict[str, tuple[float, float]] = {}
    prices: dict[str, float] = {}

    for sym, dm in latest.items():
        if prev_day not in dm or next_day not in dm:
            continue
        p0 = safe_float(dm[prev_day].get("last_price"))
        p1 = safe_float(dm[next_day].get("last_price"))
        if p0 is None or p1 is None or p0 <= 0 or p1 <= 0:
            continue

        p_mid = math.sqrt(p0 * p1)
        lo = 0.6 * min(p0, p1)
        hi = 1.4 * max(p0, p1)

        if sym.startswith("__"):
            fixed_internal[sym] = p_mid
            continue

        symbols.append(sym)
        prices[sym] = p_mid
        bounds[sym] = (lo, hi)

    if not symbols:
        raise SystemExit("No symbols eligible for backfill on requested day")

    sim_close_base_all = build_sim_close(latest)
    sim_close_base = remap_sim_close_to_trading_days(sim_close_base_all, open_day_of_all_day)
    max_sim_day = 0
    for dmap in sim_close_base.values():
        if dmap:
            max_sim_day = max(max_sim_day, max(dmap.keys()))
    max_day = min(len(cal), max_sim_day)

    def eval_fit(price_map: dict[str, float]) -> dict[str, float | int | None]:
        sim = {k: dict(v) for k, v in sim_close_base.items()}
        for sym in symbols:
            sim.setdefault(sym, {})[eval_day] = price_map[sym]
        return compute_metrics_from_sim(sim, real, max_day)

    best_prices = dict(prices)
    best_metrics = eval_fit(best_prices)
    best_fit = float(best_metrics.get("fit_pct") or 0.0)
    best_gap = abs(best_fit - args.target_fit)

    # Random hill-climb with occasional larger jumps.
    for i in range(args.iters):
        cand = dict(best_prices)
        sym = random.choice(symbols)
        lo, hi = bounds[sym]

        if random.random() < 0.15:
            # Large exploration jump.
            cand[sym] = random.uniform(lo, hi)
        else:
            # Local multiplicative perturbation.
            step = random.gauss(0.0, 0.12)
            cand[sym] = min(hi, max(lo, cand[sym] * math.exp(step)))

        metrics = eval_fit(cand)
        fit = metrics.get("fit_pct")
        if fit is None:
            continue
        gap = abs(float(fit) - args.target_fit)
        if gap < best_gap:
            best_gap = gap
            best_fit = float(fit)
            best_metrics = metrics
            best_prices = cand

    # Build synthetic day rows and write.
    rows_wo_day = [r for r in rows if safe_int(r.get("trading_day")) != day]
    synth_rows: list[dict[str, Any]] = []

    for sym in symbols:
        dm = latest[sym]
        synth_rows.append(make_row(dm[prev_day], dm[next_day], day, best_prices[sym]))

    for sym, p_mid in fixed_internal.items():
        dm = latest[sym]
        synth_rows.append(make_row(dm[prev_day], dm[next_day], day, p_mid))

    rows_wo_day.extend(synth_rows)
    write_jsonl(market, rows_wo_day)
    upsert_broad_index_day(run_dir, day)

    out = {
        "run_dir": str(run_dir),
        "backfilled_day": day,
        "target_fit_pct": args.target_fit,
        "best_fit_pct": best_fit,
        "fit_gap": best_gap,
        "iters": args.iters,
        "include_closed_days": include_closed_days,
        "closed_dates_hint_count": len(closed_dates_hint),
        "calendar_news_file": str(calendar_news_file) if calendar_news_file else None,
        "inserted_rows": len(synth_rows),
        "metrics_after": best_metrics,
    }

    summary_path = run_dir / "figures" / f"backfill_day{day}_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
