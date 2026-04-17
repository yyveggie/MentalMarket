"""一次性脚本：读取无社交实验 agent_wealth.jsonl，按最后一天 return_pct Top10 统计 ToM 构成。"""
import json
from pathlib import Path
from collections import Counter, defaultdict


def compute(run_dir: Path):
    fp = run_dir / "agent_wealth.jsonl"
    if not fp.exists():
        return None
    day_agents: dict[int, list] = defaultdict(list)
    pop: dict[int, int] = {}
    with open(fp) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            day = r.get("trading_day")
            aid = r.get("agent_id")
            tom = r.get("tom_level", 0)
            ret = r.get("return_pct")
            if day is None or aid is None or ret is None:
                continue
            day_agents[int(day)].append({"aid": aid, "tom": int(tom), "ret": float(ret)})
            pop[aid] = int(tom)
    if not day_agents:
        return None
    last_day = max(day_agents)
    agents = sorted(day_agents[last_day], key=lambda a: a["ret"], reverse=True)
    n = len(agents)
    top10 = agents[:10]
    bot10 = agents[-10:]
    mid = n // 2
    median = agents[mid]["ret"] if n % 2 else (agents[mid - 1]["ret"] + agents[mid]["ret"]) / 2
    return {
        "last_day": last_day,
        "top10_composition": Counter(a["tom"] for a in top10),
        "population": Counter(pop.values()),
        "top10_avg_return": sum(a["ret"] for a in top10) / 10,
        "bot10_avg_return": sum(a["ret"] for a in bot10) / 10,
        "all_avg_return": sum(a["ret"] for a in agents) / n,
        "median_return": median,
    }


def main():
    base = Path("/Users/mushroom/Desktop/MentalMarket/runs")
    runs = [
        ("ToM01_ToM11_ToM21_无社交", "1:1:1 无社交"),
        ("ToM0_无社交", "纯 T0 无社交"),
        ("ToM1_无社交", "纯 T1 无社交"),
        ("ToM2_无社交", "纯 T2 无社交"),
        ("ToM01_ToM11_ToM21", "1:1:1 有社交 (对照)"),
    ]
    print(f"{'实验':<28}{'末日':>5}  Top10 构成        Top10均(%)  Bot10均(%)  全体均(%)  中位(%)")
    print("-" * 95)
    for r, lbl in runs:
        m = compute(base / r)
        if m is None:
            print(f"{lbl:<28}  [无数据]")
            continue
        top = m["top10_composition"]
        top_s = f"{top.get(0,0)}:{top.get(1,0)}:{top.get(2,0)}"
        print(f"{lbl:<28}{m['last_day']:>5}  T0:T1:T2={top_s:<8} "
              f"{m['top10_avg_return']:>9.4f}  {m['bot10_avg_return']:>9.4f}  "
              f"{m['all_avg_return']:>8.4f}  {m['median_return']:>6.4f}")


if __name__ == "__main__":
    main()
