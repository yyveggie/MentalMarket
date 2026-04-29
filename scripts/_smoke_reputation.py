"""新声誉系统与 KOL 双阈值的冒烟测试。

运行:
    python scripts/_smoke_reputation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domain.reputation import ReputationTracker
from app.domain.social_board import SocialBoard
from app.domain.social_graph import SocialGraph


def main() -> None:
    rep = ReputationTracker(
        initial_reputation=1.0,
        correct_weight=0.3,
        wrong_weight=0.3,
        like_weight=0.05,
        dislike_weight=0.05,
        retweet_weight=0.1,
        decay_rate=0.97,
    )
    graph = SocialGraph()
    graph.set_reputation_tracker(rep)
    graph.set_kol_thresholds(up=3.0, down=1.5)

    events: list[tuple] = []
    graph.set_event_callback(
        lambda e: events.append(("kol_evt", e.get("event"), e.get("agent_id"), e.get("reputation")))
    )

    graph.init_agents(
        agent_ids=[1, 2, 3],
        tom_levels={1: 0, 2: 1, 3: 2},
        kol_reputation_threshold=3.0,
        kol_reputation_loss_threshold=1.5,
    )

    board = SocialBoard(social_graph=graph, reputation_tracker=rep)

    post = board.publish(agent_id=1, content="hello", timestamp=0.0)
    print(f"[publish] post_id={post.post_id}")

    # 40 次点赞（+0.05 * 40 = 2.0，声誉 1.0 → 3.0）
    for _ in range(40):
        rep.record_like(1)
    print(f"after 40 likes  rep[1]={rep.get_reputation(1):.3f}  is_kol={graph.is_kol(1)}")

    # +10 次转发（+0.1 * 10 = 1.0，声誉 → 4.0，跨过 up=3.0）
    for _ in range(10):
        rep.record_retweet(1)
    print(f"after +10 retweets rep[1]={rep.get_reputation(1):.3f}  is_kol={graph.is_kol(1)}")

    # 50 次被踩（-0.05 * 50 = -2.5，声誉 → 1.5）
    for _ in range(50):
        rep.record_dislike(1)
    print(f"after 50 dislikes rep[1]={rep.get_reputation(1):.3f}  is_kol={graph.is_kol(1)}")

    # 再踩 5 次，跨过下阈 1.5
    for _ in range(5):
        rep.record_dislike(1)
    print(f"after +5 dislikes rep[1]={rep.get_reputation(1):.3f}  is_kol={graph.is_kol(1)}")

    # 每日衰减（decay_rate=0.97）
    rep.apply_decay(sim_time=86400)
    print(f"after apply_decay rep[1]={rep.get_reputation(1):.3f}")

    # 声誉下界为 0
    for _ in range(200):
        rep.record_dislike(1)
    print(f"after 200 more dislikes rep[1]={rep.get_reputation(1):.3f}  (should be 0)")

    print("\n--- KOL events ---")
    for e in events:
        print(e)


if __name__ == "__main__":
    main()
