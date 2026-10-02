"""設定檔與路徑解析（ADR-0008）：命令列與 GUI 啟動時都走這裡，取得同一組路徑。"""
import copy
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from . import atomic
from . import claude_provider
from .board import CountdownFormat, Preferences

MANAGED_DIR = ".claude-multi"  # 納管目錄的 home 預設
SETTINGS_DIR = "cc-quota-tracker"  # 在 %APPDATA% 底下；不放進納管目錄，因為納管目錄的位置寫在設定檔裡
SETTINGS_FILE = "settings.json"
CLAUDE_DIR_FIELD, MANAGED_DIR_FIELD = "claudeConfigDir", "managedDir"  # 設定檔裡的兩個路徑欄位
PROVIDERS_FIELD = "providers"  # 按供應商分開的設定：{"claude": {...}}，預設值由各供應商帶入
COUNTDOWN_FORMAT_FIELD = "countdownFormat"  # 倒數格式：twoUnits（天＋時）或 decimalDays（天數到小數第 1 位）
FONT_FIELD = "font"  # 字型家族名稱或 null（用內建字型）；只能在設定檔調整，不進 GUI 選單
CLAUDE_CONFIG_DIR = "CLAUDE_CONFIG_DIR"  # Claude Code 自己的環境變數；空字串當成沒設
# 第一次啟動時整份寫出：八項偏好與各供應商設定的預設值，加上兩個路徑欄位（null＝沒填）。欄位說明在 README，JSON 不能寫註解
DEFAULTS = {
    "layout": "cards", "alwaysOnTop": True, "mode": "compact",
    "language": "system", "theme": "system", "opacity": 100, "countdownFormat": "twoUnits",
    "font": None, "providers": {claude_provider.PROVIDER: claude_provider.SETTINGS_DEFAULTS},
    "claudeConfigDir": None, "managedDir": None,
}


# 設定檔的偏好欄位 → (Preferences 的屬性, 合法值)。第一個合法值不一定是預設；預設以 Preferences 為準
PREFERENCE_FIELDS = {
    "layout": ("layout", ("cards", "table", "ring")),  # cards：A 卡片列表、table：B 密集表格／單行條、ring：C 環形儀表
    "alwaysOnTop": ("always_on_top", (True, False)),
    "mode": ("mode", ("compact", "expanded")),
    "language": ("language", ("system", "zh-TW", "en")),
    "theme": ("theme", ("system", "light", "dark")),
    "opacity": ("opacity", (100, 85, 70)),
}
_COUNTDOWN_FORMATS = tuple(f.value for f in CountdownFormat)


class WriteResult(Enum):
    """GUI 改設定檔的結果。寫入階段的失敗不在這裡：照常丟 OSError，由呼叫端處理。"""
    WRITTEN = "written"
    UNREADABLE = "unreadable"  # 設定檔讀不到，或不是合法的 JSON 物件
    MALFORMED = "malformed"  # 設定檔讀得懂，但要改的那一層不是物件（providers 或 providers.<供應商>）


class PathSource(Enum):
    SETTINGS_FILE = "settings_file"
    ENV = "env"
    DEFAULT = "default"


class PathProblem(Enum):
    NOT_ABSOLUTE = "not_absolute"  # 含空字串與非字串；相對路徑跟著工作目錄走，開機自動啟動時會指到別處
    NOT_A_DIRECTORY = "not_a_directory"
    INSIDE_CLAUDE_DIR = "inside_claude_dir"  # 納管目錄在 Claude Code 目錄裡面：本工具永不寫入那裡


class InvalidPathSetting(ValueError):
    """設定檔的路徑欄位有填、但不能用。field 是設定檔裡的欄位名稱。"""

    def __init__(self, settings_file: Path, field: str, problem: PathProblem):
        super().__init__(field, problem)
        self.settings_file, self.field, self.problem = settings_file, field, problem


@dataclass(frozen=True)
class ResolvedPaths:
    """claude_dir 是當前憑證所在的 Claude Code 目錄；claude_json 是額度快取所在的檔案。
    path_fields：啟動時設定檔裡兩個路徑欄位的原值，執行中拿來比對是否需要重新啟動。
    settings_unreadable：設定檔不是合法的 JSON 物件，兩個路徑欄位都當成沒填。"""
    claude_dir: Path
    claude_json: Path
    claude_source: PathSource
    managed_dir: Path
    managed_source: PathSource
    settings_file: Path
    path_fields: Tuple[Any, Any]
    settings_unreadable: bool = False


def resolve_paths(home: Path, env: Mapping[str, str]) -> ResolvedPaths:
    """啟動時呼叫一次。設定檔還不存在就先寫出完整的預設設定檔；已存在的一律不覆寫。
    Claude Code 目錄：設定檔欄位 → CLAUDE_CONFIG_DIR → home 預設。納管目錄：設定檔欄位 → home 預設。"""
    home = Path(home)
    settings_file = Path(env.get("APPDATA") or home / "AppData" / "Roaming") / SETTINGS_DIR / SETTINGS_FILE
    if not settings_file.exists():
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_atomic(settings_file, json.dumps(DEFAULTS, indent=2).encode("utf-8"))
    fields = read_settings(settings_file)
    unreadable = fields is None
    fields = fields or {}
    configured = _dir_field(settings_file, fields, CLAUDE_DIR_FIELD)
    if configured is not None:
        claude = (configured, configured / ".claude.json", PathSource.SETTINGS_FILE)  # 語意與 CLAUDE_CONFIG_DIR 相同
    elif env.get(CLAUDE_CONFIG_DIR):
        # 設了這個變數，額度快取與當前憑證都在該目錄「裡面」（實測）；home 預設則是額度快取在 home、憑證在 ~/.claude
        claude_dir = Path(env[CLAUDE_CONFIG_DIR])
        claude = (claude_dir, claude_dir / ".claude.json", PathSource.ENV)
    else:
        claude = (home / ".claude", home / ".claude.json", PathSource.DEFAULT)
    configured = _dir_field(settings_file, fields, MANAGED_DIR_FIELD)
    managed = (configured, PathSource.SETTINGS_FILE) if configured is not None else (home / MANAGED_DIR, PathSource.DEFAULT)
    if _within(managed[0], claude[0]):
        raise InvalidPathSetting(settings_file, MANAGED_DIR_FIELD, PathProblem.INSIDE_CLAUDE_DIR)
    return ResolvedPaths(*claude, *managed, settings_file, path_fields(fields), settings_unreadable=unreadable)


def path_fields(fields: dict) -> Tuple[Any, Any]:
    return fields.get(CLAUDE_DIR_FIELD), fields.get(MANAGED_DIR_FIELD)


def _within(path: Path, directory: Path) -> bool:
    path, directory = (Path(os.path.normcase(p.resolve())) for p in (path, directory))
    return path == directory or directory in path.parents


def read_settings(settings_file: Path) -> Optional[dict]:
    """None：設定檔讀不到，或不是合法的 JSON 物件。讀不懂的檔案不覆寫，等使用者修好。"""
    try:
        fields = json.loads(settings_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return fields if isinstance(fields, dict) else None


def read_preferences(fields: dict) -> Tuple[Preferences, Tuple[str, ...]]:
    """回傳偏好，以及值不合法的欄位名稱（含倒數格式、字型）。缺少的欄位用預設、不算不合法；不合法的只那一欄用預設。"""
    values, invalid = {}, []
    for field, (attr, allowed) in PREFERENCE_FIELDS.items():
        if field in fields:
            if _allowed(fields[field], allowed):
                values[attr] = fields[field]
            else:
                invalid.append(field)
    if COUNTDOWN_FORMAT_FIELD in fields and not _allowed(fields[COUNTDOWN_FORMAT_FIELD], _COUNTDOWN_FORMATS):
        invalid.append(COUNTDOWN_FORMAT_FIELD)
    if FONT_FIELD in fields:
        if fields[FONT_FIELD] is None or isinstance(fields[FONT_FIELD], str):
            values["font"] = fields[FONT_FIELD]
        else:
            invalid.append(FONT_FIELD)
    return Preferences(**values), tuple(sorted(invalid))


def _allowed(value, allowed: tuple) -> bool:
    # 型別也要相同：JSON 的 true 等於 1、100.0 等於 100，只比值會放過型別不對的值
    return any(type(value) is type(a) and value == a for a in allowed)


def write_preference(settings_file: Path, field: str, value) -> bool:
    """GUI 改一項偏好：先重讀設定檔、只改那一欄，再原子寫入，不蓋掉使用者剛手改的內容。
    設定檔不是合法的 JSON 物件時不寫，回傳 False，改動只在記憶體生效；設定檔不見了就以預設值重建。"""
    def change(fields: dict) -> bool:
        fields[field] = value
        return True
    return _rewrite(settings_file, change) is WriteResult.WRITTEN


def write_provider_setting(settings_file: Path, provider: str, field: str, value) -> WriteResult:
    """GUI 改一項供應商設定（providers.<provider>.<field>），規則同 write_preference。
    providers 或該供應商的設定寫成了不是物件的值時也不寫（MALFORMED）：那是使用者填錯的內容，不替他蓋掉；
    讀不懂的設定檔同樣不寫（UNREADABLE）。兩者要讓使用者分得出來，所以不像 write_preference 只回傳布林。"""
    def change(fields: dict) -> bool:
        providers = fields.setdefault(PROVIDERS_FIELD, {})
        if not isinstance(providers, dict) or not isinstance(providers.setdefault(provider, {}), dict):
            return False
        providers[provider][field] = value
        return True
    return _rewrite(settings_file, change)


def _rewrite(settings_file: Path, change) -> WriteResult:
    if settings_file.exists():
        fields = read_settings(settings_file)
        if fields is None:
            return WriteResult.UNREADABLE
    else:
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        fields = copy.deepcopy(DEFAULTS)  # 改動不能漏回模組層級的預設值
    if not change(fields):
        return WriteResult.MALFORMED
    atomic.write_atomic(settings_file, json.dumps(fields, indent=2, ensure_ascii=False).encode("utf-8"))
    return WriteResult.WRITTEN


def _dir_field(settings_file: Path, fields: dict, field: str) -> Optional[Path]:
    """缺少或為 null：沒填，交給下一層。有填就必須是存在目錄的絕對路徑，否則報錯，不回退。"""
    value = fields.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise InvalidPathSetting(settings_file, field, PathProblem.NOT_ABSOLUTE)
    if not Path(value).is_dir():
        raise InvalidPathSetting(settings_file, field, PathProblem.NOT_A_DIRECTORY)
    return Path(value)
