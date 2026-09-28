"""看板：核心對外的唯一資料形狀，只帶語意狀態，不帶文案。"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Tuple


class Role(Enum):
    ACTIVE = "active"
    STANDBY = "standby"
    UNMANAGED = "unmanaged"


class ReadingState(Enum):
    HAS_READING = "has_reading"
    PENDING = "pending"
    NO_READING = "no_reading"


@dataclass(frozen=True)
class Window:
    kind: str
    percent: int
    resets_at: Optional[datetime]


@dataclass(frozen=True)
class Card:
    account_key: Optional[str]
    role: Role
    reading_state: ReadingState
    reading_age: Optional[timedelta] = None
    windows: Tuple[Window, ...] = ()


@dataclass(frozen=True)
class Board:
    cards: Tuple[Card, ...]
