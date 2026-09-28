"""核心：接收 home 目錄與時鐘，對外只有 poll、add、remove。"""
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Tuple

from . import claude_provider as provider
from .board import Board, Card, Limit, ReadingState, Role, Severity


class Core:
    def __init__(self, home: Path, clock: Callable[[], datetime]):
        self._source = Path(home) / ".claude.json"
        self._clock = clock
        self._mtime: Optional[int] = None
        self._reading: Optional[provider.UsageReading] = None

    def poll(self) -> Board:
        self._refresh()
        return Board(cards=(self._active_card(),))

    def add(self, label: str) -> None:
        raise NotImplementedError

    def remove(self, label: str) -> None:
        raise NotImplementedError

    def _refresh(self) -> None:
        try:
            mtime = os.stat(self._source).st_mtime_ns
        except OSError:
            self._mtime, self._reading = None, None
            return
        if mtime == self._mtime:
            return
        try:
            text = self._source.read_text(encoding="utf-8")
        except OSError:
            return
        self._mtime = mtime
        result = provider.parse(text)
        if isinstance(result, provider.UsageReading):
            self._reading = result
        elif isinstance(result, provider.NoReading):
            self._reading = None
        # 暫時不可讀與結構不符：沿用上一次的值（結構橫幅由後續票處理）

    def _active_card(self) -> Card:
        reading = self._reading
        if reading is None:
            return Card(None, Role.ACTIVE, ReadingState.NO_READING)
        now = self._clock()
        breakdown = reading.weekly_breakdown
        if breakdown and breakdown.ends_at and not _counting(breakdown.ends_at, now):
            breakdown = None  # 週窗口已重置，舊的用量去向不再屬於計時中的這一週
        return Card(
            None, Role.ACTIVE, ReadingState.HAS_READING,
            reading_age=now - reading.observed_at,
            limits=_as_of(reading.limits, now),
            scoped_limits=_as_of(reading.scoped_limits, now),
            other_limits=_as_of(reading.other_limits, now),
            locked_reason=reading.locked_reason,
            weekly_breakdown=breakdown,
            extra_usage=reading.extra_usage,
            spend=reading.spend,
        )


def _counting(resets_at: Optional[datetime], now: datetime) -> bool:
    return resets_at is not None and now < resets_at


def _as_of(limits: Tuple[Limit, ...], now: datetime) -> Tuple[Limit, ...]:
    """沒有重置時間或已過重置時間：無計時中窗口，重置時間未知，不推算下一次。
    週窗口固定 7 天，過了重置時間代表新的一週已開始，標為已重置。"""
    return tuple(
        lim if _counting(lim.resets_at, now)
        else replace(lim, percent=None, resets_at=None, severity=Severity.NORMAL,
                     reset=lim.resets_at is not None and lim.kind == provider.WEEKLY_KIND)
        for lim in limits
    )
