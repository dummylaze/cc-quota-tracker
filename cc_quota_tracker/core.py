"""核心：接收解析後的路徑與時鐘，對外只有 poll、add、remove。"""
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable, FrozenSet, NamedTuple, Optional, Set, Tuple

from . import atomic
from . import claude_provider as provider
from .board import Board, Card, CountdownFormat, Limit, ReadingState, Role, Severity
from .credstore import FileCredentialStore
from .permissions import is_private, make_private
from .settings import COUNTDOWN_FORMAT_FIELD, PROVIDERS_FIELD, PathSource, ResolvedPaths, path_fields, read_settings

STATE_DIR = ".state"  # 納管目錄底下放工具狀態的子目錄，與憑證快照分開
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_ILLEGAL_IN_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                   *(f"LPT{i}" for i in range(1, 10))}
SCHEMA_CHANGE_ROUNDS = 3  # 結構不符連續這麼多輪才判定為結構變更；偶發一次不亮橫幅
# 沒落後時多久重掃一次對話紀錄：落後提示最多晚這麼久出現，換來不必每輪 poll 都 stat 所有對話紀錄
LAG_SCAN_INTERVAL = timedelta(seconds=60)


class _LagScan(NamedTuple):
    """上一次掃描對話紀錄：比對的是哪個觀測時間、何時掃的、結果是否落後。"""
    observed_at: datetime
    scanned_at: datetime
    lagging: bool


class AddWarning(Enum):
    PERMISSIONS_FIXED = "permissions_fixed"  # 納管目錄或檔案的權限原本不符（他人可存取或靠繼承），已修正
    LABEL_LOOKS_LIKE_EMAIL = "label_looks_like_email"  # 帳號標籤會顯示在畫面上
    NOT_BOUND = "not_bound"  # 讀不到目前登入帳號的識別碼，憑證快照暫時沒有綁定


@dataclass(frozen=True)
class _Account:
    """納管帳號：帳號鍵、憑證快照的憑證指紋、綁定的帳號識別碼（沒有綁定為 None）、refreshToken 的到期時間。"""
    key: str
    fingerprint: Optional[str]
    account_id: Optional[str]
    expires_at: Optional[datetime] = None


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
    def __init__(self, paths: ResolvedPaths, clock: Callable[[], datetime]):
        self._source = paths.claude_json
        self._credentials = paths.claude_dir / provider.CREDENTIALS
        self._transcripts = paths.claude_dir / provider.TRANSCRIPTS
        self._lag_scan: Optional[_LagScan] = None
        self._managed_dir = paths.managed_dir  # 憑證快照直接放在這一層
        self._paths = paths
        self._source_missing = False
        self._settings_mtime: Optional[int] = None
        self._path_fields = paths.path_fields  # 設定檔目前寫的路徑欄位；與啟動時不同就要重新啟動
        self._settings_unreadable = False  # 第一輪 poll 就會重讀設定檔
        self._countdown_format = CountdownFormat.TWO_UNITS
        self._provider_settings = provider.ProviderSettings()  # 設定檔的 providers.claude
        self._bindings = self._managed_dir / STATE_DIR / "bindings.json"
        self._readings_file = self._managed_dir / STATE_DIR / "readings.json"
        self._switch_log = self._managed_dir / STATE_DIR / "switches.jsonl"
        self._observed = self._managed_dir / STATE_DIR / "observed.json"  # 最後運作時間與上一輪的觀測
        self._readings: Optional[dict] = None  # 帳號識別碼 → 最後一次歸屬給它的讀數；第一次用到才讀檔
        self._oauth_account_id: Optional[str] = None  # 目前登入帳號的識別碼（oauthAccount），未納管帳號靠它歸屬讀數
        self._clock = clock
        self._mtime: Optional[int] = None
        self._reading: Optional[provider.UsageReading] = None
        self._result: provider.ParseResult = provider.NoReading()
        self._mismatch_rounds = 0

    def poll(self) -> Board:
        self._refresh()
        self._reread_settings()
        accounts = self._maintain_bindings(self._accounts())
        self._remember(accounts)
        active, invalid = self._observe(accounts)
        reading = self._reading
        return Board(cards=self._cards(accounts, active, invalid),
                     schema_changed=self._mismatch_rounds >= SCHEMA_CHANGE_ROUNDS,
                     last_reading_at=reading.observed_at if reading else None,
                     managed_accounts=tuple(a.key for a in accounts),
                     wrong_location_suspected=self._source_missing and self._paths.claude_source is PathSource.DEFAULT,
                     restart_required=self._path_fields != self._paths.path_fields,
                     settings_unreadable=self._settings_unreadable,
                     as_of=self._clock(), countdown_format=self._countdown_format)

    def add(self, label: str) -> AddResult:
        _check_label(label)
        try:
            data = self._credentials.read_bytes()
        except OSError:
            raise NoCredential() from None
        try:
            account_id = provider.account_id(self._source.read_text(encoding="utf-8"))
        except OSError:
            account_id = None
        fixed = self._mkdir_private(self._managed_dir)
        key = self._write_snapshot(self._snapshot(label), data)
        bindings = self._read_bindings()
        if account_id:
            bindings[key] = {"accountId": account_id}
        # 讀不到識別碼：同一憑證指紋原有的綁定仍然有效；沒有的話留給之後補學
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
        """替換前先驗證暫存檔讀得出憑證指紋：讀到寫到一半的憑證時，既有的憑證快照維持原樣。"""
        keys = []

        def check(tmp: Path) -> None:
            key = FileCredentialStore(tmp).fingerprint()
            if key is None:
                raise NoCredential()
            _tighten(tmp, new=True)
            keys.append(key)
        atomic.write_atomic(snapshot, data, before_replace=check)
        return keys[0]

    def _read_bindings(self) -> dict:
        return self._load_bindings() or {}

    def _load_bindings(self) -> Optional[dict]:
        """讀不到（例如防毒短暫鎖住）回傳 None，不同於沒有或讀不懂的空綁定：後者才可以放心寫回。"""
        try:
            bindings = json.loads(self._bindings.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except OSError:
            return None
        except ValueError:
            return {}
        return bindings if isinstance(bindings, dict) else {}

    def _write_bindings(self, bindings: dict) -> None:
        """綁定以憑證指紋為鍵；只留還有憑證快照對應的憑證指紋，重新納管換掉的舊憑證指紋一併清掉。"""
        live = {FileCredentialStore(self._snapshot(label)).fingerprint() for label in self._labels()}
        kept = {k: v for k, v in bindings.items() if k in live}
        self._write_state(self._bindings, kept)
        stored = self._load_readings()
        bound = {v.get("accountId") for v in kept.values() if isinstance(v, dict)}
        if stored is not None and set(stored) - bound:  # 移除的帳號，它的讀數一併清掉
            self._write_readings(stored, bound)

    def _accounts(self) -> Tuple[_Account, ...]:
        bindings = self._read_bindings()
        accounts = []
        for label in self._labels():
            snapshot = FileCredentialStore(self._snapshot(label))
            fingerprint, credential = snapshot.fingerprint(), snapshot.read()
            bound = bindings.get(fingerprint) if fingerprint else None
            account_id = bound.get("accountId") if isinstance(bound, dict) else None
            accounts.append(_Account(f"{provider.PROVIDER}:{label}", fingerprint,
                                     account_id if isinstance(account_id, str) and account_id else None,
                                     credential.refresh_token_expires_at if credential else None))
        return tuple(accounts)

    def _maintain_bindings(self, accounts: Tuple[_Account, ...]) -> Tuple[_Account, ...]:
        """不經過 add 的綁定維護：直接放進目錄的憑證快照補學綁定，快照被刪掉的孤兒綁定清掉。
        綁定檔讀不到、有憑證快照讀不出憑證指紋（寫到一半、被鎖住）、或寫不成時，這一輪什麼都不動：
        寫綁定會依現有的憑證指紋過濾，讀不出來的那份快照的綁定會被一起洗掉。"""
        bindings = self._load_bindings()
        if bindings is None or not all(a.fingerprint for a in accounts):
            return accounts
        target = self._snapshot_to_bind(accounts)
        has_orphans = bool(set(bindings) - {a.fingerprint for a in accounts})
        if target is None and not has_orphans:
            return accounts
        if target:
            bindings[target.fingerprint] = {"accountId": self._oauth_account_id}
        try:
            self._write_bindings(bindings)
        except OSError:
            return accounts
        return self._accounts()

    def _snapshot_to_bind(self, accounts: Tuple[_Account, ...]) -> Optional[_Account]:
        """要補學綁定的憑證快照，沒有就是 None。這份快照本身還沒有綁定，而且三個條件同時成立才補學，缺一就不猜：
        它是使用中帳號、額度快取的識別碼等於 oauthAccount 的識別碼、該識別碼還沒綁給其他帳號。"""
        reading, account_id = self._reading, self._oauth_account_id
        if reading is None or account_id is None or reading.account_id != account_id:
            return None
        if any(a.account_id == account_id for a in accounts):
            return None
        current = FileCredentialStore(self._credentials).fingerprint()
        return next((a for a in accounts if a.fingerprint == current and a.account_id is None), None)

    def _remember(self, accounts: Tuple[_Account, ...]) -> None:
        """額度快取的讀數歸屬到某個納管帳號時存進工具狀態：它換成待命帳號、甚至重新啟動後仍看得到。
        只留還有綁定的帳號；有變化才寫檔。"""
        reading, stored = self._reading, self._load_readings()
        bound = {a.account_id for a in accounts if a.account_id}
        if reading is None or stored is None or reading.account_id not in bound:
            return
        if stored.get(reading.account_id) == reading:
            return
        stored[reading.account_id] = reading
        self._write_readings(stored, bound)

    def _load_readings(self) -> Optional[dict]:
        """讀不到（例如防毒短暫鎖住）回傳 None，下一輪再讀；內容讀不懂就當成沒有。"""
        if self._readings is None:
            try:
                raw = json.loads(self._readings_file.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raw = {}
            except OSError:
                return None
            except ValueError:
                raw = {}
            parsed = {k: provider.parse_cache(cache) for k, cache in raw.items()} if isinstance(raw, dict) else {}
            self._readings = {k: r for k, r in parsed.items() if isinstance(r, provider.UsageReading)}
        return self._readings

    def _write_readings(self, readings: dict, bound: Set[str]) -> None:
        """只留 bound 裡的帳號識別碼；存的是 cachedUsageUtilization 原文，讀回來時再解析。"""
        self._readings = {k: r for k, r in readings.items() if k in bound}
        self._write_state(self._readings_file, {k: r.source for k, r in self._readings.items()})

    def _observe(self, accounts: Tuple[_Account, ...]) -> Tuple[Optional[_Account], bool]:
        """每輪的切換偵測。回傳使用中的納管帳號（未納管為 None），以及它的憑證快照是否已失效。
        上一輪的憑證指紋與失效標記存在工具狀態，重新啟動後接著比對；第一次運作也算一次切換。
        讀不到當前憑證（寫到一半、登出）時不動：不記錄，也不覆蓋上一輪的憑證指紋。"""
        current = FileCredentialStore(self._credentials).fingerprint()
        by_fp = {a.fingerprint: a for a in accounts if a.fingerprint}
        state = self._read_observed()
        if state is None:  # 讀不到上一輪的觀測（例如短暫鎖住）：這一輪不判定
            return by_fp.get(current), False
        previous, invalid_snapshot = _text(state.get("fingerprint")), _text(state.get("invalidSnapshot"))
        switched, account_id = False, None
        if current is not None and current != previous:
            previous_account = by_fp.get(previous) or by_fp.get(invalid_snapshot)  # 前一個使用中的納管帳號
            if current in by_fp:
                switched, account_id = True, by_fp[current].account_id
            elif previous_account and previous_account.account_id \
                    and self._oauth_account_id == previous_account.account_id:
                invalid_snapshot = previous_account.fingerprint  # 憑證被輪替：同一個帳號，不算切換（ADR-0002）
            else:
                switched, account_id = True, self._oauth_account_id
        elif current is not None and invalid_snapshot:
            flagged = by_fp.get(invalid_snapshot)
            if flagged is None:  # 憑證快照已移除或重新納管
                invalid_snapshot = None
            elif self._oauth_account_id not in (None, flagged.account_id):
                # Claude Code 先寫憑證、後寫 oauthAccount：上一輪看起來像輪替，其實是切到未納管帳號
                switched, account_id = True, self._oauth_account_id
        if switched or current in by_fp:
            invalid_snapshot = None
        try:
            if switched:
                self._append_switch(account_id)
            # 紀錄寫成、這裡寫失敗時，下一輪會再記一次同一個帳號；重複的一行不影響歸屬
            self._write_state(self._observed, {"lastRunAt": self._clock().isoformat(),
                                               "fingerprint": current or previous, "invalidSnapshot": invalid_snapshot})
        except OSError:
            pass  # 不推進上一輪的觀測，下一輪重試
        if current in by_fp:
            return by_fp[current], False
        flagged = by_fp.get(invalid_snapshot) if current is not None and invalid_snapshot else None
        return flagged, flagged is not None

    def _read_observed(self) -> Optional[dict]:
        """讀不到回傳 None；不存在或讀不懂就當成沒有上一輪。"""
        try:
            state = json.loads(self._observed.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except OSError:
            return None
        except ValueError:
            return {}
        return state if isinstance(state, dict) else {}

    def _append_switch(self, account_id: Optional[str]) -> None:
        """切換紀錄只追加：時間、切到的帳號識別碼（拿不到為 null）、來源。不記帳號鍵（ADR-0009）。"""
        self._mkdir_state_dir()
        line = json.dumps({"at": self._clock().isoformat(), "accountId": account_id, "source": "observed"})
        atomic.append(self._switch_log, (line + "\n").encode("utf-8"),
                      before_replace=lambda tmp: _tighten(tmp, new=True))

    def _write_state(self, path: Path, data: dict) -> None:
        """工具狀態一律原子寫入，暫存檔在替換前就收緊權限。"""
        self._mkdir_state_dir()
        atomic.write_atomic(path, json.dumps(data, indent=2).encode("utf-8"),
                            before_replace=lambda tmp: _tighten(tmp, new=True))

    def _mkdir_state_dir(self) -> None:
        """poll 在還沒納管任何帳號時也會寫工具狀態，納管目錄可能還不存在。"""
        self._mkdir_private(self._managed_dir)
        self._mkdir_private(self._managed_dir / STATE_DIR)

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

    def _reread_settings(self) -> None:
        """設定檔改了才重讀。讀不懂時不記修改時間，下一輪再讀；路徑欄位沿用上一次讀到的值。"""
        try:
            mtime = os.stat(self._paths.settings_file).st_mtime_ns
        except FileNotFoundError:
            self._settings_mtime, self._path_fields, self._settings_unreadable = None, (None, None), False
            self._countdown_format = CountdownFormat.TWO_UNITS
            self._provider_settings = provider.ProviderSettings()
            return
        except OSError:
            return
        if mtime == self._settings_mtime:
            return
        fields = read_settings(self._paths.settings_file)
        self._settings_unreadable = fields is None
        if fields is not None:
            self._settings_mtime, self._path_fields = mtime, path_fields(fields)
            self._countdown_format = _countdown_format(fields.get(COUNTDOWN_FORMAT_FIELD))
            self._provider_settings = provider.read_settings(fields.get(PROVIDERS_FIELD))

    def _read(self) -> Optional[provider.ParseResult]:
        """來源檔案沒變時不重新解析，沿用上一次的解析結果，結構判定仍算一輪。
        偶發讀取失敗回傳 None，下一輪重試。"""
        try:
            mtime = os.stat(self._source).st_mtime_ns
        except FileNotFoundError:
            self._mtime, self._result, self._source_missing = None, provider.NoReading(), True
            self._oauth_account_id = None
            return self._result
        except OSError:
            return None
        self._source_missing = False
        if mtime != self._mtime:
            try:
                text = self._source.read_text(encoding="utf-8")
            except OSError:
                return None
            self._result = provider.parse(text)
            # 暫時不可讀不記修改時間：寫入中的檔案可能在同一個時間刻度內寫完，下一輪要重讀
            transient = isinstance(self._result, provider.TransientlyUnreadable)
            self._mtime = None if transient else mtime
            if not transient:
                self._oauth_account_id = provider.account_id(text)
        return self._result

    def _cards(self, accounts: Tuple[_Account, ...], active: Optional[_Account], invalid: bool) -> Tuple[Card, ...]:
        """使用中帳號在最前面，其餘納管帳號是待命帳號，依帳號鍵排序。
        active 為 None：當前憑證對不上任何憑證快照，使用中帳號是未納管帳號。"""
        if active:
            first = replace(self._active_card(active.key, Role.ACTIVE, active.account_id), snapshot_invalid=invalid)
        else:
            first = self._active_card(None, Role.UNMANAGED, self._oauth_account_id)
        return (self._with_expiry(first, active),
                *(self._with_expiry(self._standby_card(a), a) for a in accounts if a is not active))

    def _with_expiry(self, card: Card, account: Optional[_Account]) -> Card:
        """剩不到設定的天數（預設 7 天）才警示：畫面的倒數一律捨去，門檻 7 天時顯示「7天0小時」不警示、
        「6天23小時」起才警示。每輪以當下時間與設定檔目前的值重算。"""
        if account is None or account.expires_at is None:
            return card
        warning = timedelta(days=self._provider_settings.expiry_warning_days)
        return replace(card, snapshot_expires_at=account.expires_at,
                       snapshot_expiring=account.expires_at - self._clock() < warning)

    def _active_card(self, key: Optional[str], role: Role, owner: Optional[str]) -> Card:
        """額度快取的識別碼等於 owner 才歸屬；否則是別的帳號的讀數（例如剛切換），讀數待更新。"""
        reading = self._reading
        if reading is None:
            return Card(key, role, ReadingState.NO_READING)
        if owner is None or reading.account_id != owner:
            return Card(key, role, ReadingState.PENDING)
        return self._reading_card(key, role, reading)

    def _standby_card(self, account: _Account) -> Card:
        stored = self._load_readings() or {}
        reading = stored.get(account.account_id) if account.account_id else None
        if reading is None:
            return Card(account.key, Role.STANDBY, ReadingState.NO_READING)
        return self._reading_card(account.key, Role.STANDBY, reading)

    def _reading_card(self, key: Optional[str], role: Role, reading: provider.UsageReading) -> Card:
        now = self._clock()
        breakdown = reading.weekly_breakdown
        if breakdown and breakdown.ends_at and not _counting(breakdown.ends_at, now):
            breakdown = None  # 週窗口已重置，舊的用量去向不再屬於計時中的這一週
        return Card(
            key, role, ReadingState.HAS_READING,
            reading_age=now - reading.observed_at,
            lagging=role is not Role.STANDBY and self._lagging(reading),
            limits=_as_of(self._graded(reading.limits), now),
            scoped_limits=_as_of(self._graded(reading.scoped_limits), now),
            other_limits=_as_of(self._graded(reading.other_limits), now),
            locked_reason=reading.locked_reason,
            weekly_breakdown=breakdown,
            extra_usage=reading.extra_usage,
            spend=reading.spend and replace(reading.spend, severity=self._grade(reading.spend.severity,
                                                                                 reading.spend.percent)),
        )

    def _lagging(self, reading: provider.UsageReading) -> bool:
        """落後讀數：觀測時間之後，本機有對話紀錄被修改。已判為落後就維持到下一個讀數；
        沒落後時每 LAG_SCAN_INTERVAL 才重掃一次。讀數換了（觀測時間不同）立刻重掃。"""
        now, last = self._clock(), self._lag_scan
        if last and last.observed_at == reading.observed_at and (
                last.lagging or timedelta(0) <= now - last.scanned_at < LAG_SCAN_INTERVAL):  # 時鐘往回撥也重掃
            return last.lagging
        lagging = provider.transcripts_modified_after(self._transcripts, reading.observed_at.timestamp())
        self._lag_scan = _LagScan(reading.observed_at, now, lagging)
        return lagging

    def _graded(self, limits: Tuple[Limit, ...]) -> Tuple[Limit, ...]:
        return tuple(replace(lim, severity=self._grade(lim.severity, lim.percent)) for lim in limits)

    def _grade(self, severity: Optional[Severity], percent: Optional[int]) -> Severity:
        return provider.grade(severity, percent, self._provider_settings)


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


def _countdown_format(value) -> CountdownFormat:
    """不認得的值用預設的「天＋時」。"""
    try:
        return CountdownFormat(value)
    except ValueError:
        return CountdownFormat.TWO_UNITS


def _text(value) -> Optional[str]:
    return value if isinstance(value, str) and value else None


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
