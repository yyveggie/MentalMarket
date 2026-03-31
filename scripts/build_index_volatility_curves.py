#!/usr/bin/env python3
"""根据成分股权重与收盘价生成指数波动曲线（JSON）。"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path


PAIR_RE = re.compile(r"([A-Z]{2}\d{6})\s*,\s*权重\s*([0-9.]+)%", re.IGNORECASE)


def norm_code(code: str) -> str:
    return code[:2].lower() + code[2:]


def load_index_weights(profile_csv: Path) -> dict[str, dict[str, float]]:
    index_weights: dict[str, dict[str, float]] = {}
    with profile_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            idx = (row.get("stock_id") or "").strip()
            desc = row.get("description") or ""
            weights: dict[str, float] = {}
            for m in PAIR_RE.finditer(desc):
                code = norm_code(m.group(1).upper())
                weight = float(m.group(2))
                weights[code] = weight
            if idx and weights:
                index_weights[idx] = weights
    return index_weights


def load_close_series(quotes_dir: Path, code: str) -> dict[str, float]:
    p = quotes_dir / f"{code}.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        d = item.get("date")
        c = item.get("close")
        if not d:
            continue
        try:
            out[str(d)] = float(c)
        except (TypeError, ValueError):
            continue
    return out


def build_curves(index_weights: dict[str, dict[str, float]], quotes_dir: Path) -> dict[str, list[dict]]:
    all_stock_series: dict[str, dict[str, float]] = {}
    for weights in index_weights.values():
        for code in weights.keys():
            if code not in all_stock_series:
                all_stock_series[code] = load_close_series(quotes_dir, code)

    curves: dict[str, list[dict]] = {}
    for idx, weights in index_weights.items():
        date_to_pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)

        for code, w in weights.items():
            series = all_stock_series.get(code, {})
            for d, close in series.items():
                date_to_pairs[d].append((close, w))

        rows: list[dict] = []
        prev_close: float | None = None
        for d in sorted(date_to_pairs.keys()):
            pairs = date_to_pairs[d]
            sum_w = sum(w for _, w in pairs)
            if sum_w <= 0:
                continue
            index_close = sum(close * w for close, w in pairs) / sum_w
            ret = None if prev_close is None or prev_close == 0 else (index_close - prev_close) / prev_close
            rows.append(
                {
                    "date": d,
                    "close": round(index_close, 6),
                    "volatility": None if ret is None else round(ret, 8),
                    "component_count_used": len(pairs),
                    "component_weight_sum_used": round(sum_w, 4),
                }
            )
            prev_close = index_close

        curves[idx] = rows

    return curves


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    profile_csv = root / "data" / "stock_profile.csv"
    quotes_dir = root / "data" / "mongodb_quotes_by_stock"
    output_path = root / "data" / "index_volatility_curves.json"

    index_weights = load_index_weights(profile_csv)
    curves = build_curves(index_weights, quotes_dir)

    payload = {
        "method": "weighted_index_close_from_constituents",
        "volatility_definition": "(close_t-close_t-1)/close_t-1",
        "source": {
            "profile_csv": str(profile_csv.relative_to(root)),
            "quotes_dir": str(quotes_dir.relative_to(root)),
        },
        "indices": curves,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[done] indices={len(curves)}")
    for idx in sorted(curves.keys()):
        print(f"[done] {idx}: {len(curves[idx])} points")
    print(f"[done] output={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
