"""akshare 雪球实时行情拉取。

使用 akshare 的 stock_individual_spot_xq 接口获取个股实时快照。
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class AkshareQuoteFetcher:
    """通过 akshare（雪球源）拉取个股实时报价。"""

    def __init__(self, symbols: list[str], max_history: int = 200):
        self.symbols = symbols
        self.max_history = max_history
        self.history: dict[str, deque[dict[str, Any]]] = {
            s: deque(maxlen=max_history) for s in symbols
        }

    def fetch(self) -> dict[str, dict[str, Any]]:
        """拉取所有标的的最新报价。

        Returns:
            {symbol: {"timestamp": str, "current": float, "change_pct": float, ...}}
        """
        import akshare as ak

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        results: dict[str, dict[str, Any]] = {}
        for symbol in self.symbols:
            try:
                df = ak.stock_individual_spot_xq(symbol=symbol)
                if df is None or df.empty:
                    logger.warning("akshare 返回空数据: %s", symbol)
                    continue
                # DataFrame 通常是 item/value 两列，转为 dict
                record: dict[str, Any] = {"timestamp": now, "symbol": symbol}
                for _, row in df.iterrows():
                    key = str(row.iloc[0]).strip()
                    val = row.iloc[1]
                    record[key] = val
                results[symbol] = record
                self.history[symbol].append(record)
            except Exception as exc:
                logger.warning("akshare 报价拉取失败 [%s]: %s", symbol, exc)
        return results

    def get_recent(self, symbol: str, n: int = 10) -> list[dict[str, Any]]:
        """返回某标的最近 n 条报价（从新到旧）。"""
        items = list(self.history.get(symbol, []))
        return items[-n:][::-1]

    def format_quote_text(self, quotes: dict[str, dict[str, Any]]) -> str:
        """将拉取到的报价格式化为可读文本，供 LLM prompt 使用。"""
        if not quotes:
            return "（暂无报价数据）"
        lines: list[str] = []
        for symbol, q in quotes.items():
            name = q.get("股票名称", symbol)
            current = q.get("现价", q.get("current", "N/A"))
            change_pct = q.get("涨跌幅", q.get("percent", "N/A"))
            high = q.get("最高", q.get("high", "N/A"))
            low = q.get("最低", q.get("low", "N/A"))
            volume = q.get("成交额", q.get("amount", "N/A"))
            open_px = q.get("今开", q.get("open", "N/A"))
            prev_close = q.get("昨收", q.get("last_close", "N/A"))
            lines.append(
                f"  {symbol} {name}: 现价={current} 涨跌幅={change_pct}% "
                f"今开={open_px} 昨收={prev_close} 最高={high} 最低={low} 成交额={volume}"
            )
        return "\n".join(lines)
