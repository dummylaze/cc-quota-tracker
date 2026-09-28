"""核心：接收 home 目錄與時鐘，對外只有 poll、add、remove。"""
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Tuple

from . import claude_provider as provider
from .board import Board, Card, Limit, ReadingState, Role, Severity

SCHEMA_CHANGE_ROUNDS = 3  # 結構不符連續這麼多輪才判定為結構變更；偶發一次不亮橫幅


class Core:
    def __init__(self, home: Path, clock: Callable[[], datetime]):
        self._source = Path(home) / ".claude.json"
        self._clock = clock
        self._mtime: Optional[int] = None
        self._reading: Optional[provider.UsageReading] = None
        self._result: provider.ParseResult = provider.NoReading()
        self._mismatch_rounds = 0

    def poll(self) -> Board:
        self._refresh()
        reading = self._reading
        return Board(cards=(self._active_card(),),
                     schema_changed=self._mismatch_rounds >= SCHEMA_CHANGE_ROUNDS,
                     last_reading_at=reading.observed_at if reading else None)

    def add(self, label: str) -> None:
        raise NotImplementedError

    def remove(self, label: str) -> None:
        raise NotImplementedError

    def _refresh(self) -> None:
        result = self._read()
        if isinstance(result, provider.UsageReading):
            self._reading, self._mismatch_rounds = result, 0
        elif isinstance(result, provider.NoReading):
            self._reading, self._mismatch_rounds = None, 0
        elif isinstance(result, provider.SchemaMismatch):
            self._mismatch_rounds += 1
        # 暫時不可讀、偶發讀取失敗：沿用上一次的值，也不動結構不符的累計

    def _read(self) -> Optional[provider.ParseResult]:
        """來源檔案沒變時不重新解析，沿用上一次的解析結果，結構判定仍算一輪。
        偶發讀取失敗回傳 None，下一輪重試。"""
        try:
            mtime = os.stat(self._source).st_mtime_ns
        except FileNotFoundError:
            self._mtime, self._result = None, provider.NoReading()
            return self._result
        except OSError:
            return None
        if mtime != self._mtime:
            try:
                text = self._source.read_text(encoding="utf-8")
            except OSError:
                return None
            self._result = provider.parse(text)
            # 暫時不可讀不記修改時間：寫入中的檔案可能在同一個時間刻度內寫完，下一輪要重讀
            transient = isinstance(self._result, provider.TransientlyUnreadable)
            self._mtime = None if transient else mtime
        return self._result

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
