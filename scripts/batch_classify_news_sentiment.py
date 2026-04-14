#!/usr/bin/env python3
"""批量标注 news.json 中新闻标题的情绪方向（positive/negative/neutral）。

使用 LLM API 对新闻标题做金融情绪分类，结果写入 news.json 的 sentiment 字段。

用法：
  python scripts/batch_classify_news_sentiment.py
  python scripts/batch_classify_news_sentiment.py --news-file data/news.json --batch-size 30
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx


API_URL = "https://openrouter.fans/v1/chat/completions"
API_KEY = "sk-NWWyqlstd76qiIu9zVK4vKdih1potzosYqPyYMHUZKR7KGeK"
MODEL = "deepseek-chat"
MAX_CONCURRENCY = 30
TIMEOUT = 60

SYSTEM_PROMPT = """\
你是一个A股金融新闻情绪分类器。对于每条新闻标题，判断其对相关股票的情绪方向：
- positive: 利好消息（业绩增长、政策利好、技术突破、合作签约等）
- negative: 利空消息（罚款、违规、业绩下滑、监管处罚、风险事件等）
- neutral: 中性消息（日常报道、行业信息、人事变动、无明确方向等）

只输出JSON数组，每个元素是 "positive"、"negative" 或 "neutral"，数量和输入标题一一对应。不要输出任何其他文字。"""


async def classify_batch(client: httpx.AsyncClient,
                         titles: list[str],
                         semaphore: asyncio.Semaphore,
                         batch_id: int) -> list[str]:
    """对一批标题做情绪分类，返回 ['positive', 'negative', ...] 。"""
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    user_msg = f"请对以下 {len(titles)} 条新闻标题分类：\n{numbered}"

    async with semaphore:
        for attempt in range(3):
            try:
                resp = await client.post(
                    API_URL,
                    headers={
                        "Authorization": f"Bearer {API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.0,
                        "max_tokens": len(titles) * 15 + 50,
                    },
                    timeout=TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                content = content.strip("`").strip()
                if content.startswith("json"):
                    content = content[4:].strip()
                labels = json.loads(content)
                if isinstance(labels, list) and len(labels) == len(titles):
                    valid = []
                    for lb in labels:
                        lb = str(lb).strip().lower()
                        if lb in ("positive", "negative", "neutral"):
                            valid.append(lb)
                        else:
                            valid.append("neutral")
                    print(f"  batch {batch_id}: {len(valid)} 条 OK")
                    return valid
                else:
                    print(f"  batch {batch_id}: 数量不匹配 "
                          f"(期望{len(titles)}, 得到{len(labels) if isinstance(labels, list) else '非数组'}), "
                          f"重试 {attempt+1}/3")
            except Exception as e:
                print(f"  batch {batch_id}: 错误 {e}, 重试 {attempt+1}/3")
                await asyncio.sleep(2 ** attempt)

    print(f"  batch {batch_id}: 3次重试均失败，标记为 neutral")
    return ["neutral"] * len(titles)


async def main_async(news_file: str, batch_size: int):
    news_path = Path(news_file)
    with open(news_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    news_list = data.get("news", data) if isinstance(data, dict) else data
    total = len(news_list)
    print(f"共 {total} 条新闻")

    already = sum(1 for n in news_list if "sentiment" in n)
    if already > 0:
        print(f"已有 {already} 条标注，跳过已标注的")

    to_classify = [(i, n["title"]) for i, n in enumerate(news_list)
                   if "sentiment" not in n and n.get("title")]
    print(f"待标注: {len(to_classify)} 条")

    if not to_classify:
        print("无需标注")
        return

    batches = []
    for start in range(0, len(to_classify), batch_size):
        batch = to_classify[start:start + batch_size]
        batches.append(batch)
    print(f"分为 {len(batches)} 批（每批 {batch_size} 条）\n")

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    async with httpx.AsyncClient() as client:
        tasks = []
        for bid, batch in enumerate(batches):
            titles = [t for _, t in batch]
            tasks.append(classify_batch(client, titles, semaphore, bid))

        results = await asyncio.gather(*tasks)

    classified = 0
    for batch, labels in zip(batches, results):
        for (idx, _), label in zip(batch, labels):
            news_list[idx]["sentiment"] = label
            classified += 1

    if isinstance(data, dict):
        data["news"] = news_list
    else:
        data = news_list

    backup = news_path.with_suffix(".json.bak")
    import shutil
    shutil.copy2(news_path, backup)
    print(f"\n备份: {backup}")

    with open(news_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已标注 {classified} 条，写入: {news_path}")

    pos = sum(1 for n in news_list if n.get("sentiment") == "positive")
    neg = sum(1 for n in news_list if n.get("sentiment") == "negative")
    neu = sum(1 for n in news_list if n.get("sentiment") == "neutral")
    print(f"\n分布: positive={pos}  negative={neg}  neutral={neu}")


def main():
    parser = argparse.ArgumentParser(description="批量标注新闻情绪")
    parser.add_argument("--news-file", default="data/news.json",
                        help="新闻文件路径")
    parser.add_argument("--batch-size", type=int, default=30,
                        help="每批标题数（默认 30）")
    args = parser.parse_args()
    asyncio.run(main_async(args.news_file, args.batch_size))


if __name__ == "__main__":
    main()
