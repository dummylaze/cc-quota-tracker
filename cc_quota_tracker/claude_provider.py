"""Claude 供應商的解析層：唯一接觸 ~/.claude.json 原始 dict 的地方。"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple, Union

from .board import (BreakdownRow, Dollars, ExtraUsage, Limit, Money, Severity, Spend,
                    WeeklyBreakdown)

WINDOW_KINDS = ("session", "weekly_all")
SCOPED_KIND = "weekly_scoped"
# limits[] 各種類在 utilization 底下的對應欄位：數字以 limits[] 為準，這裡只取金額與鎖定原因
WINDOW_FIELDS = {"session": "five_hour", "weekly_all": "seven_day"}
# 舊式的分模型週限額欄位；limits[] 已有 weekly_scoped 時兩者重複，只在沒有時採用
MODEL_WEEKLY_FIELDS = ("seven_day_opus", "seven_day_sonnet")
# 形狀含 utilization 鍵、但不是其他限額的欄位
KNOWN_FIELDS = frozenset(WINDOW_FIELDS.values()) | set(MODEL_WEEKLY_FIELDS) | {"extra_usage"}

_SEVERITIES = {s.value: s for s in Severity}
_WARNING_AT, _CRITICAL_AT = 60, 85


@dataclass(frozen=True)
class UsageReading:
    observed_at: datetime
    account_uuid: Optional[str]
    limits: Tuple[Limit, ...] = ()
    scoped_limits: Tuple[Limit, ...] = ()
    other_limits: Tuple[Limit, ...] = ()
    locked_reason: Optional[str] = None
    weekly_breakdown: Optional[WeeklyBreakdown] = None
    extra_usage: Optional[ExtraUsage] = None
    spend: Optional[Spend] = None


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
    try:
        return _to_reading(raw["cachedUsageUtilization"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return SchemaMismatch()


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
    weekly_end = next((lim.resets_at for lim in windows if lim.kind == "weekly_all"), None)
    return UsageReading(
        observed, cache.get("accountUuid"), tuple(windows), tuple(scoped), tuple(others), locked,
        _breakdown(usage.get("seven_day_breakdown"), weekly_end),
        _extra_usage(usage.get("extra_usage")), _spend(usage.get("spend")),
    )


def _is_limit_field(value) -> bool:
    return isinstance(value, dict) and "utilization" in value


def _limit_row(item: dict, scope: Optional[str] = None, dollars: Optional[Dollars] = None) -> Limit:
    percent = int(item["percent"])
    return Limit(item["kind"], percent, _severity(item.get("severity"), percent),
                 _parse_time(item.get("resets_at")), bool(item.get("is_active")), scope, dollars)


def _field_limit(name: str, field: dict) -> Limit:
    percent = None if field["utilization"] is None else int(field["utilization"])
    return Limit(name, percent, _severity(None, percent), _parse_time(field.get("resets_at")),
                 dollars=_dollars(field))


def _severity(raw: Optional[str], percent: Optional[int]) -> Severity:
    if raw is not None:
        return _SEVERITIES.get(raw, Severity.NORMAL)
    if percent is None or percent < _WARNING_AT:
        return Severity.NORMAL
    return Severity.WARNING if percent < _CRITICAL_AT else Severity.CRITICAL


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
                 _severity(raw.get("severity"), percent))


def _money(raw: Optional[dict]) -> Optional[Money]:
    if not raw:
        return None
    return Money(int(raw["amount_minor"]), raw.get("currency"), int(raw.get("exponent", 2)))


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # 3.9 不吃結尾的 Z
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
