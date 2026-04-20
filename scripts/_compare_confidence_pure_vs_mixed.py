#!/usr/bin/env python3
"""对比纯 ToM（ToM0/ToM1/ToM2）与混合 ToM 实验的市场平均信心。

指标：
  - overall_mean: 全场所有决策的 confidence 均值（从 sentiment_series.jsonl 读取，100% 覆盖）
  - by_tom: 按 tom_level 分层的均值（仅混合实验有意义）
  - 类别标注：根据 config.yaml 的 tom_distribution 判定 pure/mixed

用法：
  python scripts/_compare_confidence_pure_vs_mixed.py           # 自动扫描 runs/
  python scripts/_compare_confidence_pure_vs_mixed.py run1 run2 # 指定目录
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"


def load_tom_distribution(run_dir: Path) -> dict[int, float] | None:
    cfg = run_dir / "config.yaml"
    if not cfg.exists():
        return None
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        dist = (data.get("simulation") or {}).get("tom_distribution") or {}
        return {int(k): float(v) for k, v in dist.items()}
    except Exception:
        return None


def classify(dist: dict[int, float] | None) -> str:
    """返回 'pure_ToMX' / 'mixed' / 'unknown'。"""
    if not dist:
        return "unknown"
    nonzero = [(k, v) for k, v in dist.items() if v > 0]
    if len(nonzero) == 1 and abs(nonzero[0][1] - 1.0) < 1e-6:
        return f"pure_ToM{nonzero[0][0]}"
    return "mixed"


def dist_label(dist: dict[int, float] | None) -> str:
    if not dist:
        return "?"
    return " / ".join(f"T{k}:{int(round(v*100))}%" for k, v in sorted(dist.items()))


def read_confidence(run_dir: Path) -> tuple[list[float], dict[int, list[float]]]:
    """从 sentiment_series.jsonl 读取 confidence 与按 tom 分层的列表。"""
    p = run_dir / "sentiment_series.jsonl"
    overall: list[float] = []
    by_tom: dict[int, list[float]] = {0: [], 1: [], 2: []}
    if not p.exists():
        return overall, by_tom
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            c = r.get("confidence")
            if c is None:
                continue
            try:
                c = float(c)
            except Exception:
                continue
            overall.append(c)
            tom = r.get("tom_level")
            if isinstance(tom, int) and tom in by_tom:
                by_tom[tom].append(c)
    return overall, by_tom


def fmt(vals: list[float]) -> str:
    if not vals:
        return "n=0"
    return f"n={len(vals):>6}  mean={statistics.mean(vals):.4f}  stdev={statistics.pstdev(vals):.4f}"


def main():
    args = sys.argv[1:]
    if args:
        targets = [Path(a) if Path(a).is_absolute() else (ROOT / a) for a in args]
    else:
        if not RUNS_DIR.exists():
            print(f"runs/ 不存在: {RUNS_DIR}")
            sys.exit(1)
        targets = sorted(p for p in RUNS_DIR.iterdir() if p.is_dir())

    rows: list[dict] = []
    for run_dir in targets:
        if not run_dir.exists():
            print(f"[!] 跳过不存在的目录: {run_dir}")
            continue
        dist = load_tom_distribution(run_dir)
        overall, by_tom = read_confidence(run_dir)
        rows.append({
            "run": run_dir.name,
            "category": classify(dist),
            "dist": dist_label(dist),
            "overall": overall,
            "by_tom": by_tom,
        })

    # ===== 单实验表 =====
    print("=" * 110)
    print(f"{'RUN':<42} {'CATEGORY':<10} {'DIST':<22} {'N':>7}  {'MEAN':>7}  {'STDEV':>7}")
    print("-" * 110)
    for r in rows:
        vals = r["overall"]
        n = len(vals)
        mean = statistics.mean(vals) if vals else 0
        sd = statistics.pstdev(vals) if vals else 0
        print(f"{r['run']:<42} {r['category']:<10} {r['dist']:<22} {n:>7}  {mean:>7.4f}  {sd:>7.4f}")

    # ===== 按 ToM 分层（仅有意义的实验）=====
    print()
    print("=" * 110)
    print("按 tom_level 分层的平均信心（同一 run 内不同 ToM agent 子群对比）")
    print("-" * 110)
    print(f"{'RUN':<42} {'CATEGORY':<10} {'ToM0':<30} {'ToM1':<30} {'ToM2':<30}")
    for r in rows:
        b = r["by_tom"]
        def cell(vs):
            if not vs:
                return "-"
            return f"n={len(vs)} μ={statistics.mean(vs):.3f}±{statistics.pstdev(vs):.3f}"
        print(f"{r['run']:<42} {r['category']:<10} {cell(b[0]):<30} {cell(b[1]):<30} {cell(b[2]):<30}")

    # ===== 聚合：pure vs mixed =====
    pure: dict[str, list[float]] = {}
    mixed_all: list[float] = []
    for r in rows:
        cat = r["category"]
        if cat.startswith("pure_"):
            pure.setdefault(cat, []).extend(r["overall"])
        elif cat == "mixed":
            mixed_all.extend(r["overall"])

    print()
    print("=" * 110)
    print("聚合：纯 ToM vs 混合 ToM 的全市场平均信心")
    print("-" * 110)
    for k in sorted(pure):
        print(f"  {k:<12} {fmt(pure[k])}")
    print(f"  {'mixed':<12} {fmt(mixed_all)}")

    # pure 子集的 tom-matched 子群 vs mixed 对应 tom 子群
    print()
    print("=" * 110)
    print("同 tom_level 子群对比：纯 ToMX run 的该层 vs 各混合 run 的该层子群")
    print("-" * 110)
    for tom in (0, 1, 2):
        pure_vals = pure.get(f"pure_ToM{tom}", [])
        mixed_subgroup: list[float] = []
        for r in rows:
            if r["category"] == "mixed":
                mixed_subgroup.extend(r["by_tom"][tom])
        print(f"  ToM{tom}:  pure  {fmt(pure_vals)}")
        print(f"         mixed {fmt(mixed_subgroup)}")
        if pure_vals and mixed_subgroup:
            diff = statistics.mean(mixed_subgroup) - statistics.mean(pure_vals)
            print(f"         Δ(mixed − pure) = {diff:+.4f}")
        print()


if __name__ == "__main__":
    main()
