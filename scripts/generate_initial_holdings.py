#!/usr/bin/env python3
"""根据 index_holding_prob.json 为 Agent 生成初始持仓分配。

所有参数自动从指定配置文件读取（n_agents, random_seed, index_holding_max/min）。

用法:
  python scripts/generate_initial_holdings.py                        # 使用 config.yaml
  python scripts/generate_initial_holdings.py --config config_100.yaml  # 使用 config_100.yaml
"""

import argparse
import json
import random
from pathlib import Path
from collections import Counter

import yaml

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="Generate initial holdings for agents")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config_path = ROOT / args.config
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    sim_cfg = cfg.get("simulation", {})
    agent_cfg = cfg.get("agent", {})

    n_agents = int(sim_cfg.get("n_agents", 1000))
    seed = sim_cfg.get("random_seed", 42)
    max_holdings = int(agent_cfg.get("index_holding_max", 6))
    min_holdings = max(1, int(agent_cfg.get("index_holding_min", 1)))
    min_holders = int(agent_cfg.get("min_holders_per_index", 0))
    prob_file = ROOT / str(agent_cfg.get("index_holding_prob_file", "data/index_holding_prob.json"))
    output_file = ROOT / str(agent_cfg.get("index_holding_file", "data/agents_initial_holdings.json"))

    if seed is not None:
        random.seed(int(seed))

    with open(prob_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    holdings_cfg = data["holdings"]
    prob_map = {sym: float(info["probability"]) for sym, info in holdings_cfg.items()}
    ranked = sorted(prob_map.keys(), key=lambda s: prob_map[s], reverse=True)

    agents: dict[int, list[str]] = {}
    global_counter: Counter = Counter()
    holding_count_dist: Counter = Counter()

    for agent_id in range(1, n_agents + 1):
        selected = []
        for symbol, prob in prob_map.items():
            if random.random() < prob:
                selected.append(symbol)

        if len(selected) > max_holdings:
            selected.sort(key=lambda s: prob_map.get(s, 0), reverse=True)
            selected = selected[:max_holdings]

        if len(selected) < min_holdings:
            for s in ranked:
                if s not in selected:
                    selected.append(s)
                if len(selected) >= min_holdings:
                    break

        selected.sort()
        agents[agent_id] = selected
        for s in selected:
            global_counter[s] += 1
        holding_count_dist[len(selected)] += 1

    # 最低覆盖率修补：确保每个指数至少被 min_holders 个 Agent 持有
    if min_holders > 0:
        patched = 0
        for symbol in prob_map:
            deficit = min_holders - global_counter.get(symbol, 0)
            if deficit <= 0:
                continue
            candidates = [
                aid for aid, syms in agents.items()
                if symbol not in syms and len(syms) < max_holdings
            ]
            random.shuffle(candidates)
            for aid in candidates[:deficit]:
                agents[aid].append(symbol)
                agents[aid].sort()
                global_counter[symbol] += 1
                patched += 1
        if patched:
            holding_count_dist.clear()
            for syms in agents.values():
                holding_count_dist[len(syms)] += 1
            print(f"Patched {patched} assignments to meet min_holders_per_index={min_holders}")

    summary = {
        "config": {
            "n_agents": n_agents,
            "random_seed": seed,
            "max_holdings": max_holdings,
            "min_holdings": min_holdings,
            "min_holders_per_index": min_holders,
            "source": str(prob_file.relative_to(ROOT)),
            "config_file": args.config,
        },
        "statistics": {
            "avg_holdings_per_agent": round(sum(len(v) for v in agents.values()) / n_agents, 2),
            "holding_count_distribution": {
                str(k): v for k, v in sorted(holding_count_dist.items())
            },
            "index_holder_counts": {
                sym: {
                    "holders": global_counter[sym],
                    "holder_pct": round(global_counter[sym] / n_agents * 100, 1),
                    "configured_prob": round(prob_map[sym] * 100, 1),
                }
                for sym in sorted(global_counter.keys(), key=lambda s: global_counter[s], reverse=True)
            },
        },
        "agents": {str(k): v for k, v in agents.items()},
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nGenerated holdings for {n_agents} agents → {output_file}")
    print(f"Config: {args.config}")
    print(f"Average holdings per agent: {summary['statistics']['avg_holdings_per_agent']}")
    print(f"\nHolding count distribution:")
    for count, n in sorted(holding_count_dist.items()):
        print(f"  {count} indices: {n} agents ({n/n_agents*100:.1f}%)")
    print(f"\nIndex holder counts (min_holders_per_index={min_holders}):")
    for sym in sorted(global_counter.keys(), key=lambda s: global_counter[s], reverse=True):
        mark = " ⚠️" if global_counter[sym] < min_holders else ""
        print(f"  {sym}: {global_counter[sym]} agents ({global_counter[sym]/n_agents*100:.1f}%) [configured: {prob_map[sym]*100:.1f}%]{mark}")


if __name__ == "__main__":
    main()
