"""核心：接收 home 目錄與時鐘，對外只有 poll、add、remove。"""
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, FrozenSet, Optional, Tuple

from . import atomic
from . import claude_provider as provider
from .board import Board, Card, Limit, ReadingState, Role, Severity
from .credstore import FileCredentialStore
from .permissions import is_private, make_private

MANAGED_DIR = ".claude-multi"  # 本工具自己的狀態目錄；憑證快照直接放在這一層
STATE_DIR = ".state"  # 納管目錄底下放工具狀態的子目錄，與憑證快照分開
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_ILLEGAL_IN_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                   *(f"LPT{i}" for i in range(1, 10))}
SCHEMA_CHANGE_ROUNDS = 3  # 結構不符連續這麼多輪才判定為結構變更；偶發一次不亮橫幅


class AddWarning(Enum):
    PERMISSIONS_FIXED = "permissions_fixed"  # 納管目錄或檔案的權限原本不符（他人可存取或靠繼承），已修正
    LABEL_LOOKS_LIKE_EMAIL = "label_looks_like_email"  # 帳號標籤會顯示在畫面上
    NOT_BOUND = "not_bound"  # 讀不到目前登入帳號的識別碼，憑證快照暫時沒有綁定


@dataclass(frozen=True)
class AddResult:
    account_key: str
    warnings: FrozenSet[AddWarning] = frozenset()


class InvalidLabel(ValueError):
    """帳號標籤就是憑證快照的檔名，必須是單純、合法的檔名。"""


class NoCredential(Exception):
    """讀不到目前登入的憑證（尚未登入、或憑證檔讀不懂），無法納管。"""


class UnknownLabel(LookupError):
    """沒有這個帳號標籤的憑證快照。"""


class Core:
    def __init__(self, home: Path, clock: Callable[[], datetime]):
        self._source = Path(home) / ".claude.json"
        self._credentials = Path(home) / provider.CREDENTIALS
        self._managed_dir = Path(home) / MANAGED_DIR
        self._bindings = self._managed_dir / STATE_DIR / "bindings.json"
        self._clock = clock
        self._mtime: Optional[int] = None
        self._reading: Optional[provider.UsageReading] = None
        self._result: provider.ParseResult = provider.NoReading()
        self._mismatch_rounds = 0

    def poll(self) -> Board:
        self._refresh()
        reading = self._reading
        return Board(cards=(self._active_card(),),
                     schema_changed=self._mismatch_rounds >= SCHEMA_CHANGE_ROUNDS,
                     last_reading_at=reading.observed_at if reading else None,
                     managed_accounts=tuple(f"{provider.PROVIDER}:{label}" for label in self._labels()))

    def add(self, label: str) -> AddResult:
        _check_label(label)
        try:
            data = self._credentials.read_bytes()
        except OSError:
            raise NoCredential() from None
        try:
            uuid = provider.account_uuid(self._source.read_text(encoding="utf-8"))
        except OSError:
            uuid = None
        fixed = self._mkdir_private(self._managed_dir)
        key = self._write_snapshot(self._snapshot(label), data)
        bindings = self._read_bindings()
        if uuid:
            bindings[key] = {"accountUuid": uuid}
        # 讀不到識別碼：同一身分鍵原有的綁定仍然有效；沒有的話留給之後補學
        self._write_bindings(bindings)
        # 事後驗證：連同既有的憑證快照一起檢查，不符就修正並告警
        checked = [self._bindings.parent, self._bindings] + [self._snapshot(l) for l in self._labels()]
        fixed = any([_tighten(p) for p in checked]) or fixed
        warnings = {AddWarning.PERMISSIONS_FIXED} if fixed else set()
        if key not in bindings:
            warnings.add(AddWarning.NOT_BOUND)
        if _EMAIL.search(label):
            warnings.add(AddWarning.LABEL_LOOKS_LIKE_EMAIL)
        return AddResult(f"{provider.PROVIDER}:{label}", frozenset(warnings))

    def remove(self, label: str) -> None:
        if label not in self._labels():
            raise UnknownLabel(label)
        atomic.remove(self._snapshot(label))
        self._write_bindings(self._read_bindings())

    def _write_snapshot(self, snapshot: Path, data: bytes) -> str:
        """替換前先驗證暫存檔讀得出身分鍵：讀到寫到一半的憑證時，既有的憑證快照維持原樣。"""
        keys = []

        def check(tmp: Path) -> None:
            key = FileCredentialStore(tmp).identity_key()
            if key is None:
                raise NoCredential()
            _tighten(tmp, new=True)
            keys.append(key)
        atomic.write_atomic(snapshot, data, before_replace=check)
        return keys[0]

    def _read_bindings(self) -> dict:
        try:
            bindings = json.loads(self._bindings.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return bindings if isinstance(bindings, dict) else {}

    def _write_bindings(self, bindings: dict) -> None:
        """綁定以身分鍵為鍵；只留還有憑證快照對應的身分鍵，重新納管換掉的舊身分鍵一併清掉。"""
        live = {FileCredentialStore(self._snapshot(label)).identity_key() for label in self._labels()}
        self._mkdir_private(self._bindings.parent)
        data = json.dumps({k: v for k, v in bindings.items() if k in live}, indent=2)
        atomic.write_atomic(self._bindings, data.encode("utf-8"), before_replace=lambda tmp: _tighten(tmp, new=True))

    @staticmethod
    def _mkdir_private(path: Path) -> bool:
        """先收緊目錄再往裡面寫，檔案一建立就不會外露。回傳是否修正了既有目錄的權限。"""
        new = not path.exists()
        path.mkdir(exist_ok=True)
        return _tighten(path, new)

    def _snapshot(self, label: str) -> Path:
        return self._managed_dir / f"{label}.json"

    def _labels(self) -> Tuple[str, ...]:
        """帳號標籤就是憑證快照的檔名去掉 .json；點開頭的是工具自己的檔案。"""
        if not self._managed_dir.is_dir():
            return ()
        return tuple(sorted(p.stem for p in self._managed_dir.glob("*.json")
                            if p.is_file() and not p.name.startswith(".")))

    def _refresh(self) -> None:
        result = self._read()
        if isinstance(result, provider.UsageReading):
            self._reading, self._mismatch_rounds = result, 0
        elif isinstance(result, provider.NoReading):
            self._reading, self._mismatch_rounds = None, 0
        elif isinstance(result, provider.SchemaMismatch):
            self._mismatch_rounds += 1
        # 暫時不可讀、偶發讀取失敗：沿用上一次的值，也不動結構不符的累計

    def _read(self) -> Optional[provider.ParseResult]:
        """來源檔案沒變時不重新解析，沿用上一次的解析結果，結構判定仍算一輪。
        偶發讀取失敗回傳 None，下一輪重試。"""
        try:
            mtime = os.stat(self._source).st_mtime_ns
        except FileNotFoundError:
            self._mtime, self._result = None, provider.NoReading()
            return self._result
        except OSError:
            return None
        if mtime != self._mtime:
            try:
                text = self._source.read_text(encoding="utf-8")
            except OSError:
                return None
            self._result = provider.parse(text)
            # 暫時不可讀不記修改時間：寫入中的檔案可能在同一個時間刻度內寫完，下一輪要重讀
            transient = isinstance(self._result, provider.TransientlyUnreadable)
            self._mtime = None if transient else mtime
        return self._result

    def _active_card(self) -> Card:
        reading = self._reading
        if reading is None:
            return Card(None, Role.ACTIVE, ReadingState.NO_READING)
        now = self._clock()
        breakdown = reading.weekly_breakdown
        if breakdown and breakdown.ends_at and not _counting(breakdown.ends_at, now):
            breakdown = None  # 週窗口已重置，舊的用量去向不再屬於計時中的這一週
        return Card(
            None, Role.ACTIVE, ReadingState.HAS_READING,
            reading_age=now - reading.observed_at,
            limits=_as_of(reading.limits, now),
            scoped_limits=_as_of(reading.scoped_limits, now),
            other_limits=_as_of(reading.other_limits, now),
            locked_reason=reading.locked_reason,
            weekly_breakdown=breakdown,
            extra_usage=reading.extra_usage,
            spend=reading.spend,
        )


def _check_label(label: str) -> None:
    """標籤會直接成為納管目錄裡的檔名：擋掉路徑、Windows 不接受的檔名，以及點開頭（留給工具自己的檔案）。"""
    if (not label.strip() or label.startswith(".") or label.endswith((".", " "))
            or _ILLEGAL_IN_NAME.search(label) or label.split(".")[0].upper() in _RESERVED_NAMES):
        raise InvalidLabel(label)


def _tighten(path: Path, new: bool = False) -> bool:
    """收緊到只有目前使用者能存取。回傳是否修正了原本外露的權限；剛建立的不算。修正後仍不符就丟例外。"""
    if is_private(path):
        return False
    make_private(path)
    if not is_private(path):
        raise PermissionError(f"無法把權限收緊到只有目前使用者：{path.name}")
    return not new


def _counting(resets_at: Optional[datetime], now: datetime) -> bool:
    return resets_at is not None and now < resets_at


def _as_of(limits: Tuple[Limit, ...], now: datetime) -> Tuple[Limit, ...]:
    """沒有重置時間或已過重置時間：無計時中窗口，重置時間未知，不推算下一次。
    週窗口固定 7 天，過了重置時間代表新的一週已開始，標為已重置。"""
    return tuple(
        lim if _counting(lim.resets_at, now)
        else replace(lim, percent=None, resets_at=None, severity=Severity.NORMAL,
                     reset=lim.resets_at is not None and lim.kind == provider.WEEKLY_KIND)
        for lim in limits
    )
