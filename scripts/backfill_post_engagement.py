#!/usr/bin/env python3
"""回填 posts.jsonl 的 likes 和 retweet_count 字段。

数据来源:
- retweet_count: 统计 source="retweet" 帖子的 metadata.original_post_id
- likes: 统计 social_graph_events.jsonl 的 like 事件
"""

import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path


def backfill_run(run_dir: str) -> dict:
    run_dir = Path(run_dir)
    posts_path = run_dir / "posts.jsonl"
    events_path = run_dir / "social_graph_events.jsonl"

    if not posts_path.exists():
        print(f"  SKIP: {posts_path} not found")
        return {}

    # ── 1. 第一遍: 统计 retweet_count 和 likes ──
    rt_counts: Counter = Counter()   # original_post_id → count
    like_counts: Counter = Counter()  # post_id → count

    # 统计转发
    with open(posts_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("source") == "retweet":
                opid = r.get("metadata", {}).get("original_post_id")
                if opid is not None:
                    rt_counts[opid] += 1

    # 统计点赞
    if events_path.exists():
        with open(events_path, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("event") == "like":
                    pid = r.get("post_id", 0)
                    if pid > 0:
                        like_counts[pid] += 1

    # ── 2. 第二遍: 写入 ──
    backup_path = posts_path.with_suffix(".jsonl.bak_engagement")
    shutil.copy2(posts_path, backup_path)
    print(f"  backed up → {backup_path.name}")

    tmp_path = posts_path.with_suffix(".jsonl.tmp")
    updated = 0
    total = 0

    with open(posts_path, encoding="utf-8") as fin, \
         open(tmp_path, "w", encoding="utf-8") as fout:
        for line in fin:
            r = json.loads(line)
            total += 1
            pid = r.get("post_id")

            likes = like_counts.get(pid, 0)
            retweet_count = rt_counts.get(pid, 0)

            changed = False
            if likes > 0 or r.get("likes", 0) != likes:
                r["likes"] = likes
                changed = True
            elif "likes" not in r:
                r["likes"] = 0
                changed = True

            if retweet_count > 0 or r.get("retweet_count", 0) != retweet_count:
                r["retweet_count"] = retweet_count
                changed = True
            elif "retweet_count" not in r:
                r["retweet_count"] = 0
                changed = True

            if changed:
                updated += 1

            fout.write(json.dumps(r, ensure_ascii=False) + "\n")

    os.replace(tmp_path, posts_path)

    stats = {
        "total_posts": total,
        "updated_posts": updated,
        "total_likes": sum(like_counts.values()),
        "liked_posts": len(like_counts),
        "total_retweet_count": sum(rt_counts.values()),
        "retweeted_posts": len(rt_counts),
    }
    return stats


def main():
    base = Path(__file__).resolve().parent.parent / "runs"
    run_dirs = sorted(base.glob("*_tom*"))

    if not run_dirs:
        print("No run directories found")
        sys.exit(1)

    for run_dir in run_dirs:
        name = run_dir.name
        print(f"\n{'='*60}")
        print(f"Processing: {name}")
        stats = backfill_run(str(run_dir))
        if stats:
            print(f"  total:    {stats['total_posts']} posts")
            print(f"  updated:  {stats['updated_posts']} posts")
            print(f"  likes:    {stats['total_likes']} (across {stats['liked_posts']} posts)")
            print(f"  retweets: {stats['total_retweet_count']} (across {stats['retweeted_posts']} posts)")

    print(f"\n{'='*60}")
    print("Done!")


if __name__ == "__main__":
    main()
