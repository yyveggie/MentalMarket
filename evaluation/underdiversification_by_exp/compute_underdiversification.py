#!/usr/bin/env python3
"""按实验 × ToM 层级统计"持仓分散度"指标（改良版）。

与旧版的差异：
 1. **Agent 级聚合**：先按 Agent 计算其时间维度 HHI 均值，再跨 Agent 计算跨体均值
    和 95% bootstrap CI；而不是事件级简单求占比。
 2. **主指标改为连续量**：
      - mean_hhi            : Agent 级 HHI 均值（0~1，越高越集中）
      - norm_hhi            : 标准化 HHI = (HHI-1/N)/(1-1/N)，消除标的数 N 的下界影响
      - n_eff               : 有效持仓数 = 1/HHI，直观"等价等权几只股票"
 3. **阈值敏感性**：在 {0.2, 0.3, 0.4, 0.5, 0.6} 多阈值下报告触发率，证明结论稳健
    而非依赖单一 0.5 阈值。
 4. **预热剔除**：trading_day < WARMUP_DAYS 的记录不参与统计，
    避免初始 1 只持仓导致 HHI=1.0 的 artifact。
 5. **空仓排除**：holdings_count == 0 的事件单独计数，不计入 HHI 分布。

聚合流程（伪代码）：
    for run in experiments:
        for record in behavioral_biases.jsonl:
            if day < WARMUP_DAYS: skip
            if holdings_count == 0: counted as empty, skip HHI
            accumulate record.portfolio_hhi into agent_id's list
        for each agent_id:
            agent_mean_hhi = mean(that agent's HHI list)
        for each ToM level:
            group_mean_hhi = mean over agents of agent_mean_hhi
            ci95 = bootstrap(agent_mean_hhi list, B=2000)
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO / "runs"
OUT_DIR = Path(__file__).parent
OUT_JSON = OUT_DIR / "持仓分散度_汇总.json"

WARMUP_DAYS = 3
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 42
THRESHOLDS = [0.2, 0.3, 0.4, 0.5, 0.6]

EXPERIMENTS = [
    ("ToM1", "ToM1"),
    ("ToM2", "ToM2"),
    ("ToM00_ToM11_ToM21", "0:1:1"),
    ("ToM01_ToM10_ToM21", "1:0:1"),
    ("ToM01_ToM11_ToM20", "1:1:0"),
    ("ToM01_ToM11_ToM21", "1:1:1"),
    ("ToM02_ToM11_ToM21", "2:1:1"),
    ("ToM02_ToM13_ToM23", "2:3:3"),
    ("ToM06_ToM13_ToM21", "6:3:1"),
    ("ToM07_ToM12_ToM21", "7:2:1"),
]


def bootstrap_ci(vals: list[float], n: int = BOOTSTRAP_N,
                 seed: int = BOOTSTRAP_SEED) -> tuple[float, float]:
    if not vals:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    k = len(vals)
    means = []
    for _ in range(n):
        sample = [vals[rng.randrange(k)] for _ in range(k)]
        means.append(sum(sample) / k)
    means.sort()
    lo = means[int(0.025 * n)]
    hi = means[int(0.975 * n)]
    return (lo, hi)


def aggregate_one_run(path: Path) -> dict:
    """返回:
      {
        'overall': {...},
        'by_tom': {0: {...}, 1: {...}, 2: {...}},
        'threshold_sensitivity': {tom: {thr: trigger_rate}},
        'n_tradable': 10,
      }
    口径全部为 Agent 级：先按 agent 求 HHI 时均值，再跨 agent 汇总。
    """
    # agent_id -> list[hhi]
    per_agent_hhi: dict[int, list[float]] = defaultdict(list)
    per_agent_tom: dict[int, int] = {}
    per_agent_empty: dict[int, int] = defaultdict(int)  # 空仓事件计数
    per_agent_total: dict[int, int] = defaultdict(int)  # 总事件（含空仓）
    n_tradable_seen: set[int] = set()

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                continue
            day = row.get("trading_day")
            if day is not None and day < WARMUP_DAYS:
                continue
            aid = row.get("agent_id")
            tom = row.get("tom_level")
            if aid is None or tom is None:
                continue
            per_agent_tom[aid] = int(tom)
            per_agent_total[aid] += 1
            hc = row.get("holdings_count")
            hhi = row.get("portfolio_hhi")
            nt = row.get("total_tradable")
            if isinstance(nt, int):
                n_tradable_seen.add(nt)
            if hc == 0 or hhi is None:
                per_agent_empty[aid] += 1
                continue
            if isinstance(hhi, (int, float)):
                per_agent_hhi[aid].append(float(hhi))

    n_tradable = max(n_tradable_seen) if n_tradable_seen else 10

    # 每 agent 的 HHI 时间均值
    agent_mean_hhi: dict[int, float] = {}
    for aid, xs in per_agent_hhi.items():
        if xs:
            agent_mean_hhi[aid] = mean(xs)

    # 每 agent 各阈值触发率（该 agent 自己 HHI 观测中 > T 的比例）
    agent_trigger: dict[int, dict[float, float]] = {}
    for aid, xs in per_agent_hhi.items():
        if not xs:
            continue
        agent_trigger[aid] = {
            t: sum(1 for v in xs if v > t) / len(xs) for t in THRESHOLDS
        }

    # 按 ToM 层级汇总
    by_tom_agents: dict[int, list[float]] = defaultdict(list)  # HHI 均值
    for aid, hhi_bar in agent_mean_hhi.items():
        tom = per_agent_tom[aid]
        by_tom_agents[tom].append(hhi_bar)

    by_tom_trigger: dict[int, dict[float, list[float]]] = defaultdict(
        lambda: {t: [] for t in THRESHOLDS}
    )
    for aid, d in agent_trigger.items():
        tom = per_agent_tom[aid]
        for t, r in d.items():
            by_tom_trigger[tom][t].append(r)

    def pack_group(hhi_bars: list[float]) -> dict:
        if not hhi_bars:
            return {
                "mean_hhi": None,
                "ci95": [None, None],
                "n_eff": None,
                "norm_hhi": None,
                "n_agents": 0,
            }
        m = mean(hhi_bars)
        lo, hi = bootstrap_ci(hhi_bars)
        norm = (m - 1.0 / n_tradable) / (1 - 1.0 / n_tradable)
        return {
            "mean_hhi": round(m, 4),
            "ci95": [round(lo, 4), round(hi, 4)],
            "n_eff": round(1.0 / m, 3),
            "norm_hhi": round(norm, 4),
            "n_agents": len(hhi_bars),
        }

    by_tom = {}
    by_tom_threshold = {}
    for tom in sorted(by_tom_agents.keys()):
        by_tom[str(tom)] = pack_group(by_tom_agents[tom])
        by_tom_threshold[str(tom)] = {
            str(t): round(100 * mean(by_tom_trigger[tom][t]), 3)
            if by_tom_trigger[tom][t] else None
            for t in THRESHOLDS
        }

    overall_bars = list(agent_mean_hhi.values())
    overall = pack_group(overall_bars)

    all_trigger = {t: [] for t in THRESHOLDS}
    for aid, d in agent_trigger.items():
        for t, r in d.items():
            all_trigger[t].append(r)
    overall_threshold = {
        str(t): round(100 * mean(all_trigger[t]), 3) if all_trigger[t] else None
        for t in THRESHOLDS
    }

    empty_agents = [aid for aid in per_agent_total if per_agent_empty[aid] > 0]
    return {
        "n_tradable": n_tradable,
        "overall": overall,
        "overall_threshold_pct": overall_threshold,
        "by_tom": by_tom,
        "by_tom_threshold_pct": by_tom_threshold,
        "empty_event_count": sum(per_agent_empty.values()),
        "total_event_count": sum(per_agent_total.values()),
    }


def main() -> None:
    result = {
        "description": "按实验 × ToM 层级的 Agent 级持仓分散度统计",
        "method": {
            "aggregation_level": "per_agent_then_group",
            "warmup_days_skipped": WARMUP_DAYS,
            "exclude_empty_portfolio": True,
            "bootstrap_n": BOOTSTRAP_N,
            "thresholds_for_sensitivity": THRESHOLDS,
            "normalized_hhi": "(HHI - 1/N) / (1 - 1/N)",
            "n_eff": "1 / HHI_agent_mean",
        },
        "experiments": [],
    }

    hdr = (
        f"{'实验':<25}{'标签':<8}{'N':>4}"
        f"{'mean_hhi':>10}{'CI95':>22}{'n_eff':>8}{'norm_hhi':>10}{'agents':>8}"
    )
    print(hdr)
    print("-" * len(hdr))

    for run_dir, label in EXPERIMENTS:
        path = RUNS_DIR / run_dir / "behavioral_biases.jsonl"
        if not path.exists():
            print(f"{run_dir:<25}{label:<8}  [缺失] {path}")
            continue
        agg = aggregate_one_run(path)
        ov = agg["overall"]
        lo, hi = ov["ci95"]
        ci_str = f"[{lo:.3f},{hi:.3f}]" if lo is not None else "-"
        mh = ov["mean_hhi"] or float("nan")
        ne = ov["n_eff"] or float("nan")
        nh = ov["norm_hhi"] or float("nan")
        print(
            f"{run_dir:<25}{label:<8}{agg['n_tradable']:>4}"
            f"{mh:>10.4f}{ci_str:>22}{ne:>8.2f}{nh:>10.4f}"
            f"{ov['n_agents']:>8}"
        )
        result["experiments"].append({
            "run": run_dir,
            "label": label,
            "n_tradable": agg["n_tradable"],
            "overall": ov,
            "overall_threshold_pct": agg["overall_threshold_pct"],
            "by_tom": agg["by_tom"],
            "by_tom_threshold_pct": agg["by_tom_threshold_pct"],
            "empty_event_count": agg["empty_event_count"],
            "total_event_count": agg["total_event_count"],
        })

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n按 ToM 层级（Agent 级均值）:")
    print(f"{'实验':<25}{'ToM':>4}{'mean_hhi':>10}{'CI95':>22}{'n_eff':>8}{'n_agt':>6}")
    print("-" * 75)
    for entry in result["experiments"]:
        for tom, s in entry["by_tom"].items():
            lo, hi = s["ci95"]
            ci_str = f"[{lo:.3f},{hi:.3f}]" if lo is not None else "-"
            mh = s["mean_hhi"] if s["mean_hhi"] is not None else float("nan")
            ne = s["n_eff"] if s["n_eff"] is not None else float("nan")
            print(
                f"{entry['run']:<25}{tom:>4}"
                f"{mh:>10.4f}{ci_str:>22}{ne:>8.2f}"
                f"{s['n_agents']:>6}"
            )

    print("\n阈值敏感性：Agent 级触发率 % (事件中 HHI>T 的平均比例)")
    print(f"{'实验':<25}{'ToM':>4}" + "".join(f"{'T='+str(t):>10}" for t in THRESHOLDS))
    print("-" * (29 + 10 * len(THRESHOLDS)))
    for entry in result["experiments"]:
        for tom, d in entry["by_tom_threshold_pct"].items():
            row = f"{entry['run']:<25}{tom:>4}"
            for t in THRESHOLDS:
                v = d.get(str(t))
                row += f"{(v if v is not None else float('nan')):>10.2f}"
            print(row)

    print(f"\n写入: {OUT_JSON}")


if __name__ == "__main__":
    main()
