"""新浪财经实时新闻拉取（无外部依赖版）。

从 zhibo.sina.com.cn 财经直播流获取最新新闻，
内存去重，不依赖 MongoDB / 代理池。
"""

from __future__ import annotations

import logging
import re
import time
from ast import literal_eval
from collections import deque
from datetime import datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "referer": "https://finance.sina.com.cn/",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "zh-CN,zh;q=0.9",
}

_ZHIBO_URL = (
    "https://zhibo.sina.com.cn/api/zhibo/feed"
    "?callback=jQuery&page=1&page_size={page_size}"
    "&zhibo_id=152&tag_id=0&dire=f&dpc=1"
)


class SinaRealtimeNews:
    """内存缓存式新浪实时新闻抓取器。"""

    def __init__(self, page_size: int = 20, max_history: int = 100, dedup: bool = True):
        self.page_size = page_size
        self.max_history = max_history
        self.dedup = dedup
        self._url = _ZHIBO_URL.format(page_size=page_size)
        self._seen: set[str] = set()
        self.history: deque[dict[str, Any]] = deque(maxlen=max_history)

    # ------------------------------------------------------------------
    # 核心拉取
    # ------------------------------------------------------------------
    def fetch_raw(self) -> list[str]:
        """从新浪直播流获取原始 rich_text 列表。"""
        try:
            resp = requests.get(self._url, headers=_DEFAULT_HEADERS, timeout=15)
            resp.raise_for_status()
            text = resp.text
            items = re.findall(r'"rich_text":"(.*?)","multimedia":', text, re.S)
            # literal_eval 解码 unicode 转义（逐条处理，避免单条异常丢弃整批）
            decoded: list[str] = []
            for item in items:
                try:
                    decoded.append(literal_eval(f'"{item}"'))
                except Exception:
                    decoded.append(item)  # 解码失败则保留原始文本
            return decoded
        except Exception as exc:
            logger.warning("新浪新闻拉取失败: %s", exc)
            return []

    def fetch(self) -> list[dict[str, Any]]:
        """拉取新闻并返回本轮新增条目（去重后）。

        Returns:
            list of {"timestamp": str, "content": str}
        """
        raw_list = self.fetch_raw()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_items: list[dict[str, Any]] = []
        for text in raw_list:
            text = text.strip()
            if not text:
                continue
            if self.dedup and text in self._seen:
                continue
            self._seen.add(text)
            item = {"timestamp": now, "content": text}
            new_items.append(item)
            self.history.append(item)
        # 控制 seen 集合大小
        if len(self._seen) > self.max_history * 3:
            self._seen = {d["content"] for d in self.history}
        return new_items

    def get_recent(self, n: int = 10) -> list[dict[str, Any]]:
        """返回最近 n 条新闻（从新到旧）。"""
        items = list(self.history)
        return items[-n:][::-1]
