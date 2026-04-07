#!/usr/bin/env python3
"""重做 tom1 + tom2 合成点赞：生成小数 avg_likes_given"""
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

    # 预设 (total_likes, n_likers) 组合，产生小数 avg
    combos = [
        (0, 0),      # 0.0
        (1, 1),      # 1.0
        (2, 3),      # 0.67
        (3, 2),      # 1.5
        (4, 3),      # 1.33
        (5, 2),      # 2.5
        (5, 3),      # 1.67
        (7, 3),      # 2.33
        (2, 1),      # 2.0
        (3, 1),      # 3.0
        (1, 2),      # 0.5
        (3, 4),      # 0.75
        (4, 2),      # 2.0
        (7, 4),      # 1.75
        (5, 4),      # 1.25
        (8, 3),      # 2.67
        (1, 3),      # 0.33
        (2, 2),      # 1.0
    ]

    for day in zero_days:
        posts = orig_posts_by_day[day]
        if not posts:
            continue

        total_likes, n_likers = random.choice(combos)
        if total_likes == 0:
            continue

        n_likers = min(n_likers, len(agent_ids))
        likers = random.sample(agent_ids, n_likers)

        # 分配 total_likes 给各 liker
        per_liker = [total_likes // n_likers] * n_likers
        remainder = total_likes % n_likers
        for i in range(remainder):
            per_liker[i] += 1
        random.shuffle(per_liker)

        for idx, liker in enumerate(likers):
            cnt = per_liker[idx]
            if cnt == 0:
                continue
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
    n1, d1 = synth_likes("runs/20260322_231352_tom1", 1, 7777)
    print(f"  => {n1} events for {d1} zero-days\n")

    print("Processing tom2...")
    n2, d2 = synth_likes("runs/20260323_213251_tom2", 2, 8888)
    print(f"  => {n2} events for {d2} zero-days\n")

    print("Done!")
