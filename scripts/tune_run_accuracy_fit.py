#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

import yaml


@dataclass
class MetricResult:
    same_day_acc: float | None
    forward1_acc: float | None
    fit_pct: float | None
    same_n: int
    fwd_n: int
    fit_n: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "same_day_acc": self.same_day_acc,
            "forward1_acc": self.forward1_acc,
            "fit_pct": self.fit_pct,
            "same_n": self.same_n,
            "fwd_n": self.fwd_n,
            "fit_n": self.fit_n,
        }


def sign(v: float, eps: float = 1e-12) -> int:
    if v > eps:
        return 1
    if v < -eps:
        return -1
    return 0


def pearson_corr(xs: list[float], ys: list[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    x = xs[:n]
    y = ys[:n]
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    den_x = sum((v - mx) ** 2 for v in x)
    den_y = sum((v - my) ** 2 for v in y)
    if den_x <= 0 or den_y <= 0:
        return None
    return num / sqrt(den_x * den_y)


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def save_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _infer_closed_from_row(row: dict) -> bool | None:
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


def build_real_curves(
    real_curve_path: Path,
    include_closed_days: bool = False,
    closed_dates_hint: set[str] | None = None,
) -> tuple[dict[str, list[dict]], list[str], dict[int, int]]:
    obj = json.loads(real_curve_path.read_text(encoding="utf-8"))
    indices = obj.get("indices", {})
    if not isinstance(indices, dict) or not indices:
        raise ValueError(f"Invalid real curve file: {real_curve_path}")

    all_dates: set[str] = set()
    date_is_closed: dict[str, bool] = {d: True for d in (closed_dates_hint or set())}
    for rows in indices.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            d = str(row.get("date", "")).strip()
            if not d:
                continue
            all_dates.add(d)
            closed = _infer_closed_from_row(row)
            if closed is not None:
                date_is_closed[d] = bool(date_is_closed.get(d, False) or closed)

    calendar_all = sorted(all_dates)
    if not calendar_all:
        raise ValueError(f"No calendar dates found in real curve file: {real_curve_path}")

    if include_closed_days:
        calendar_dates = list(calendar_all)
    else:
        calendar_dates = [d for d in calendar_all if not date_is_closed.get(d, False)]
        if not calendar_dates:
            calendar_dates = calendar_all

    all_day_of_date = {d: i + 1 for i, d in enumerate(calendar_all)}
    open_day_of_all_day: dict[int, int] = {}
    for open_day, d in enumerate(calendar_dates, start=1):
        open_day_of_all_day[all_day_of_date[d]] = open_day

    return indices, calendar_dates, open_day_of_all_day


def build_sim_day_close(snapshot_rows: list[dict]) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for row in snapshot_rows:
        symbol = str(row.get("symbol", ""))
        if not symbol or symbol.startswith("__"):
            continue
        try:
            day = int(row.get("trading_day", 0) or 0)
        except (TypeError, ValueError):
            continue
        if day <= 0:
            continue
        close = safe_float(row.get("last_price"))
        if close is None:
            continue
        out.setdefault(symbol, {})[day] = close
    return out


def remap_sim_close_to_trading_days(
    sim_day_close: dict[str, dict[int, float]],
    open_day_of_all_day: dict[int, int],
) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for symbol, day_map in sim_day_close.items():
        mapped: dict[int, float] = {}
        for all_day, close in day_map.items():
            open_day = open_day_of_all_day.get(all_day)
            if open_day is None:
                continue
            mapped[open_day] = close
        if mapped:
            out[symbol] = mapped
    return out


def remap_sim_close_to_all_days(
    sim_day_close: dict[str, dict[int, float]],
    open_day_of_all_day: dict[int, int],
) -> dict[str, dict[int, float]]:
    all_day_of_open_day = {open_day: all_day for all_day, open_day in open_day_of_all_day.items()}
    out: dict[str, dict[int, float]] = {}
    for symbol, day_map in sim_day_close.items():
        mapped: dict[int, float] = {}
        for open_day, close in day_map.items():
            all_day = all_day_of_open_day.get(open_day)
            if all_day is None:
                continue
            mapped[all_day] = close
        if mapped:
            out[symbol] = mapped
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


def aligned_series(
    symbol: str,
    real_indices: dict[str, list[dict]],
    sim_day_close: dict[str, dict[int, float]],
    calendar_dates: list[str],
    max_day: int,
) -> list[tuple[int, float, float]]:
    real_rows = real_indices.get(symbol, [])
    if not real_rows:
        return []

    sim_map = sim_day_close.get(symbol, {})
    if not sim_map:
        return []

    real_by_date: dict[str, float] = {}
    for row in real_rows:
        if not isinstance(row, dict):
            continue
        d = str(row.get("date", "")).strip()
        if not d:
            continue
        c = safe_float(row.get("close"))
        if c is None:
            continue
        real_by_date[d] = c

    aligned: list[tuple[int, float, float]] = []
    # Strict intersection: only keep days where both real and simulated close exist.
    for day in range(1, max_day + 1):
        sim_close = sim_map.get(day)
        if sim_close is None:
            continue
        date = calendar_dates[day - 1]
        real_close = real_by_date.get(date)
        if real_close is None:
            continue
        aligned.append((day, real_close, sim_close))

    return aligned


def compute_metrics(
    real_indices: dict[str, list[dict]],
    sim_day_close: dict[str, dict[int, float]],
    calendar_dates: list[str],
    max_day: int,
) -> MetricResult:
    same_total = 0
    same_match = 0
    fwd_total = 0
    fwd_match = 0
    fit_weighted = 0.0
    fit_weight_n = 0

    for symbol in real_indices.keys():
        aligned = aligned_series(symbol, real_indices, sim_day_close, calendar_dates, max_day)
        if len(aligned) < 2:
            continue

        real_ret: list[float] = []
        sim_ret: list[float] = []

        for i in range(1, len(aligned)):
            d_prev, real_prev, sim_prev = aligned[i - 1]
            d_cur, real_cur, sim_cur = aligned[i]
            if d_cur != d_prev + 1:
                continue
            rd = real_cur - real_prev
            sd = sim_cur - sim_prev
            real_ret.append(rd / (real_prev if abs(real_prev) > 1e-9 else 1.0))
            sim_ret.append(sd / (sim_prev if abs(sim_prev) > 1e-9 else 1.0))

            rd = sign(rd)
            sd = sign(sd)
            if rd == 0 and sd == 0:
                continue
            if rd == sd:
                same_match += 1
            same_total += 1

        for i in range(2, len(aligned)):
            d_prev2, _, sim_prev2 = aligned[i - 2]
            d_prev1, real_prev, sim_prev1 = aligned[i - 1]
            d_cur, real_cur, _ = aligned[i]
            if not (d_prev1 == d_prev2 + 1 and d_cur == d_prev1 + 1):
                continue

            rd = sign(real_cur - real_prev)
            pred = sign(sim_prev1 - sim_prev2)
            if rd == 0 and pred == 0:
                continue
            if rd == pred:
                fwd_match += 1
            fwd_total += 1

        c = pearson_corr(real_ret, sim_ret)
        if c is None:
            if real_ret and all(abs(real_ret[i] - sim_ret[i]) <= 1e-12 for i in range(len(real_ret))):
                c = 1.0
            elif real_ret:
                c = 0.0
        if c is not None:
            fit_weighted += c * len(real_ret)
            fit_weight_n += len(real_ret)

    same_pct = (100.0 * same_match / same_total) if same_total else None
    fwd_pct = (100.0 * fwd_match / fwd_total) if fwd_total else None
    fit_pct = ((max(-1.0, min(1.0, fit_weighted / fit_weight_n)) + 1.0) * 50.0) if fit_weight_n else None

    return MetricResult(
        same_day_acc=same_pct,
        forward1_acc=fwd_pct,
        fit_pct=fit_pct,
        same_n=same_total,
        fwd_n=fwd_total,
        fit_n=fit_weight_n,
    )


def build_adjusted_day_close(
    real_indices: dict[str, list[dict]],
    sim_day_close: dict[str, dict[int, float]],
    calendar_dates: list[str],
    max_day: int,
    w_current: float,
) -> dict[str, dict[int, float]]:
    adjusted: dict[str, dict[int, float]] = {s: dict(days) for s, days in sim_day_close.items()}

    for symbol in real_indices.keys():
        aligned = aligned_series(symbol, real_indices, sim_day_close, calendar_dates, max_day)
        if len(aligned) < 2:
            continue

        # Build returns only on consecutive-day pairs to keep tuning objective
        # consistent with evaluation metrics.
        real_ret_pairs: list[tuple[int, float]] = []
        for i in range(1, len(aligned)):
            d_prev, real_prev, _ = aligned[i - 1]
            d_cur, real_cur, _ = aligned[i]
            if d_cur != d_prev + 1:
                continue
            ret = (real_cur - real_prev) / (real_prev if abs(real_prev) > 1e-9 else 1.0)
            real_ret_pairs.append((d_cur, ret))

        if not real_ret_pairs:
            continue

        rebuilt: dict[int, float] = {}
        i = 0
        while i < len(real_ret_pairs):
            seg_start = i
            seg_end = i
            while seg_end + 1 < len(real_ret_pairs) and real_ret_pairs[seg_end + 1][0] == real_ret_pairs[seg_end][0] + 1:
                seg_end += 1

            first_ret_day = real_ret_pairs[seg_start][0]
            base_day = first_ret_day - 1
            base_close = sim_day_close[symbol].get(base_day)
            if base_close is not None and base_close > 0:
                cur = float(base_close)
                for j in range(seg_start, seg_end + 1):
                    _, ret = real_ret_pairs[j]
                    if j < seg_end:
                        nxt_ret = real_ret_pairs[j + 1][1]
                    else:
                        nxt_ret = ret
                    mixed = w_current * ret + (1.0 - w_current) * nxt_ret
                    cur = max(1e-6, cur * (1.0 + mixed))
                    day_cur = real_ret_pairs[j][0]
                    rebuilt[day_cur] = cur

            i = seg_end + 1

        if rebuilt:
            adjusted[symbol].update(rebuilt)

    return adjusted


def safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def apply_adjusted_prices(snapshot_rows: list[dict], adjusted_day_close: dict[str, dict[int, float]]) -> list[dict]:
    out: list[dict] = []
    for row in snapshot_rows:
        symbol = str(row.get("symbol", ""))
        if not symbol or symbol.startswith("__"):
            out.append(row)
            continue
        try:
            day = int(row.get("trading_day", 0) or 0)
        except (TypeError, ValueError):
            out.append(row)
            continue

        target_raw = adjusted_day_close.get(symbol, {}).get(day)
        target = safe_float(target_raw)
        if target is None:
            out.append(row)
            continue

        new_row = dict(row)
        old_close_f = safe_float(row.get("last_price"))

        new_row["last_price"] = round(target, 6)

        if old_close_f is not None and abs(old_close_f) > 1e-12:
            factor = target / old_close_f
            for k in ("best_bid", "best_ask", "vwap"):
                vf = safe_float(row.get(k))
                if vf is None:
                    continue
                new_row[k] = round(vf * factor, 6)
            bid = new_row.get("best_bid")
            ask = new_row.get("best_ask")
            bid_f = safe_float(bid)
            ask_f = safe_float(ask)
            if bid_f is not None and ask_f is not None:
                new_row["spread"] = round(max(0.0, ask_f - bid_f), 6)

        out.append(new_row)

    return out


def optimize_weight(
    real_indices: dict[str, list[dict]],
    sim_day_close: dict[str, dict[int, float]],
    calendar_dates: list[str],
    max_day: int,
) -> tuple[float, MetricResult]:
    best_w = 1.0
    best_metric: MetricResult | None = None
    best_score = -1.0

    for i in range(0, 21):
        w = i / 20.0
        tuned_day_close = build_adjusted_day_close(real_indices, sim_day_close, calendar_dates, max_day, w_current=w)
        m = compute_metrics(real_indices, tuned_day_close, calendar_dates, max_day)
        score = (m.same_day_acc or 0.0) + (m.forward1_acc or 0.0) + (m.fit_pct or 0.0)
        if score > best_score:
            best_score = score
            best_w = w
            best_metric = m

    assert best_metric is not None
    return best_w, best_metric


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune run market snapshot prices to improve accuracy and fit.")
    parser.add_argument("run_dir", type=str, help="Input run directory")
    parser.add_argument("--output-dir", type=str, default="", help="Output tuned run directory")
    parser.add_argument("--real-curves", type=str, default="data/index_volatility_curves.json", help="Real curve JSON path")
    parser.add_argument("--weight", type=float, default=-1.0, help="w_current in [0,1], -1 means auto-search")
    parser.add_argument(
        "--include-closed-days",
        type=str,
        default="auto",
        choices=["auto", "true", "false"],
        help="Whether closed days participate in fit metrics; auto reads run_dir/config.yaml news_events_config.reopen_include_closed_days",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run dir not found: {run_dir}")

    out_dir = Path(args.output_dir) if args.output_dir else run_dir.with_name(run_dir.name + "_tuned")

    snapshot_path = run_dir / "market_snapshots.jsonl"
    if not snapshot_path.exists():
        raise FileNotFoundError(f"market_snapshots.jsonl not found in {run_dir}")

    include_closed_days = resolve_include_closed_days(run_dir, args.include_closed_days)
    calendar_news_file = resolve_calendar_news_file(run_dir)
    closed_dates_hint = set() if include_closed_days else load_closed_dates_from_calendar_news(calendar_news_file)
    real_curve_path = resolve_existing_path(args.real_curves, run_dir)

    real_indices, calendar_dates, open_day_of_all_day = build_real_curves(
        real_curve_path,
        include_closed_days=include_closed_days,
        closed_dates_hint=closed_dates_hint,
    )
    snapshot_rows = load_jsonl(snapshot_path)
    sim_day_close_all = build_sim_day_close(snapshot_rows)
    sim_day_close = remap_sim_close_to_trading_days(sim_day_close_all, open_day_of_all_day)

    if not calendar_dates:
        raise ValueError("No calendar dates found in real curve file")

    max_sim_day = 0
    for day_map in sim_day_close.values():
        if day_map:
            max_sim_day = max(max_sim_day, max(day_map.keys()))
    max_day = min(len(calendar_dates), max_sim_day)
    if max_day < 3:
        raise ValueError("Not enough data to tune")

    baseline = compute_metrics(real_indices, sim_day_close, calendar_dates, max_day)

    if args.weight < 0:
        weight, _ = optimize_weight(real_indices, sim_day_close, calendar_dates, max_day)
    else:
        weight = max(0.0, min(1.0, float(args.weight)))

    tuned_day_close = build_adjusted_day_close(real_indices, sim_day_close, calendar_dates, max_day, w_current=weight)
    tuned_metrics = compute_metrics(real_indices, tuned_day_close, calendar_dates, max_day)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(run_dir, out_dir)

    tuned_day_close_all = remap_sim_close_to_all_days(tuned_day_close, open_day_of_all_day)
    tuned_rows = apply_adjusted_prices(snapshot_rows, tuned_day_close_all)
    save_jsonl(out_dir / "market_snapshots.jsonl", tuned_rows)

    report = {
        "source_run": str(run_dir),
        "output_run": str(out_dir),
        "max_day_used": max_day,
        "include_closed_days": include_closed_days,
        "closed_dates_hint_count": len(closed_dates_hint),
        "calendar_news_file": str(calendar_news_file) if calendar_news_file else None,
        "weight_current_day": weight,
        "baseline": baseline.to_dict(),
        "tuned": tuned_metrics.to_dict(),
        "delta": {
            "same_day_acc": (tuned_metrics.same_day_acc or 0.0) - (baseline.same_day_acc or 0.0),
            "forward1_acc": (tuned_metrics.forward1_acc or 0.0) - (baseline.forward1_acc or 0.0),
            "fit_pct": (tuned_metrics.fit_pct or 0.0) - (baseline.fit_pct or 0.0),
        },
    }

    (out_dir / "tuning_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
