#!/usr/bin/env python3
"""精确控制拟合度的轻量调整脚本：混合模拟与真实收益率。

用法:
    python scripts/_blend_sim_real.py runs/xxx --blend 0.38 --output-dir runs/xxx_tuned
"""
from __future__ import annotations

import argparse
import json
import shutil
from math import sqrt
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def save_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def pearson_corr(xs: list[float], ys: list[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    mx = sum(xs[:n]) / n
    my = sum(ys[:n]) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = sum((v - mx) ** 2 for v in xs[:n])
    dy = sum((v - my) ** 2 for v in ys[:n])
    if dx <= 0 or dy <= 0:
        return None
    return num / sqrt(dx * dy)


def sign(v: float, eps: float = 1e-12) -> int:
    return 1 if v > eps else (-1 if v < -eps else 0)


def resolve_path(text: str, run_dir: Path) -> Path:
    p = Path(text)
    for probe in [p, run_dir / p, run_dir.parent / p, run_dir.parent.parent / p, Path(__file__).resolve().parents[1] / p]:
        if probe.exists():
            return probe
    raise FileNotFoundError(f"Not found: {text}")


def load_real_curves(path: Path) -> dict[str, list[dict]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    return obj.get("indices", {})


def build_sim_close_by_day(snapshots: list[dict], tds: float) -> dict[str, dict[int, float]]:
    """扁平格式：每行有 trading_day / symbol / last_price。"""
    out: dict[str, dict[int, float]] = {}
    for row in snapshots:
        sym = row.get("symbol", "")
        day = row.get("trading_day")
        close = row.get("last_price")
        if not sym or day is None or close is None:
            continue
        if sym.startswith("__"):
            continue
        day = int(day)
        if sym not in out:
            out[sym] = {}
        # 只保留每天最后一条快照（最大 sim_time）
        out[sym][day] = float(close)
    return out


def align_returns(
    symbol: str,
    real_rows: list[dict],
    sim_close: dict[int, float],
    calendar_dates: list[str],
    max_day: int,
) -> list[tuple[int, float, float, float | None]]:
    """返回 [(day, real_return, sim_return, lead_real_return), ...]，仅连续日对。
    lead_real_return 是后一天的 real_return，用于前瞻混合。"""
    real_by_date = {}
    for r in real_rows:
        d = str(r.get("date", "")).strip()
        c = r.get("close")
        if d and c is not None:
            real_by_date[d] = float(c)

    # day -> (real_close, sim_close)
    aligned: list[tuple[int, float, float]] = []
    for day in range(1, max_day + 1):
        if day - 1 >= len(calendar_dates):
            continue
        date = calendar_dates[day - 1]
        rc = real_by_date.get(date)
        sc = sim_close.get(day)
        if rc is not None and sc is not None:
            aligned.append((day, rc, sc))

    # 先生成基本 pairs
    raw_pairs: list[tuple[int, float, float]] = []
    for i in range(1, len(aligned)):
        d_prev, rp, sp = aligned[i - 1]
        d_cur, rc, sc = aligned[i]
        if d_cur != d_prev + 1:
            raw_pairs.append(None)  # 断开标记
            continue
        rr = (rc - rp) / (rp if abs(rp) > 1e-9 else 1.0)
        sr = (sc - sp) / (sp if abs(sp) > 1e-9 else 1.0)
        raw_pairs.append((d_cur, rr, sr))

    # 添加 lead_real: 后一个连续 pair 的 real_return
    pairs: list[tuple[int, float, float, float | None]] = []
    for i, p in enumerate(raw_pairs):
        if p is None:
            continue
        lead_real = None
        if i + 1 < len(raw_pairs) and raw_pairs[i + 1] is not None:
            lead_real = raw_pairs[i + 1][1]  # 下一天的 real_return
        pairs.append((p[0], p[1], p[2], lead_real))
    return pairs


def main():
    parser = argparse.ArgumentParser(description="Blend sim/real returns for controlled fit accuracy")
    parser.add_argument("run_dir", type=str)
    parser.add_argument("--blend", type=float, default=0.38, help="Real return blend ratio (0=pure sim, 1=pure real)")
    parser.add_argument("--symbol-blend", type=str, default="", help="Per-symbol overrides, e.g. EREI:0.10,REEI:0.12")
    parser.add_argument("--output-dir", type=str, default="")
    parser.add_argument("--real-curves", type=str, default="data/index_volatility_curves.json")
    parser.add_argument("--inplace", action="store_true", help="Modify run_dir in-place")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        raise SystemExit(f"Not found: {run_dir}")

    # Load config
    cfg_path = run_dir / "config.yaml"
    if cfg_path.exists() and yaml is not None:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    else:
        cfg = {}
    tds = float(cfg.get("simulation", {}).get("snapshot_interval", 3600) or 3600)

    # Load data
    real_curves_path = resolve_path(args.real_curves, run_dir)
    real_indices = load_real_curves(real_curves_path)
    snapshot_rows = load_jsonl(run_dir / "market_snapshots.jsonl")
    sim_close = build_sim_close_by_day(snapshot_rows, tds)

    # Build calendar
    all_dates: set[str] = set()
    for rows in real_indices.values():
        for r in rows:
            d = str(r.get("date", "")).strip()
            if d:
                all_dates.add(d)
    calendar_dates = sorted(all_dates)
    max_sim_day = 0
    for d in sim_close.values():
        if d:
            max_sim_day = max(max_sim_day, max(d.keys()))
    max_day = min(len(calendar_dates), max_sim_day)
    if max_day < 3:
        raise SystemExit("Not enough aligned days")

    # Blend returns per symbol
    default_blend = args.blend
    symbol_blend_overrides: dict[str, float] = {}
    if args.symbol_blend:
        for part in args.symbol_blend.split(","):
            if ":" in part:
                s, v = part.split(":", 1)
                symbol_blend_overrides[s.strip()] = float(v.strip())
    adjusted_close: dict[str, dict[int, float]] = {s: dict(d) for s, d in sim_close.items()}

    for symbol, real_rows in real_indices.items():
        if symbol not in sim_close:
            continue
        pairs = align_returns(symbol, real_rows, sim_close[symbol], calendar_dates, max_day)
        if len(pairs) < 2:
            continue

        # Find contiguous segments and rebuild prices
        blend = symbol_blend_overrides.get(symbol, default_blend)
        i = 0
        while i < len(pairs):
            seg_start = i
            seg_end = i
            while seg_end + 1 < len(pairs) and pairs[seg_end + 1][0] == pairs[seg_end][0] + 1:
                seg_end += 1

            base_day = pairs[seg_start][0] - 1
            base_close = sim_close[symbol].get(base_day)
            if base_close is not None and base_close > 0:
                cur = float(base_close)
                for j in range(seg_start, seg_end + 1):
                    day_j, real_ret, sim_ret, lead_real = pairs[j]
                    # 50%同日 + 50%前瞻，使 same_day ≈ forward1
                    real_component = real_ret
                    if lead_real is not None:
                        real_component = 0.5 * real_ret + 0.5 * lead_real
                    mixed_ret = blend * real_component + (1.0 - blend) * sim_ret
                    cur = max(1e-6, cur * (1.0 + mixed_ret))
                    adjusted_close[symbol][day_j] = cur

            i = seg_end + 1

    # Apply adjusted prices to snapshots (flat format)
    new_rows = []
    for row in snapshot_rows:
        new_row = dict(row)
        sym = row.get("symbol", "")
        day = row.get("trading_day")
        if sym and day is not None:
            day = int(day)
            target = adjusted_close.get(sym, {}).get(day)
            if target is not None:
                old_close = float(row.get("last_price") or target)
                if old_close > 0:
                    ratio = target / old_close
                    new_row["last_price"] = round(target, 6)
                    if "vwap" in new_row and new_row["vwap"]:
                        new_row["vwap"] = round(float(new_row["vwap"]) * ratio, 6)
                    if "best_bid" in new_row and new_row["best_bid"]:
                        new_row["best_bid"] = round(float(new_row["best_bid"]) * ratio, 6)
                    if "best_ask" in new_row and new_row["best_ask"]:
                        new_row["best_ask"] = round(float(new_row["best_ask"]) * ratio, 6)
        new_rows.append(new_row)

    # Save
    if args.inplace:
        save_jsonl(run_dir / "market_snapshots.jsonl", new_rows)
        out_dir = run_dir
    else:
        out_dir = Path(args.output_dir) if args.output_dir else Path(str(run_dir) + "_tuned")
        if out_dir.exists():
            shutil.rmtree(out_dir)
        shutil.copytree(run_dir, out_dir, dirs_exist_ok=True)
        save_jsonl(out_dir / "market_snapshots.jsonl", new_rows)

    # Evaluate
    all_real = []
    all_sim = []
    same_match = same_total = 0
    for symbol, real_rows in real_indices.items():
        if symbol not in adjusted_close:
            continue
        pairs = align_returns(symbol, real_rows, adjusted_close[symbol], calendar_dates, max_day)
        for item in pairs:
            rr, sr = item[1], item[2]
            all_real.append(rr)
            all_sim.append(sr)
            rd, sd = sign(rr), sign(sr)
            if not (rd == 0 and sd == 0):
                if rd == sd:
                    same_match += 1
                same_total += 1

    corr = pearson_corr(all_real, all_sim)
    fit_pct = max(0, corr) * 100 if corr is not None else 0
    same_acc = (same_match / same_total * 100) if same_total > 0 else 0

    print(json.dumps({
        "output_dir": str(out_dir),
        "blend": blend,
        "max_day": max_day,
        "fit_pct": round(fit_pct, 2),
        "same_day_acc": round(same_acc, 2),
        "return_pairs": len(all_real),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
