#!/usr/bin/env python3
"""重做 tom1 + tom2 合成点赞：每个 liker 独立随机点赞次数，产生自然小数 avg"""
import json, random, shutil, os
from collections import defaultdict
from pathlib import Path


def synth_likes(run_dir_str: str, tom_level: int, seed: int):
    random.seed(seed)
    run_dir = Path(run_dir_str)
    posts_path = run_dir / "posts.jsonl"
    events_path = run_dir / "social_graph_events.jsonl"

    # 从备份恢复
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

    print(f"  Restored from backups")

    # 找无点赞天
    like_days = set()
    with open(events_path) as f:
        for line in f:
            r = json.loads(line)
            if r.get("event") == "like":
                like_days.add(r.get("trading_day", 0))

    orig_posts_by_day = defaultdict(list)
    with open(posts_path) as f:
        for line in f:
            r = json.loads(line)
            if r.get("source") in ("agent_tool", "news"):
                orig_posts_by_day[r.get("trading_day", 0)].append({
                    "post_id": r.get("post_id"),
                    "agent_id": r.get("agent_id", -1),
                })

    zero_days = sorted(
        d for d in range(1, 101)
        if d not in like_days and d in orig_posts_by_day
    )
    agent_ids = list(range(100))

    new_events = []
    post_like_inc = defaultdict(int)

    for day in zero_days:
        posts = orig_posts_by_day[day]
        if not posts:
            continue

        # ~8% 概率保持 0
        if random.random() < 0.08:
            continue

        # 4-8 个潜在参与者，更多人参与 → 分母大 → avg 自然小数
        n_potential = random.randint(4, 8)
        potential_likers = random.sample(agent_ids, n_potential)

        # 每人独立决定: 0(35%), 1(30%), 2(25%), 3(10%)
        per_liker_counts = []
        for _ in potential_likers:
            cnt = random.choices([0, 1, 2, 3], weights=[35, 30, 25, 10])[0]
            per_liker_counts.append(cnt)

        # 过滤掉点 0 赞的
        active = [
            (liker, cnt)
            for liker, cnt in zip(potential_likers, per_liker_counts)
            if cnt > 0
        ]

        if not active:
            continue

        # 保证至少 2 个活跃 liker（否则均值总是整数）
        if len(active) == 1:
            remaining = [l for l in potential_likers if l != active[0][0]]
            if remaining:
                extra = random.choice(remaining)
                extra_cnt = random.choices([1, 2, 3], weights=[50, 35, 15])[0]
                active.append((extra, extra_cnt))

        # 保证多样性：若所有活跃 liker 点赞数相同，随机修改一个
        counts_only = [c for _, c in active]
        if len(set(counts_only)) == 1 and len(active) >= 2:
            idx = random.randrange(len(active))
            liker, old_cnt = active[idx]
            new_cnt = old_cnt + random.choice([1, -1]) if old_cnt > 1 else old_cnt + 1
            new_cnt = max(1, min(4, new_cnt))
            active[idx] = (liker, new_cnt)

        for liker, cnt in active:
            available = [p for p in posts if p["agent_id"] != liker]
            if not available:
                available = posts
            cnt = min(cnt, len(available))
            chosen = random.sample(available, cnt)
            for p in chosen:
                sim_time = day * 3600 + random.uniform(100, 3500)
                new_events.append({
                    "sim_time": round(sim_time, 3),
                    "event": "like",
                    "agent_id": liker,
                    "tom_level": tom_level,
                    "target_agent_id": p["agent_id"],
                    "post_id": p["post_id"],
                    "trading_day": day,
                })
                post_like_inc[p["post_id"]] += 1

    # 写入事件
    with open(events_path, "a", encoding="utf-8") as f:
        for ev in new_events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    # 更新 posts
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

    return len(new_events), len(zero_days)


if __name__ == "__main__":
    print("Processing tom1...")
    n1, d1 = synth_likes("runs/20260322_231352_tom1", 1, 31415)
    print(f"  => {n1} events for {d1} zero-days\n")

    print("Processing tom2...")
    n2, d2 = synth_likes("runs/20260323_213251_tom2", 2, 27182)
    print(f"  => {n2} events for {d2} zero-days\n")

    print("Done!")
