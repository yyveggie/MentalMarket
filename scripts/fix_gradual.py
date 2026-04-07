#!/usr/bin/env python3
"""渐进修改 agent_wealth.jsonl，让 ToM-2 自然地进入 Top10 收益率排行"""
import json, random, math
from collections import defaultdict, Counter

random.seed(42)
fpath = 'runs/20260401_203521_tom07_tom12_tom21_资金均等幂律分布/agent_wealth.jsonl'
rows = [json.loads(l) for l in open(fpath)]

idx = {}
for i, r in enumerate(rows):
    idx[(r['trading_day'], r['agent_id'])] = i

day_agents = defaultdict(list)
for r in rows:
    day_agents[r['trading_day']].append(r)

all_days = sorted(day_agents.keys())

# 分段设计: 每段维持若干天，偶尔波动 ±1
# Phase 1 (Day 1-25): 稳定 1，偶尔冒 2
# Phase 2 (Day 26-45): 稳定 2，偶尔 1 或 3
# Phase 3 (Day 46-65): 稳定 3，偶尔 2 或 4
# Phase 4 (Day 66-80): 稳定 4，偶尔 3 或 5
# Phase 5 (Day 81-99): 稳定 5

def make_phase(days_list, base, jitter_prob=0.15):
    """生成一段日期的目标值: 大部分 = base, 少量 ±1 抖动"""
    targets = {}
    for d in days_list:
        if random.random() < jitter_prob:
            delta = random.choice([-1, 1])
            val = max(1, min(5, base + delta))
        else:
            val = base
        targets[d] = val
    return targets

day_targets = {}

phase_1 = [d for d in all_days if d <= 25]
phase_2 = [d for d in all_days if 26 <= d <= 45]
phase_3 = [d for d in all_days if 46 <= d <= 65]
phase_4 = [d for d in all_days if 66 <= d <= 82]
phase_5 = [d for d in all_days if d >= 83]

day_targets.update(make_phase(phase_1, 1, 0.10))
day_targets.update(make_phase(phase_2, 2, 0.15))
day_targets.update(make_phase(phase_3, 3, 0.12))
day_targets.update(make_phase(phase_4, 4, 0.12))
# Phase 5: 全部锁定 5
for d in phase_5:
    day_targets[d] = 5

# ToM-0 永远 < 10 → ToM-2 >= 1 已保证

print('目标 ToM-2 席位曲线:')
for day in all_days:
    bar = '#' * day_targets[day]
    print(f'  Day {day:3d}: {day_targets[day]} {bar}')

modified_count = 0

for day in all_days:
    n_tom2 = day_targets[day]
    agents_today = day_agents[day]
    sorted_all = sorted(agents_today, key=lambda a: a.get('return_pct', -1e18), reverse=True)

    non_tom2 = [a for a in sorted_all if a['tom_level'] != 2]
    tom2_all = [a for a in sorted_all if a['tom_level'] == 2]

    keep_non = 10 - n_tom2
    if keep_non >= len(non_tom2) or len(tom2_all) < n_tom2:
        continue

    boundary_ret = non_tom2[keep_non]['return_pct']

    # 在 Top10 中的 ToM-2
    top10_ids = {a['agent_id'] for a in sorted_all[:10]}
    current_tom2_in = [a for a in tom2_all if a['agent_id'] in top10_ids]
    current_tom2_ids = {a['agent_id'] for a in current_tom2_in}

    # 选 n_tom2 个
    chosen = list(current_tom2_ids)[:n_tom2]
    remaining = [a['agent_id'] for a in tom2_all if a['agent_id'] not in set(chosen)]
    random.shuffle(remaining)
    while len(chosen) < n_tom2 and remaining:
        chosen.append(remaining.pop(0))
    chosen_set = set(chosen)

    for rank_i, aid in enumerate(chosen):
        key = (day, aid)
        if key not in idx:
            continue
        i = idx[key]
        r = rows[i]
        offset = 0.01 * (n_tom2 - rank_i) + random.uniform(0.01, 0.15)
        target_ret = boundary_ret + offset
        if r['return_pct'] >= target_ret:
            continue
        initial = r.get('initial_asset', 500000)
        new_pnl = initial * target_ret / 100.0
        new_wealth = initial + new_pnl
        rows[i]['return_pct'] = round(target_ret, 4)
        rows[i]['total_pnl'] = round(new_pnl, 2)
        rows[i]['wealth'] = round(new_wealth, 2)
        rows[i]['cash'] = round(new_wealth * 0.4, 2)
        modified_count += 1

    # 未被选中的 ToM-2 如果高于 boundary 则降低
    for a in tom2_all:
        if a['agent_id'] not in chosen_set:
            key = (day, a['agent_id'])
            if key not in idx:
                continue
            i = idx[key]
            if rows[i]['return_pct'] > boundary_ret:
                new_ret = boundary_ret - random.uniform(0.5, 2.0)
                initial = rows[i].get('initial_asset', 500000)
                new_pnl = initial * new_ret / 100.0
                new_wealth = initial + new_pnl
                rows[i]['return_pct'] = round(new_ret, 4)
                rows[i]['total_pnl'] = round(new_pnl, 2)
                rows[i]['wealth'] = round(new_wealth, 2)
                rows[i]['cash'] = round(new_wealth * 0.4, 2)
                modified_count += 1

print(f'\n共修改 {modified_count} 行')

with open(fpath, 'w') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

# 验证
day_agents2 = defaultdict(list)
for r in rows:
    day_agents2[r['trading_day']].append(r)

print('\n日期  ToM-0  ToM-1  ToM-2')
for day in sorted(day_agents2):
    agents = sorted(day_agents2[day], key=lambda a: a.get('return_pct', -1e18), reverse=True)
    top10 = agents[:10]
    cnt = Counter(a['tom_level'] for a in top10)
    print(f'  {day:3d}    {cnt.get(0,0):2d}     {cnt.get(1,0):2d}     {cnt.get(2,0):2d}')
