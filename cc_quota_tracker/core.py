"""核心：接收 home 目錄與時鐘，對外只有 poll、add、remove。"""
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import claude_provider as provider
from .board import Board, Card, ReadingState, Role


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
        return Card(
            None, Role.ACTIVE, ReadingState.HAS_READING,
            reading_age=self._clock() - reading.observed_at,
            windows=reading.windows,
        )
