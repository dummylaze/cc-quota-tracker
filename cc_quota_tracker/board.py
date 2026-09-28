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
    """percent 為 None：無計時中窗口（reset 為 True 時是週窗口已重置）；resets_at 為 None：重置時間未知。"""
    kind: str
    percent: Optional[int]
    severity: Severity
    resets_at: Optional[datetime]
    headline: bool = False
    scope: Optional[str] = None
    dollars: Optional[Dollars] = None
    reset: bool = False


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
    snapshot_invalid: bool = False  # 憑證被輪替：這張卡片的憑證快照已失效，需要重新納管


@dataclass(frozen=True)
class Board:
    """schema_changed：額度快取結構變更，卡片沿用最後一次成功的讀數；last_reading_at 是它的觀測時間。
    managed_accounts：所有納管帳號的帳號鍵（「供應商:帳號標籤」），依帳號鍵排序。
    wrong_location_suspected：Claude Code 目錄沒有指定、home 預設位置也沒有額度快取檔，可能讀錯位置。
    restart_required：執行中設定檔的路徑欄位改了；路徑只在啟動時解析，重新啟動才生效。
    settings_unreadable：設定檔不是合法的 JSON 物件；本工具不覆寫它，等使用者修好。"""
    cards: Tuple[Card, ...]
    schema_changed: bool = False
    last_reading_at: Optional[datetime] = None
    managed_accounts: Tuple[str, ...] = ()
    wrong_location_suspected: bool = False
    restart_required: bool = False
    settings_unreadable: bool = False
