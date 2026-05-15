from __future__ import annotations

import datetime
from typing import Optional

_MORNING_OPEN = datetime.time(9, 30)
_MORNING_CLOSE = datetime.time(11, 30)
_AFTERNOON_OPEN = datetime.time(13, 0)
_AFTERNOON_CLOSE = datetime.time(15, 0)

_WEEKDAY_OPEN = (0, 1, 2, 3, 4)


def is_market_open(now: Optional[datetime.datetime] = None) -> bool:
    if now is None:
        now = datetime.datetime.now()
    if now.weekday() not in _WEEKDAY_OPEN:
        return False
    t = now.time()
    return (_MORNING_OPEN <= t < _MORNING_CLOSE) or (_AFTERNOON_OPEN <= t < _AFTERNOON_CLOSE)


def seconds_until_next_open(now: Optional[datetime.datetime] = None) -> float:
    if now is None:
        now = datetime.datetime.now()

    if is_market_open(now):
        return 0.0

    t = now.time()
    today = now.date()

    if now.weekday() in _WEEKDAY_OPEN:
        if t < _MORNING_OPEN:
            target = datetime.datetime.combine(today, _MORNING_OPEN)
            return (target - now).total_seconds()
        if _MORNING_CLOSE <= t < _AFTERNOON_OPEN:
            target = datetime.datetime.combine(today, _AFTERNOON_OPEN)
            return (target - now).total_seconds()

    for offset in range(1, 8):
        next_day = today + datetime.timedelta(days=offset)
        if next_day.weekday() in _WEEKDAY_OPEN:
            target = datetime.datetime.combine(next_day, _MORNING_OPEN)
            return (target - now).total_seconds()

    return 3600.0
