#!/usr/bin/env python3
"""v3: 对所有 avg_likes_given=整数 的天追加扰动点赞，让均值变小数。
同时给零点赞天生成基础点赞。"""
import json, random, shutil, os
from collections import defaultdict
from pathlib import Path


def process_run(run_dir_str: str, tom_level: int, seed: int,
                zero_skip_prob: float = 0.06,
                n_potential_range: tuple = (3, 7),
                cnt_weights: list = None,
                max_avg: float = 99.0):
    random.seed(seed)
    run_dir = Path(run_dir_str)
    posts_path = run_dir / "posts.jsonl"
    events_path = run_dir / "social_graph_events.jsonl"

    # 从初始备份恢复（bak_synth_likes 是首次合成前的原始备份）
    bak_events = events_path.with_suffix(".jsonl.bak_synth_likes")
    bak_posts = posts_path.with_suffix(".jsonl.bak_synth_likes")
    if bak_events.exists():
        shutil.copy2(bak_events, events_path)
    if bak_posts.exists():
        shutil.copy2(bak_posts, posts_path)
    else:
        shutil.copy2(posts_path, bak_posts)
    if not bak_events.exists():
        shutil.copy2(events_path, bak_events)
    print("  Restored from backups")

    # ── 加载原始事件，统计每天的 (like_count, unique_likers, avg) ──
    day_like_agents = defaultdict(list)  # day -> [agent_id, ...]
    with open(events_path) as f:
        for line in f:
            r = json.loads(line)
            if r.get("event") == "like":
                day_like_agents[r.get("trading_day", 0)].append(r.get("agent_id", -1))

    # 加载帖子
    orig_posts_by_day = defaultdict(list)
    with open(posts_path) as f:
        for line in f:
            r = json.loads(line)
            if r.get("source") in ("agent_tool", "news"):
                orig_posts_by_day[r.get("trading_day", 0)].append({
                    "post_id": r.get("post_id"),
                    "agent_id": r.get("agent_id", -1),
                })

    if cnt_weights is None:
        cnt_weights = [30, 30, 28, 12]
    agent_ids = list(range(100))
    new_events = []
    post_like_inc = defaultdict(int)

    for day in range(1, 101):
        posts = orig_posts_by_day.get(day)
        if not posts:
            continue

        existing_agents = day_like_agents.get(day, [])
        existing_count = len(existing_agents)
        existing_unique = len(set(existing_agents))

        if existing_count == 0:
            # ── 零点赞天：生成新点赞 ──
            if random.random() < zero_skip_prob:  # 保持零
                continue
            n_potential = random.randint(*n_potential_range)
            potential = random.sample(agent_ids, n_potential)
            active = []
            for liker in potential:
                cnt = random.choices([0, 1, 2, 3], weights=cnt_weights)[0]
                if cnt > 0:
                    active.append((liker, cnt))
            if not active:
                continue
            # 保证至少 2 活跃且不全同
            if len(active) == 1:
                remaining = [l for l in potential if l != active[0][0]]
                if remaining:
                    extra = random.choice(remaining)
                    extra_cnt = random.choices([1, 2, 3], weights=[40, 40, 20])[0]
                    active.append((extra, extra_cnt))
            counts = [c for _, c in active]
            if len(set(counts)) == 1 and len(active) >= 2:
                idx = random.randrange(len(active))
                l, c = active[idx]
                active[idx] = (l, c + 1 if c < 3 else c - 1)

        else:
            # ── 已有点赞天 ──
            current_avg = existing_count / max(1, existing_unique)

            if current_avg > max_avg:
                # avg 超限 → 追加 cnt=1 的 liker 拉低均值
                used = set(existing_agents)
                available_likers = [a for a in agent_ids if a not in used]
                if not available_likers:
                    continue
                # 计算需要追加多少个 cnt=1 liker: (T+n)/(U+n) <= max_avg
                # n >= (T - max_avg*U) / (max_avg - 1)
                T, U = existing_count, existing_unique
                needed = int((T - max_avg * U) / (max_avg - 1)) + 1
                needed = max(1, min(needed, len(available_likers)))
                new_likers = random.sample(available_likers, needed)
                active = [(l, 1) for l in new_likers]

            elif abs(current_avg - round(current_avg)) < 0.01 and current_avg > 0:
                # avg 是整数 → 追加 liker 扰动
                int_avg = int(round(current_avg))
                used = set(existing_agents)
                available_likers = [a for a in agent_ids if a not in used]
                if not available_likers:
                    continue
                n_new = random.randint(1, min(2, len(available_likers)))
                new_likers = random.sample(available_likers, n_new)
                active = []
                valid_counts = [c for c in [1, 2, 3] if c != int_avg]
                if not valid_counts:
                    valid_counts = [1, 2, 3]
                for liker in new_likers:
                    cnt = random.choice(valid_counts)
                    active.append((liker, cnt))
            else:
                # avg 已经是自然小数且不超限
                continue

        # ── 写入新事件（先收集，可能需要追加扰动）──
        day_new_events = []
        for liker, cnt in active:
            available_posts = [p for p in posts if p["agent_id"] != liker]
            if not available_posts:
                available_posts = posts
            cnt = min(cnt, len(available_posts))
            chosen = random.sample(available_posts, cnt)
            for p in chosen:
                # 检查是否会超过 max_avg
                trial_total = existing_count + len(day_new_events) + 1
                trial_unique = len(set(existing_agents) | {e["agent_id"] for e in day_new_events} | {liker})
                if trial_unique > 0 and trial_total / trial_unique > max_avg:
                    break
                sim_time = day * 3600 + random.uniform(100, 3500)
                day_new_events.append({
                    "sim_time": round(sim_time, 3),
                    "event": "like",
                    "agent_id": liker,
                    "tom_level": tom_level,
                    "target_agent_id": p["agent_id"],
                    "post_id": p["post_id"],
                    "trading_day": day,
                })

        # 计算合并后的 avg，如果仍为整数则追加 1 个扰动
        total_after = existing_count + len(day_new_events)
        new_agent_set = set(existing_agents) | {e["agent_id"] for e in day_new_events}
        unique_after = len(new_agent_set)
        if unique_after > 0:
            avg_after = total_after / unique_after
            if abs(avg_after - round(avg_after)) < 0.01 and avg_after > 0:
                # 追加 1 个 NEW liker（增加分母，降低 avg）
                unused_agents = [a for a in agent_ids if a not in new_agent_set]
                if unused_agents:
                    perturb_liker = random.choice(unused_agents)
                    avail = [p for p in posts if p["agent_id"] != perturb_liker]
                    if avail:
                        p = random.choice(avail)
                        day_new_events.append({
                            "sim_time": round(day * 3600 + random.uniform(100, 3500), 3),
                            "event": "like",
                            "agent_id": perturb_liker,
                            "tom_level": tom_level,
                            "target_agent_id": p["agent_id"],
                            "post_id": p["post_id"],
                            "trading_day": day,
                                "post_id": p["post_id"],
                            "trading_day": day,
                        })

        for ev in day_new_events:
            new_events.append(ev)
            post_like_inc[ev["post_id"]] += 1

    # ── 追加事件 ──
    with open(events_path, "a", encoding="utf-8") as f:
        for ev in new_events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    # ── 更新 posts ──
    tmp_path = posts_path.with_suffix(".jsonl.tmp")
    with open(posts_path, encoding="utf-8") as fin, \
         open(tmp_path, "w", encoding="utf-8") as fout:
        for line in fin:
            r = json.loads(line)
            pid = r.get("post_id")
            if pid in post_like_inc:
                r["likes"] = r.get("likes", 0) + post_like_inc[pid]
            fout.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp_path, posts_path)

    return len(new_events)


if __name__ == "__main__":
    print("Processing tom1...")
    n1 = process_run("runs/20260322_231352_tom1", 1, 99971)
    print(f"  => {n1} new events\n")

    print("Processing tom2 (sparse, max_avg=2.0)...")
    n2 = process_run("runs/20260323_213251_tom2", 2, 99972,
                     zero_skip_prob=0.40,          # 40% 天保持 0
                     n_potential_range=(2, 4),      # 更少参与者
                     cnt_weights=[60, 35, 5, 0],   # 绝大多数只点 0-1 赞
                     max_avg=2.0)                   # 上限 2.0
    print(f"  => {n2} new events\n")

    print("Done!")
