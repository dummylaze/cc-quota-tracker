"""Claude 供應商的解析層：唯一接觸 ~/.claude.json 原始 dict 的地方。"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Tuple, Union

from .board import (BreakdownRow, Dollars, ExtraUsage, Limit, Money, Severity, Spend,
                    WeeklyBreakdown)

PROVIDER = "claude"  # 帳號鍵的供應商前綴
CREDENTIALS = ".credentials.json"  # Claude Code 目錄裡的當前憑證
WEEKLY_KIND = "weekly_all"
WINDOW_KINDS = ("session", WEEKLY_KIND)
SCOPED_KIND = "weekly_scoped"
# limits[] 各種類在 utilization 底下的對應欄位：數字以 limits[] 為準，這裡只取金額與鎖定原因
WINDOW_FIELDS = {"session": "five_hour", "weekly_all": "seven_day"}
# 舊式的分模型週限額欄位；limits[] 已有 weekly_scoped 時兩者重複，只在沒有時採用
MODEL_WEEKLY_FIELDS = ("seven_day_opus", "seven_day_sonnet")
# 形狀含 utilization 鍵、但不是其他限額的欄位
KNOWN_FIELDS = frozenset(WINDOW_FIELDS.values()) | set(MODEL_WEEKLY_FIELDS) | {"extra_usage"}

_SEVERITIES = {s.value: s for s in Severity}


@dataclass(frozen=True)
class ProviderSettings:
    """設定檔 providers.claude 底下的值；缺少或不合法時用這裡的預設。百分比門檻只在供應商沒給嚴重度時使用。
    目前只有設定檔的格式按供應商分開；程式只認得 Claude，第二家供應商時再抽介面（spec〈範圍外〉）。"""
    expiry_warning_days: int = 7  # 憑證快照剩不到這麼多天就發出到期警示
    warning_percent: int = 60
    critical_percent: int = 85


_DEFAULT = ProviderSettings()
# 第一次啟動時寫進設定檔的 providers.claude
SETTINGS_DEFAULTS = {"expiryWarningDays": _DEFAULT.expiry_warning_days,
                     "warningPercent": _DEFAULT.warning_percent, "criticalPercent": _DEFAULT.critical_percent}


@dataclass(frozen=True)
class UsageReading:
    observed_at: datetime
    account_id: Optional[str]
    limits: Tuple[Limit, ...] = ()
    scoped_limits: Tuple[Limit, ...] = ()
    other_limits: Tuple[Limit, ...] = ()
    locked_reason: Optional[str] = None
    weekly_breakdown: Optional[WeeklyBreakdown] = None
    extra_usage: Optional[ExtraUsage] = None
    spend: Optional[Spend] = None
    # 解析來源的 cachedUsageUtilization 原文：待命帳號的讀數以它存進工具狀態，重新啟動後再解析回來
    source: Optional[dict] = field(default=None, compare=False, repr=False)


class TransientlyUnreadable:
    """JSON 解析失敗，通常是讀到寫入中的檔案。"""


class NoReading:
    """cachedUsageUtilization 不存在，屬於正常狀態。"""


class SchemaMismatch:
    """有 utilization，但結構不符。"""


ParseResult = Union[UsageReading, TransientlyUnreadable, NoReading, SchemaMismatch]


def parse(text: str) -> ParseResult:
    try:
        raw = json.loads(text)
    except ValueError:
        return TransientlyUnreadable()
    if not isinstance(raw, dict) or "cachedUsageUtilization" not in raw:
        return NoReading()
    return parse_cache(raw["cachedUsageUtilization"])


def parse_cache(cache) -> Union[UsageReading, SchemaMismatch]:
    """解析 cachedUsageUtilization 本身；工具狀態裡存的就是這一段。"""
    try:
        return _to_reading(cache)
    except (KeyError, TypeError, ValueError, AttributeError):
        return SchemaMismatch()


def read_settings(providers) -> ProviderSettings:
    """providers 是設定檔的 providers 欄位。個別欄位不合法就用預設；兩個門檻不是由小到大時兩個都用預設。"""
    fields = providers.get(PROVIDER) if isinstance(providers, dict) else None
    fields = fields if isinstance(fields, dict) else {}
    days = _whole(fields.get("expiryWarningDays"), 1, None) or _DEFAULT.expiry_warning_days
    warning = _whole(fields.get("warningPercent"), 1, 100) or _DEFAULT.warning_percent
    critical = _whole(fields.get("criticalPercent"), 1, 100) or _DEFAULT.critical_percent
    if warning >= critical:
        warning, critical = _DEFAULT.warning_percent, _DEFAULT.critical_percent
    return ProviderSettings(days, warning, critical)


def grade(severity: Optional[Severity], percent: Optional[int], settings: ProviderSettings) -> Severity:
    """供應商給了嚴重度就以它為準；沒給才以百分比門檻推定。每輪以設定檔目前的門檻重算。"""
    if severity is not None:
        return severity
    if percent is None or percent < settings.warning_percent:
        return Severity.NORMAL
    return Severity.WARNING if percent < settings.critical_percent else Severity.CRITICAL


def account_id(text: str) -> Optional[str]:
    """目前登入帳號的識別碼（oauthAccount.accountUuid）；oauthAccount 裡的其他欄位（含 email）一律不取。"""
    try:
        value = json.loads(text)["oauthAccount"]["accountUuid"]
    except (ValueError, KeyError, TypeError):
        return None
    return value if isinstance(value, str) and value else None


def _to_reading(cache: dict) -> UsageReading:
    usage = cache["utilization"]
    items = usage["limits"]
    if not isinstance(items, list):
        raise TypeError("limits is not a list")
    windows, scoped, others = [], [], []
    for item in items:
        kind = item["kind"]
        if kind in WINDOW_KINDS:
            windows.append(_limit_row(item, dollars=_dollars(usage.get(WINDOW_FIELDS[kind]))))
        elif kind == SCOPED_KIND:
            scoped.append(_limit_row(item, scope=_scope_name(item.get("scope"))))
        else:
            others.append(_limit_row(item))
    limit_fields = {name: value for name, value in usage.items() if _is_limit_field(value)}
    if not scoped:
        scoped = [_field_limit(name, limit_fields[name]) for name in MODEL_WEEKLY_FIELDS if name in limit_fields]
    others += [_field_limit(name, value) for name, value in limit_fields.items() if name not in KNOWN_FIELDS]
    locked = next((q["locked_reason"] for q in limit_fields.values() if q.get("locked_reason")), None)
    observed = datetime.fromtimestamp(cache["fetchedAtMs"] / 1000, tz=timezone.utc)
    weekly_end = next((lim.resets_at for lim in windows if lim.kind == WEEKLY_KIND), None)
    return UsageReading(
        observed, cache.get("accountUuid"), tuple(windows), tuple(scoped), tuple(others), locked,
        _breakdown(usage.get("seven_day_breakdown"), weekly_end),
        _extra_usage(usage.get("extra_usage")), _spend(usage.get("spend")), cache,
    )


def _is_limit_field(value) -> bool:
    return isinstance(value, dict) and "utilization" in value


def _limit_row(item: dict, scope: Optional[str] = None, dollars: Optional[Dollars] = None) -> Limit:
    percent = int(item["percent"])
    return Limit(item["kind"], percent, _severity(item.get("severity")),
                 _parse_time(item.get("resets_at")), bool(item.get("is_active")), scope, dollars)


def _field_limit(name: str, field: dict) -> Limit:
    percent = None if field["utilization"] is None else int(field["utilization"])
    return Limit(name, percent, None, _parse_time(field.get("resets_at")),
                 dollars=_dollars(field))


def _severity(raw: Optional[str]) -> Optional[Severity]:
    """供應商沒給為 None，由核心依門檻推定；不認得的值當 normal。"""
    return None if raw is None else _SEVERITIES.get(raw, Severity.NORMAL)


def _whole(value, low: int, high: Optional[int]) -> Optional[int]:
    """設定檔裡的正整數；布林、小數、字串都不算。"""
    if isinstance(value, bool) or not isinstance(value, int) or value < low or (high is not None and value > high):
        return None
    return value


def _scope_name(scope: Optional[dict]) -> Optional[str]:
    for part in ("model", "surface"):
        if scope and scope.get(part):
            return scope[part]["display_name"]
    return None


def _dollars(field: Optional[dict]) -> Optional[Dollars]:
    if not field:
        return None
    amounts = Dollars(field.get("limit_dollars"), field.get("used_dollars"), field.get("remaining_dollars"))
    return None if amounts == Dollars(None, None, None) else amounts


def _breakdown(raw: Optional[dict], ends_at: Optional[datetime]) -> Optional[WeeklyBreakdown]:
    if not raw:
        return None
    rows = tuple(BreakdownRow(r["key"], r["display_name"], int(r["percent"])) for r in raw["rows"])
    return WeeklyBreakdown(_parse_time(raw.get("window_started_at")), ends_at, rows)


def _extra_usage(raw: Optional[dict]) -> Optional[ExtraUsage]:
    if not raw or not raw["is_enabled"]:
        return None
    currency, exponent = raw.get("currency"), raw.get("decimal_places") or 2

    def money(minor):
        return None if minor is None else Money(int(minor), currency, exponent)
    percent = raw.get("utilization")
    return ExtraUsage(money(raw.get("used_credits")), money(raw.get("monthly_limit")),
                      None if percent is None else int(percent))


def _spend(raw: Optional[dict]) -> Optional[Spend]:
    if not raw or not raw["enabled"]:
        return None
    percent = raw.get("percent")
    percent = None if percent is None else int(percent)
    return Spend(_money(raw.get("used")), _money(raw.get("limit")), percent,
                 _severity(raw.get("severity")))


def _money(raw: Optional[dict]) -> Optional[Money]:
    if not raw:
        return None
    return Money(int(raw["amount_minor"]), raw.get("currency"), int(raw.get("exponent", 2)))


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # 3.9 不吃結尾的 Z
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
