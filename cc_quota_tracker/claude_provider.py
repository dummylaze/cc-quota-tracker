"""Claude 供應商的解析層：唯一接觸 ~/.claude.json 原始 dict 的地方。"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple, Union

from .board import Window

WINDOW_KINDS = ("session", "weekly_all")


@dataclass(frozen=True)
class UsageReading:
    observed_at: datetime
    account_uuid: Optional[str]
    windows: Tuple[Window, ...]


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
    limits = cache["utilization"]["limits"]
    if not isinstance(limits, list):
        raise TypeError("limits is not a list")
    windows = []
    for item in limits:
        if item["kind"] in WINDOW_KINDS:
            windows.append(Window(item["kind"], int(item["percent"]), _parse_time(item.get("resets_at"))))
    observed = datetime.fromtimestamp(cache["fetchedAtMs"] / 1000, tz=timezone.utc)
    return UsageReading(observed, cache.get("accountUuid"), tuple(windows))


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # 3.9 不吃結尾的 Z
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
