#!/usr/bin/env python3
"""核验 runs/ 下每个实验目录，Agent 决策时是否都输出 confidence 字段。

检查对象：
  1. decisions.jsonl    → llm_output.confidence  (LLM 原始输出)
  2. sentiment_series.jsonl → confidence          (决策落库后的情绪记录)

用法：
  python scripts/_check_confidence_in_runs.py                # 扫描 runs/ 下所有目录
  python scripts/_check_confidence_in_runs.py <run_dir> ...  # 指定目录
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"


def iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def check_decisions(path: Path) -> dict:
    total = 0
    has_llm_out = 0
    has_conf = 0
    default_05 = 0
    by_tom: dict[int, list[float]] = {0: [], 1: [], 2: []}
    missing_samples: list[dict] = []

    for r in iter_jsonl(path):
        total += 1
        out = r.get("llm_output") or {}
        if isinstance(out, dict) and out:
            has_llm_out += 1
        conf = out.get("confidence") if isinstance(out, dict) else None
        tom = r.get("tom_level")
        if conf is None:
            if len(missing_samples) < 3:
                missing_samples.append({
                    "agent_id": r.get("agent_id"),
                    "tom_level": tom,
                    "llm_output_keys": list(out.keys()) if isinstance(out, dict) else None,
                })
            continue
        try:
            c = float(conf)
        except Exception:
            continue
        has_conf += 1
        if c == 0.5:
            default_05 += 1
        if tom in by_tom:
            by_tom[tom].append(c)

    return {
        "total": total,
        "has_llm_output": has_llm_out,
        "has_confidence": has_conf,
        "default_05": default_05,
        "by_tom": by_tom,
        "missing_samples": missing_samples,
    }


def check_sentiment_series(path: Path) -> dict:
    total = 0
    has_conf = 0
    vals: list[float] = []
    for r in iter_jsonl(path):
        total += 1
        if "confidence" in r and r["confidence"] is not None:
            try:
                vals.append(float(r["confidence"]))
                has_conf += 1
            except Exception:
                pass
    return {
        "total": total,
        "has_confidence": has_conf,
        "values": vals,
    }


def fmt_dist(vals: list[float]) -> str:
    if not vals:
        return "n=0"
    return (
        f"n={len(vals)}  min={min(vals):.2f}  max={max(vals):.2f}  "
        f"mean={statistics.mean(vals):.3f}  stdev={statistics.pstdev(vals):.3f}"
    )


def report(run_dir: Path) -> None:
    print("=" * 90)
    print(f"Run: {run_dir.name}")
    print("=" * 90)

    # decisions.jsonl
    dp = run_dir / "decisions.jsonl"
    if not dp.exists():
        print(f"  [!] decisions.jsonl 不存在，跳过")
    else:
        d = check_decisions(dp)
        total = d["total"]
        hc = d["has_confidence"]
        pct = (hc / total * 100) if total else 0.0
        print(f"[decisions.jsonl]  记录 {total}  含 llm_output {d['has_llm_output']}  含 confidence {hc} ({pct:.2f}%)")
        print(f"  confidence == 0.5 (默认值): {d['default_05']} ({(d['default_05']/total*100 if total else 0):.2f}%)")
        for tom in (0, 1, 2):
            vals = d["by_tom"][tom]
            print(f"  ToM{tom}: {fmt_dist(vals)}")
        if d["missing_samples"]:
            print("  缺失 confidence 样例（前3条）:")
            for s in d["missing_samples"]:
                print(f"    {s}")

    # sentiment_series.jsonl
    sp = run_dir / "sentiment_series.jsonl"
    if not sp.exists():
        print(f"[sentiment_series.jsonl] 不存在，跳过")
    else:
        s = check_sentiment_series(sp)
        total = s["total"]
        hc = s["has_confidence"]
        pct = (hc / total * 100) if total else 0.0
        print(f"[sentiment_series.jsonl]  记录 {total}  含 confidence {hc} ({pct:.2f}%)")
        print(f"  值分布: {fmt_dist(s['values'])}")
    print()


def main():
    args = sys.argv[1:]
    if args:
        targets = [Path(a) if Path(a).is_absolute() else (ROOT / a) for a in args]
    else:
        if not RUNS_DIR.exists():
            print(f"runs 目录不存在: {RUNS_DIR}")
            sys.exit(1)
        targets = sorted(p for p in RUNS_DIR.iterdir() if p.is_dir())
    for t in targets:
        if not t.exists():
            print(f"[!] 不存在: {t}")
            continue
        report(t)


if __name__ == "__main__":
    main()
