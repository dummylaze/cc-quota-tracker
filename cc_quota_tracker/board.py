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


class Severity(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Money:
    """金額以最小單位表示：minor / 10**exponent 才是 currency 的金額。"""
    minor: int
    currency: Optional[str]
    exponent: int


@dataclass(frozen=True)
class Dollars:
    limit: Optional[float]
    used: Optional[float]
    remaining: Optional[float]


@dataclass(frozen=True)
class Limit:
    """percent 為 None：無計時中窗口；resets_at 為 None：重置時間未知。"""
    kind: str
    percent: Optional[int]
    severity: Severity
    resets_at: Optional[datetime]
    headline: bool = False
    scope: Optional[str] = None
    dollars: Optional[Dollars] = None


@dataclass(frozen=True)
class BreakdownRow:
    key: str
    label: str
    percent: int


@dataclass(frozen=True)
class WeeklyBreakdown:
    started_at: Optional[datetime]
    ends_at: Optional[datetime]
    rows: Tuple[BreakdownRow, ...]


@dataclass(frozen=True)
class ExtraUsage:
    used: Optional[Money]
    limit: Optional[Money]
    percent: Optional[int]


@dataclass(frozen=True)
class Spend:
    used: Optional[Money]
    limit: Optional[Money]
    percent: Optional[int]
    severity: Severity


@dataclass(frozen=True)
class Card:
    account_key: Optional[str]
    role: Role
    reading_state: ReadingState
    reading_age: Optional[timedelta] = None
    limits: Tuple[Limit, ...] = ()
    scoped_limits: Tuple[Limit, ...] = ()
    other_limits: Tuple[Limit, ...] = ()
    locked_reason: Optional[str] = None
    weekly_breakdown: Optional[WeeklyBreakdown] = None
    extra_usage: Optional[ExtraUsage] = None
    spend: Optional[Spend] = None


@dataclass(frozen=True)
class Board:
    cards: Tuple[Card, ...]
