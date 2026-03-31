"""A 股交易时间判定工具。"""

from __future__ import annotations

import datetime
from typing import Optional

# A 股交易时段（北京时间）
_MORNING_OPEN = datetime.time(9, 30)
_MORNING_CLOSE = datetime.time(11, 30)
_AFTERNOON_OPEN = datetime.time(13, 0)
_AFTERNOON_CLOSE = datetime.time(15, 0)

# A 股法定工作日（周一到周五），不含法定节假日
_WEEKDAY_OPEN = (0, 1, 2, 3, 4)  # Monday=0 ... Friday=4


def is_market_open(now: Optional[datetime.datetime] = None) -> bool:
    """判断当前（北京时间）是否处于 A 股交易时段。

    不考虑法定节假日调休，仅按周一至周五 + 盘中时段判定。
    """
    if now is None:
        now = datetime.datetime.now()
    if now.weekday() not in _WEEKDAY_OPEN:
        return False
    t = now.time()
    return (_MORNING_OPEN <= t < _MORNING_CLOSE) or (_AFTERNOON_OPEN <= t < _AFTERNOON_CLOSE)


def seconds_until_next_open(now: Optional[datetime.datetime] = None) -> float:
    """计算距离下次开盘（含午盘恢复）的剩余秒数。

    返回 0 表示当前已在交易时段。
    """
    if now is None:
        now = datetime.datetime.now()

    if is_market_open(now):
        return 0.0

    t = now.time()
    today = now.date()

    # 如果是工作日
    if now.weekday() in _WEEKDAY_OPEN:
        # 早盘前
        if t < _MORNING_OPEN:
            target = datetime.datetime.combine(today, _MORNING_OPEN)
            return (target - now).total_seconds()
        # 午休
        if _MORNING_CLOSE <= t < _AFTERNOON_OPEN:
            target = datetime.datetime.combine(today, _AFTERNOON_OPEN)
            return (target - now).total_seconds()
        # 收盘后（15:00+），等到下一个交易日
        # fall through to next trading day logic

    # 查找下一个交易日（最多查 7 天）
    for offset in range(1, 8):
        next_day = today + datetime.timedelta(days=offset)
        if next_day.weekday() in _WEEKDAY_OPEN:
            target = datetime.datetime.combine(next_day, _MORNING_OPEN)
            return (target - now).total_seconds()

    # 理论上不会到这里
    return 3600.0
