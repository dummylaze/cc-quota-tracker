"""Claude 供應商的解析層：唯一接觸 ~/.claude.json 原始 dict 的地方。"""
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple, Union

from .board import (BreakdownRow, Dollars, ExtraUsage, Limit, Money, Severity, Spend,
                    WeeklyBreakdown)

PROVIDER = "claude"  # 帳號鍵的供應商前綴
CREDENTIALS = ".credentials.json"  # Claude Code 目錄裡的當前憑證
TRANSCRIPTS = "projects"  # Claude Code 目錄裡的對話紀錄：<專案>/<對話>.jsonl，每輪對話都會寫入
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
    claude_command: Optional[Path] = None  # 查詢額度用的 claude 執行檔；None 從 PATH 找
    claude_command_invalid: bool = False  # 有填但不是絕對路徑：查詢一律找不到，不退回 PATH


_DEFAULT = ProviderSettings()
_SETTINGS_ROOT = "providers"  # 設定檔裡這組設定的欄位名稱；與 settings.PROVIDERS_FIELD 相同（settings 匯入本模組，不能反過來）
CLAUDE_COMMAND_FIELD = "claudeCommand"
_FIELD_RANGES = (("expiryWarningDays", 1, None), ("warningPercent", 1, 100), ("criticalPercent", 1, 100))  # 設定檔欄位名稱與合法範圍
# 第一次啟動時寫進設定檔的 providers.claude
SETTINGS_DEFAULTS = {"expiryWarningDays": _DEFAULT.expiry_warning_days,
                     "warningPercent": _DEFAULT.warning_percent, "criticalPercent": _DEFAULT.critical_percent,
                     CLAUDE_COMMAND_FIELD: None}


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


class FieldStatus(Enum):
    OK = "ok"
    MISSING = "missing"  # 必要欄位不存在
    WRONG_TYPE = "wrong_type"
    ABSENT = "absent"  # 可選欄位不存在或為 null
    NO_ITEMS = "no_items"  # 清單是空的，元素的欄位無從檢查
    PARENT_ABSENT = "parent_absent"  # 上層不存在或為 null：可選的上層不在就免檢查，必要的上層由上層那一列報告
    UNREACHABLE = "unreachable"  # 上層欄位不存在或型別不符，由上層那一列報告


@dataclass(frozen=True)
class FieldCheck:
    path: str
    expected: str  # 型別：object／list／string／number／boolean
    required: bool
    status: FieldStatus
    actual: Optional[str] = None  # 型別不符時的實際型別，同一套型別名稱加上 null


@dataclass(frozen=True)
class SchemaCheck:
    fields: Tuple[FieldCheck, ...]
    new_fields: Tuple[Tuple[str, bool], ...]  # utilization 底下不在 OBSERVED_USAGE_FIELDS 的欄位：(名稱, 是否額度形狀)
    parses: bool  # 解析層實際解析得動；欄位清單沒列到的依賴壞掉時，靠這一項兜住

    @property
    def failures(self) -> Tuple[FieldCheck, ...]:
        return tuple(f for f in self.fields if f.status in (FieldStatus.MISSING, FieldStatus.WRONG_TYPE))

    @property
    def compatible(self) -> bool:
        return self.parses and not self.failures


_USAGE = "cachedUsageUtilization.utilization"
# 本工具依賴的欄位路徑：(路徑, 型別, 必要)。路徑從 .claude.json 的根算起，[] 表示清單裡的每一個元素。
# 上層排在下層前面；可選欄位不存在或為 null 不算不相容，有值就必須是這個型別。可選物件底下的必要欄位，只在該物件存在時檢查。
# 這份清單列的是架設者最需要看到的路徑，不是解析層依賴的全集：相容與否最終以解析層實際解析的結果為準
DEPENDED_FIELDS = (
    ("oauthAccount", "object", True),
    ("oauthAccount.accountUuid", "string", True),
    ("cachedUsageUtilization", "object", True),
    ("cachedUsageUtilization.fetchedAtMs", "number", True),
    ("cachedUsageUtilization.accountUuid", "string", True),
    (_USAGE, "object", True),
    (f"{_USAGE}.limits", "list", True),
    (f"{_USAGE}.limits[]", "object", True),
    (f"{_USAGE}.limits[].kind", "string", True),
    (f"{_USAGE}.limits[].percent", "number", True),
    (f"{_USAGE}.limits[].severity", "string", False),
    (f"{_USAGE}.limits[].resets_at", "string", False),
    (f"{_USAGE}.limits[].is_active", "boolean", False),
    (f"{_USAGE}.limits[].scope", "object", False),
    *((f"{_USAGE}.{name}", "object", False) for name in (
        *WINDOW_FIELDS.values(), *MODEL_WEEKLY_FIELDS, "seven_day_breakdown", "extra_usage", "spend")),
    (f"{_USAGE}.seven_day_breakdown.rows", "list", True),
    (f"{_USAGE}.seven_day_breakdown.rows[]", "object", True),
    (f"{_USAGE}.seven_day_breakdown.rows[].key", "string", True),
    (f"{_USAGE}.seven_day_breakdown.rows[].display_name", "string", True),
    (f"{_USAGE}.seven_day_breakdown.rows[].percent", "number", True),
    (f"{_USAGE}.extra_usage.is_enabled", "boolean", True),
    (f"{_USAGE}.spend.enabled", "boolean", True),
)
# utilization 底下已經見過的欄位（2026-09 實測）。本工具多半不用它們，列在這裡只是為了讓檢查指令只報新出現的欄位；
# 代號欄位若變成額度形狀，看板照樣當成其他限額顯示，與這份清單無關
OBSERVED_USAGE_FIELDS = frozenset({
    "limits", *KNOWN_FIELDS, "seven_day_breakdown", "spend", "member_dashboard_available",
    "seven_day_cowork", "seven_day_oauth_apps", "seven_day_omelette", "omelette_promotional",
    "amber_cistern", "amber_gauge", "amber_ladder", "brass_thimble", "cedar_ember", "cinder_cove",
    "copper_kite", "harbor_lantern", "iguana_necktie", "juniper_tide", "nimbus_quill", "tangelo", "wattle_ember",
})

_TYPES = (("null", type(None)), ("boolean", bool), ("number", (int, float)), ("string", str),
          ("list", list), ("object", dict))  # bool 是 int 的子類別，所以排在 number 前面
_ABSENT = object()


def check_schema(text: str) -> Union[SchemaCheck, TransientlyUnreadable, NoReading]:
    """架設者檢查指令用：逐一驗證本工具依賴的欄位。只回報型別，不帶出任何欄位的值。"""
    try:
        raw = json.loads(text)
    except ValueError:
        return TransientlyUnreadable()
    if not isinstance(raw, dict) or "cachedUsageUtilization" not in raw:
        return NoReading()
    fields = tuple(_check_field(raw, *spec) for spec in DEPENDED_FIELDS)
    usage = _values(raw, _USAGE)[0]
    usage = usage[0] if usage and isinstance(usage[0], dict) else {}
    new = tuple((name, _is_limit_field(value)) for name, value in usage.items()
                    if name not in OBSERVED_USAGE_FIELDS)
    parses = not isinstance(parse_cache(raw["cachedUsageUtilization"]), SchemaMismatch)
    return SchemaCheck(fields, new, parses)


def _check_field(raw: dict, path: str, expected: str, required: bool) -> FieldCheck:
    """必要欄位為 null 算型別不符；可選欄位為 null 與不存在相同。"""
    values, parent_absent = _values(raw, path)
    if values is None:
        return FieldCheck(path, expected, required, FieldStatus.UNREACHABLE)
    if not values:
        return FieldCheck(path, expected, required,
                          FieldStatus.PARENT_ABSENT if parent_absent else FieldStatus.NO_ITEMS)
    present = [v for v in values if v is not _ABSENT and (required or v is not None)]
    wrong = next((_type_name(v) for v in present if _type_name(v) != expected), None)
    if wrong:
        return FieldCheck(path, expected, required, FieldStatus.WRONG_TYPE, wrong)
    if len(present) < len(values) and required:
        return FieldCheck(path, expected, required, FieldStatus.MISSING)
    return FieldCheck(path, expected, required, FieldStatus.OK if present else FieldStatus.ABSENT)


def _values(raw: dict, path: str) -> Tuple[Optional[list], bool]:
    """路徑上的所有值（不存在的以 _ABSENT 表示），以及是否有上層不存在或為 null 而略過。
    途中的上層型別不符（不是物件，或 [] 那層不是清單）時，值為 None。"""
    nodes, parent_absent = [raw], False
    parts = path.split(".")
    for depth, part in enumerate(parts):
        name, each = (part[:-2], True) if part.endswith("[]") else (part, False)
        found = []
        for node in nodes:
            if depth and (node is _ABSENT or node is None):
                parent_absent = True
                continue
            if not isinstance(node, dict):
                return None, parent_absent
            value = node.get(name, _ABSENT)
            if each and not isinstance(value, list):
                if value is _ABSENT or value is None:
                    parent_absent = True
                    continue
                return None, parent_absent
            found.extend(value if each else [value])
        nodes = found
    return nodes, parent_absent


def _type_name(value) -> str:
    return next(name for name, kind in _TYPES if isinstance(value, kind))


def read_settings(fields: dict) -> Tuple[ProviderSettings, Tuple[str, ...]]:
    """fields 是整份設定檔。回傳 providers.claude 的設定，以及值不合法的欄位名稱（路徑式，如 providers.claude.warningPercent；
    缺少的欄位不算，寫了 null 算）。個別欄位不合法就用預設；兩個門檻不是由小到大時兩個都用預設，兩個都算不合法。"""
    prefix = f"{_SETTINGS_ROOT}.{PROVIDER}"
    if _SETTINGS_ROOT in fields and not isinstance(fields[_SETTINGS_ROOT], dict):
        return _DEFAULT, (_SETTINGS_ROOT,)
    providers = fields.get(_SETTINGS_ROOT, {})
    if PROVIDER in providers and not isinstance(providers[PROVIDER], dict):
        return _DEFAULT, (prefix,)
    claude = providers.get(PROVIDER, {})
    values = {name: _whole(claude.get(name), low, high) for name, low, high in _FIELD_RANGES}
    invalid = {name for name, value in values.items() if name in claude and value is None}
    days = values["expiryWarningDays"] or _DEFAULT.expiry_warning_days
    warning = values["warningPercent"] or _DEFAULT.warning_percent
    critical = values["criticalPercent"] or _DEFAULT.critical_percent
    if warning >= critical:
        warning, critical = _DEFAULT.warning_percent, _DEFAULT.critical_percent
        invalid |= {"warningPercent", "criticalPercent"}
    command = claude.get(CLAUDE_COMMAND_FIELD)
    command_invalid = command is not None and not (isinstance(command, str) and Path(command).is_absolute())
    if command_invalid:
        invalid.add(CLAUDE_COMMAND_FIELD)
    return (ProviderSettings(days, warning, critical, None if command_invalid or command is None else Path(command),
                             command_invalid),
            tuple(sorted(f"{prefix}.{name}" for name in invalid)))


def grade(severity: Optional[Severity], percent: Optional[int], settings: ProviderSettings) -> Severity:
    """供應商給了嚴重度就以它為準；沒給才以百分比門檻推定。每輪以設定檔目前的門檻重算。"""
    if severity is not None:
        return severity
    if percent is None or percent < settings.warning_percent:
        return Severity.NORMAL
    return Severity.WARNING if percent < settings.critical_percent else Severity.CRITICAL


def transcripts_modified_after(transcripts: Path, since: float) -> bool:
    """<專案>/<對話>.jsonl 有沒有任何一份在 since 之後修改過。找到一份就停；
    只逐項 stat、不留清單，對話紀錄再多，記憶體也不隨之增加。讀不到的目錄當成沒有活動。"""
    try:
        projects = os.scandir(transcripts)
    except OSError:
        return False
    with projects:
        for project in projects:
            try:
                if not project.is_dir():
                    continue
                with os.scandir(project.path) as sessions:
                    if any(s.name.endswith(".jsonl") and s.is_file() and s.stat().st_mtime > since
                           for s in sessions):
                        return True
            except OSError:
                continue
    return False


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
