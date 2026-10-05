"""看板：核心對外的唯一資料形狀，只帶語意狀態，不帶文案。"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Tuple


class Role(Enum):
    ACTIVE = "active"
    STANDBY = "standby"
    UNWATCHED = "unwatched"


WRITEBACK_ATTEMPTS = 3  # 固定值：寫回同一份當前憑證最多寫這麼多次（含第一次），都失敗就停止重試


class WatchOnlyReason(Enum):
    """監看帳號不能切換過去的原因（僅監看帳號）。同時符合多個時只帶一個，宣告順序即優先順序。
    補救一律是在 Claude Code 登入該帳號後重新納管。"""
    EXPIRED = "expired"
    INVALID = "invalid"
    WRITEBACK_RETRYING = "writeback_retrying"  # 憑證同步寫回失敗，之後每輪自動重試；成功就恢復成納管帳號
    WRITEBACK_STOPPED = "writeback_stopped"  # 寫回失敗已達次數上限、或當前憑證已不是那次登入：不再重試
    NO_ACCOUNT_INFO = "no_account_info"


class ReadingState(Enum):
    HAS_READING = "has_reading"
    PENDING = "pending"
    NO_READING = "no_reading"


class CountdownFormat(Enum):
    """倒數的顯示格式（設定檔的 countdownFormat）。兩者不足的部分一律捨去，不進位；剩不到一天時都顯示「時＋分」。"""
    TWO_UNITS = "twoUnits"  # 「天＋時」
    DECIMAL_DAYS = "decimalDays"  # 天數到小數第 1 位


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
    """percent 為 None：無計時中窗口（reset 為 True 時是週窗口已重置）；resets_at 為 None：重置時間未知。
    severity 在看板上一定有值；解析層遇到供應商沒給時先留 None，由核心依設定的百分比門檻補上。"""
    kind: str
    percent: Optional[int]
    severity: Optional[Severity]
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
    severity: Optional[Severity]  # 同 Limit.severity：看板上一定有值


@dataclass(frozen=True)
class Card:
    account_key: Optional[str]
    role: Role
    reading_state: ReadingState
    reading_age: Optional[timedelta] = None
    # 落後讀數：觀測之後本機又有新對話。當前憑證帳號是當下判斷的；待命帳號是切換時就已落後（存在工具狀態，讀數換了才清除）
    lagging: bool = False
    limits: Tuple[Limit, ...] = ()
    scoped_limits: Tuple[Limit, ...] = ()
    other_limits: Tuple[Limit, ...] = ()
    locked_reason: Optional[str] = None
    weekly_breakdown: Optional[WeeklyBreakdown] = None
    extra_usage: Optional[ExtraUsage] = None
    spend: Optional[Spend] = None
    snapshot_invalid: bool = False  # 失效的憑證快照：找不到與當前憑證同一次登入的證據，保留到重新納管
    # 憑證快照的 refreshToken 到期時間；未監看帳號或快照沒寫到期時間（暫當無效資料）為 None
    snapshot_expires_at: Optional[datetime] = None
    snapshot_expiring: bool = False  # 剩不到 7 天（含已過期）：要在該帳號下重新登入，再對同一標籤重新 add
    # 能不能切換過去：監看帳號裡的納管帳號為 True；僅監看帳號與未監看帳號為 False。
    # watch_only_reason 只有僅監看帳號有值；版面與 list 都從這兩個欄位渲染
    switchable: bool = False
    watch_only_reason: Optional[WatchOnlyReason] = None
    writeback_failures: Optional[int] = None  # 寫回重試中時，已經失敗的次數（1 起算）；其他原因為 None


@dataclass(frozen=True)
class Preferences:
    """設定檔的偏好，值與設定檔相同；供畫面層套用。倒數格式另放在 Board.countdown_format。"""
    layout: str = "cards"  # cards／table／ring
    always_on_top: bool = True
    mode: str = "compact"  # compact／expanded
    language: str = "system"  # system／zh-TW／en
    theme: str = "system"  # system／light／dark
    opacity: int = 100  # 100／85／70
    font: Optional[str] = None  # 字型家族名稱；None 用設計 token 的內建字型。只能在設定檔調整


AUTO_QUERY_FLOOR_MINUTES = 5  # 固定值：自動查詢間隔的下限；供應商沒有公開這個端點的限流門檻，5 分鐘是推測值


class QueryFailure(Enum):
    """查詢額度失敗的四種原因（ADR-0010）。"""
    COMMAND_NOT_FOUND = "command_not_found"  # 找不到 claude 執行檔，含設定的路徑不存在或不合法
    TIMEOUT = "timeout"
    REPORTED_ERROR = "reported_error"  # Claude Code 回報錯誤；原始訊息放在 UsageQueryResult.message，不翻譯
    NOT_WRITTEN = "not_written"  # Claude Code 結束了，但額度快取的觀測時間沒有前進


@dataclass(frozen=True)
class UsageQueryResult:
    """failure 為 None 是成功，observed_at 是額度快取新的觀測時間。message 只在 Claude Code 回報錯誤時有值。"""
    failure: Optional[QueryFailure] = None
    observed_at: Optional[datetime] = None
    message: Optional[str] = None


@dataclass(frozen=True)
class QueryStatus:
    """查詢額度的狀態，只存在記憶體，重新啟動後從頭開始。in_progress 與 cooling_down 時不能再觸發；
    last_failure 是最後一次失敗的結果，之後有查詢成功才清除（進行中、冷卻中仍帶著）。
    auto_enabled：設定檔開啟了自動查詢。auto_paused：自動查詢已開啟、但連續失敗到達上限而暫停，
    一次成功的查詢（含手動）才恢復；暫停時 last_failure 就是最後一次失敗的原因。
    interval_below_floor：自動查詢已開啟、設定檔填的間隔低於下限，實際以下限執行。"""
    in_progress: bool = False
    cooling_down: bool = False
    last_failure: Optional[UsageQueryResult] = None
    auto_enabled: bool = False
    auto_paused: bool = False
    interval_below_floor: bool = False


@dataclass(frozen=True)
class Board:
    """schema_changed：額度快取結構變更，卡片沿用最後一次成功的讀數；last_reading_at 是它的觀測時間。
    watched_accounts：所有監看帳號的帳號鍵（「供應商:帳號標籤」），依帳號鍵排序。
    wrong_location_suspected：Claude Code 目錄沒有指定、home 預設位置也沒有額度快取檔，可能讀錯位置。
    restart_required：執行中設定檔的路徑欄位改了；路徑只在啟動時解析，重新啟動才生效。
    settings_unreadable：設定檔不是合法的 JSON 物件；本工具不覆寫它，等使用者修好。
    as_of：這一輪的時間，畫面層以它算倒數。countdown_format：設定檔目前的倒數格式。
    preferences：設定檔目前的偏好。invalid_settings：值不合法、改用預設的設定檔欄位名稱，依名稱排序。
    usage_query：查詢額度的狀態。permissions_untightened：這一輪有納管目錄的權限收緊後查回仍未收緊，且使用者沒有關掉這個告警（ADR-0008）。"""
    cards: Tuple[Card, ...]
    schema_changed: bool = False
    last_reading_at: Optional[datetime] = None
    watched_accounts: Tuple[str, ...] = ()
    wrong_location_suspected: bool = False
    restart_required: bool = False
    settings_unreadable: bool = False
    as_of: Optional[datetime] = None
    countdown_format: CountdownFormat = CountdownFormat.TWO_UNITS
    preferences: Preferences = Preferences()
    invalid_settings: Tuple[str, ...] = ()
    usage_query: QueryStatus = QueryStatus()
    permissions_untightened: bool = False
