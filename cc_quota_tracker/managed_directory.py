"""納管目錄：本工具保管的資料都放在這裡，核心與視窗只透過它存取，不直接碰檔案。

對外是領域操作，不是檔案。以下規則在這個 module 裡強制執行，呼叫端不必、也無法繞過：
- 三態讀取：不存在與讀不懂視為「沒有」，讀不到（作業系統層的讀取錯誤，例如被防毒鎖住）視為「未知」。
- 會修剪資料的寫入（綁定、連帶的待命讀數）：綁定檔讀不到、或有任何一份憑證快照讀不出憑證指紋，就不修剪。
- 一律原子寫入；暫存檔在替換前就收緊權限；目錄先收緊再往裡面寫。
- 切換紀錄只追加。
- 權限只有一套政策：收緊後事後驗證，仍不符（或收緊本身回報錯誤）就照常寫入，並記下「未收緊」讓呼叫端告警（ADR-0008）。

各檔案的寫入規則與失敗處理（全部在納管目錄底下）：
- <帳號標籤>.json，憑證快照：本工具在納管與憑證同步時寫入、移除時刪除（使用者也可能直接放檔進來）。替換前驗證讀得出憑證指紋，讀不出來就丟 NoCredential、
  既有的維持原樣。綁定檔讀不到時納管整個拒絕（BindingsUnreadable）、同步不寫（丟 OSError），移除照樣刪。
  同步寫回時先把綁定複製到新的憑證指紋再寫憑證快照：憑證快照寫不成時多出的那筆綁定由之後的維護清掉，舊憑證指紋的綁定也一樣。
- .state/account-info/<帳號標籤>.json，帳號資訊（oauthAccount 整份，含 email；只保存、不顯示）：納管時與憑證快照一起寫，
  沒有帳號資訊的納管（匯入、讀不到）會把同標籤原有的刪掉；移除憑證快照時一併刪，憑證快照已不在的孤兒也在這時清掉。
  帳號資訊的帳號識別碼必須等於憑證快照綁定的帳號識別碼才算「附有」：使用者手動換掉憑證快照的內容時，舊的帳號資訊不會被沿用。
  讀不出來的視為沒有。寫不成丟 OSError（憑證快照與綁定已寫成，該帳號暫時是僅監看帳號）；刪不掉的孤兒不丟例外，下次再清。
- .state/bindings.json，綁定：納管、移除、綁定維護、憑證同步會寫。讀不到時納管拒絕、移除、維護與同步不寫；有憑證快照讀不出
  憑證指紋時只加不清（同步只加不清：舊憑證指紋留給之後的維護）。寫不成丟 OSError，原檔不變。
- .state/readings.json，待命讀數：記住讀數時寫，綁定被清掉時連帶修剪。讀不到就什麼都不寫，下次再試。
  同一個檔案裡的 _lagging 欄位是「切換前已落後」的標記：帳號識別碼 → 被標記的讀數的觀測時間。標記只在讀數的觀測時間
  相同時才成立，讀數換了就失效並隨寫入清掉；沒有這個欄位的舊檔視為沒有標記。
- .state/observed.json，上一輪觀測：每輪寫。讀不到時呼叫端這一輪不判定；寫不成丟 OSError。
  invalidSnapshots（持久的失效旗標）與 expiresAt（上一輪當前憑證的到期時間）是後加的欄位，沒有的舊檔視為沒有旗標、不知道到期時間。
- .state/writeback.json，寫回失敗：憑證同步寫回失敗時記下（沒寫成的憑證快照的憑證指紋 → 當時當前憑證的憑證指紋、失敗次數、
  是否已停止重試），寫回成功、重新納管或移除（那份憑證指紋不在了）時清掉。讀不到時照樣寫回，但失敗不記次數；
  寫不成不丟例外，下一輪再記。沒有這個檔的舊版視為沒有寫回失敗。
- .state/switches.jsonl，切換紀錄：只追加。寫不成丟 OSError，既有的行不變。
- .state/pre-switch.json，切換前憑證（當前憑證原文＋帳號資訊，含 email；只保存、不顯示）：每次切換在寫入當前憑證之前覆寫，
  只有一份。寫不成丟 OSError，呼叫端不切換。
- .state/window.json，視窗位置：寫不成是「這次沒記住」，不丟例外；收不緊權限照常寫入。
- .state/warnings.json，關掉看板「未收緊」告警的紀錄：使用者關掉時寫，某一輪權限全部收緊成功時清掉。
  讀不到當成沒關、下次再讀；寫不成不丟例外，記憶體裡照樣生效，下一輪重試寫入。

已知限制：GUI 與命令列是兩個程序，同時寫同一個檔案（例如綁定檔）時沒有跨程序的鎖；兩者在同一輪內交錯時，
後寫的會蓋掉先寫的。被蓋掉的綁定若屬於當前憑證帳號，之後的 poll 會補學回來。
"""
import json
import re
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, NamedTuple, Optional, Set, Tuple

from . import atomic
from . import claude_provider as provider
from .board import WRITEBACK_ATTEMPTS
from .credstore import BytesCredentialStore, FileCredentialStore
from .permissions import is_private, make_private

_LAGGING_FIELD = "_lagging"  # 讀數檔裡存落後標記的欄位；帳號識別碼不會是這個名字，舊版讀數檔的讀法會把它當成讀不懂的一筆略過
_STATE_DIR = ".state"  # 納管目錄底下放工具狀態的子目錄，與憑證快照分開
_ACCOUNT_INFO_DIR = "account-info"  # 工具狀態目錄底下，一個帳號標籤一個檔，存納管時的帳號資訊
_ILLEGAL_IN_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# 固定值：兩份憑證的 refreshToken 到期時間相差在這之內，就算出自同一次登入（ADR-0011）。
# Claude Code 存的是「本機時間加剩餘秒數」，同一次登入的輪替前後實測差距最大約 1.2 秒
SAME_LOGIN_TOLERANCE = timedelta(seconds=60)
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                   *(f"LPT{i}" for i in range(1, 10))}


class InvalidLabel(ValueError):
    """帳號標籤就是憑證快照的檔名，必須是單純、合法的檔名。"""


class NoCredential(Exception):
    """讀不出憑證（尚未登入、或憑證檔讀不懂），無法納管。"""


class UnknownLabel(LookupError):
    """沒有這個帳號標籤的憑證快照。"""


class BindingsUnreadable(Exception):
    """綁定檔存在但暫時讀不到（例如被防毒或其他程式鎖住）：納管寫回綁定會洗掉其他帳號的綁定，所以整個拒絕。"""

    def __init__(self, path: Path):
        super().__init__(str(path))
        self.path = path


class WatchedAccount(NamedTuple):
    """監看帳號：帳號標籤、憑證快照的憑證指紋（讀不出來為 None，即「未知」）、綁定的帳號識別碼（沒有為 None）、
    憑證快照的到期時間、是否附有帳號資訊。"""
    label: str
    fingerprint: Optional[str]
    account_id: Optional[str]
    expires_at: Optional[datetime]
    has_account_info: bool = False


class Stored(NamedTuple):
    """納管的結果：這份憑證快照現在有沒有綁定、納管目錄裡有沒有原本外露而被修正的權限、有沒有收不緊的權限。"""
    bound: bool
    permissions_fixed: bool
    untightened: bool = False  # 這次納管有路徑收緊後查回仍未收緊（例如 FAT32／exFAT），照常寫入


class Observed(NamedTuple):
    """上一輪的觀測：當時當前憑證的憑證指紋；暫定的失效旗標（當前憑證帳號的憑證快照，帳號資訊還可能跟上而改判）；
    持久的失效旗標（保留到重新納管）；當時當前憑證的到期時間。沒有上一輪時全部是空的。"""
    fingerprint: Optional[str] = None
    pending_invalid: Optional[str] = None
    kept_invalid: Tuple[str, ...] = ()
    expires_at: Optional[datetime] = None


class Synced(NamedTuple):
    """憑證同步寫回了一份憑證快照：它原本與現在的憑證指紋。"""
    old_fingerprint: str
    new_fingerprint: str

    def follow(self, fingerprint: Optional[str]) -> Optional[str]:
        """記著舊憑證指紋的地方，換成寫回後的新憑證指紋；其他的原樣。"""
        return self.new_fingerprint if fingerprint == self.old_fingerprint else fingerprint


class WritebackFailure(NamedTuple):
    """寫回憑證快照失敗：當時當前憑證的憑證指紋、連續失敗的次數、是否已停止重試。"""
    credential: str
    failures: int
    stopped: bool = False


class PermissionState(Enum):
    """納管目錄的權限狀態：只查不改，未收緊不區分原因。"""
    TIGHTENED = "tightened"
    UNTIGHTENED = "untightened"
    NOT_CREATED = "not_created"


def same_login(a: Optional[datetime], b: Optional[datetime]) -> bool:
    """兩份憑證出自同一次登入：refreshToken 的到期時間都知道，而且相差在容許範圍內。不看事件先後。"""
    return a is not None and b is not None and abs(a - b) <= SAME_LOGIN_TOLERANCE


def check_label(label: str) -> None:
    """帳號標籤會直接成為憑證快照的檔名：擋掉路徑、Windows 不接受的檔名，以及點開頭（留給工具自己的檔案）。
    不合法就丟 InvalidLabel。納管時一定會檢查；呼叫端可以先呼叫，在做其他事之前就拒絕。"""
    if (not label.strip() or label.startswith(".") or label.endswith((".", " "))
            or _ILLEGAL_IN_NAME.search(label) or label.split(".")[0].upper() in _RESERVED_NAMES):
        raise InvalidLabel(label)


class ManagedDirectory:
    """一個納管目錄的所有讀寫；路徑由設定決定，核心啟動時給一次。"""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._state_dir = self._path / _STATE_DIR
        self._observed = self._state_dir / "observed.json"  # 最後運作時間與上一輪的觀測
        self._switch_log = self._state_dir / "switches.jsonl"
        self._window_position = self._state_dir / "window.json"
        self._bindings_file = self._state_dir / "bindings.json"  # 憑證指紋 → 帳號識別碼
        self._writeback_file = self._state_dir / "writeback.json"  # 沒寫成的憑證快照的憑證指紋 → 寫回失敗
        self._account_info_dir = self._state_dir / _ACCOUNT_INFO_DIR  # 帳號標籤 → 納管時的帳號資訊
        self._pre_switch_file = self._state_dir / "pre-switch.json"  # 切換前憑證，只有一份
        self._readings_file = self._state_dir / "readings.json"  # 待命帳號的最後讀數
        self._readings: Optional[Dict[str, provider.UsageReading]] = None  # 第一次用到才讀檔
        self._lagging: Dict[str, str] = {}  # 帳號識別碼 → 被標為落後的讀數的觀測時間；與 _readings 一起讀、一起寫
        self._untightened = False  # 自上次 begin_round 起，有沒有收緊後查回仍未收緊的路徑
        self._tightening_checked = False  # 自上次 begin_round 起，有沒有檢查過任何路徑的權限
        self._warnings_file = self._state_dir / "warnings.json"  # 關掉看板「未收緊」告警的紀錄
        self._dismissed: Optional[bool] = None  # 第一次用到才讀檔；讀不到時維持 None，下次再讀
        self._dismissal_unsaved = False  # 記憶體裡的紀錄還沒寫進檔案，下一輪重試

    def begin_round(self) -> None:
        """一輪 poll 開始：清掉上一輪的「未收緊」，這一輪再碰到才會再亮。"""
        self._untightened = self._tightening_checked = False

    def end_round(self) -> None:
        """一輪 poll 的寫入都做完之後：這一輪有檢查權限且全部收緊成功，就清掉關掉的紀錄（之後再收不緊會重新告警）；
        否則重試上次沒寫進去的紀錄。"""
        if self._tightening_checked and not self._untightened and self._untightened_dismissed():
            self._dismissed, self._dismissal_unsaved = False, True
        if self._dismissal_unsaved:
            self._save_dismissal()

    def untightened_warning_lit(self) -> bool:
        """看板的「未收緊」告警亮著：自上次 begin_round 起有收緊後查回仍未收緊的路徑（判定以行為為準，不查檔案系統的種類），
        且使用者沒有關掉。"""
        return self._untightened and not self._untightened_dismissed()

    def _untightened_dismissed(self) -> bool:
        """使用者關掉了看板的「未收緊」告警。紀錄存在這個納管目錄裡，換目錄就沒有；讀不到當成沒關。"""
        if self._dismissed is None:
            state = self._read_state(self._warnings_file)
            if state is None:
                return False
            self._dismissed = state.get("untightenedDismissed") is True
        return self._dismissed

    def dismiss_untightened_warning(self) -> None:
        """關掉看板的「未收緊」告警：記憶體裡立刻生效；寫不進去不丟例外，下一輪重試。不影響納管告警。"""
        self._dismissed = True
        self._dismissal_unsaved = True
        self._save_dismissal()

    def _save_dismissal(self) -> None:
        try:
            self._write_state(self._warnings_file, {"untightenedDismissed": self._dismissed})
        except OSError:
            return
        self._dismissal_unsaved = False

    def permission_state(self) -> PermissionState:
        """納管目錄與其中所有檔案目前的權限狀態。只查不改；查詢本身出錯算未收緊。"""
        if not self._path.is_dir():
            return PermissionState.NOT_CREATED
        paths = [self._path, *(p for p in self._path.iterdir() if p.is_file() or p == self._state_dir)]
        if self._state_dir.is_dir():
            paths += [p for p in self._state_dir.iterdir() if p.is_file()]
        if self._account_info_dir.is_dir():
            paths += [self._account_info_dir, *(p for p in self._account_info_dir.iterdir() if p.is_file())]
        try:
            private = all(is_private(p) for p in paths)
        except OSError:
            private = False
        return PermissionState.TIGHTENED if private else PermissionState.UNTIGHTENED

    def _tighten(self, path: Path, new: bool = False) -> bool:
        """收緊到只有目前使用者能存取。回傳是否修正了原本外露的權限；剛建立的不算。
        收緊回報錯誤、或事後驗證仍不符：不丟例外，記下「未收緊」，呼叫端照常寫入。"""
        self._tightening_checked = True
        if _private(path):
            return False
        try:
            make_private(path)
        except OSError:
            pass  # 與「收緊成功但沒效果」同一條路：以事後查回的結果為準
        if not _private(path):
            self._untightened = True
            return False
        return not new

    def _mkdir_private(self, path: Path) -> bool:
        """先收緊目錄再往裡面寫，檔案一建立就不會外露。回傳是否修正了既有目錄的權限。"""
        new = not path.exists()
        path.mkdir(exist_ok=True)
        return self._tighten(path, new)

    def read_observed(self) -> Optional[Observed]:
        """讀不到回傳 None（呼叫端這一輪不判定）；不存在或讀不懂就當成沒有上一輪。"""
        state = self._read_state(self._observed)
        if state is None:
            return None
        flags = state.get("invalidSnapshots")
        return Observed(_text(state.get("fingerprint")), _text(state.get("invalidSnapshot")),
                        tuple(f for f in flags if _text(f)) if isinstance(flags, list) else (),
                        _datetime(state.get("expiresAt")))

    def write_observed(self, last_run_at: datetime, observed: Observed) -> None:
        """記下這一輪的觀測與運作時間，下一輪（含重新啟動後）接著比對。寫不成就丟 OSError。"""
        expires = observed.expires_at.isoformat() if observed.expires_at else None
        self._write_state(self._observed, {"lastRunAt": last_run_at.isoformat(), "fingerprint": observed.fingerprint,
                                          "invalidSnapshot": observed.pending_invalid,
                                          "invalidSnapshots": sorted(observed.kept_invalid),
                                          "expiresAt": expires})

    def append_switch(self, at: datetime, account_id: Optional[str]) -> None:
        """切換紀錄只追加：時間、切到的帳號識別碼（拿不到為 null）、來源。不記帳號鍵（ADR-0009）。寫不成就丟 OSError。"""
        self._mkdir_state_dir()
        line = json.dumps({"at": at.isoformat(), "accountId": account_id, "source": "observed"})
        atomic.append(self._switch_log, (line + "\n").encode("utf-8"),
                      before_replace=lambda tmp: self._tighten(tmp, new=True))

    def list_accounts(self) -> Tuple[WatchedAccount, ...]:
        """所有監看帳號，依帳號標籤排序。綁定檔讀不到時當成都沒有綁定；憑證指紋讀不出來的是「未知」。"""
        bindings = self._read_state(self._bindings_file) or {}
        accounts = []
        for label in self._snapshot_labels():
            snapshot = FileCredentialStore(self._snapshot(label))
            fingerprint, credential = snapshot.fingerprint(), snapshot.read()
            bound = bindings.get(fingerprint) if fingerprint else None
            account_id = _text(bound.get("accountId")) if isinstance(bound, dict) else None
            accounts.append(WatchedAccount(label, fingerprint, account_id,
                                           credential.refresh_token_expires_at if credential else None,
                                           self._has_account_info(label, account_id)))
        return tuple(accounts)

    def maintain_bindings(self, learn: Optional[Tuple[str, str]] = None) -> bool:
        """不經過納管的綁定維護：補學一筆綁定 learn（憑證指紋、帳號識別碼），並清掉憑證快照已不在的孤兒綁定與
        它們的待命讀數，一次寫完。綁定檔讀不到、或有憑證快照讀不出憑證指紋（寫到一半、被鎖住）時什麼都不動：
        寫綁定會依現有的憑證指紋過濾，讀不出來的那份憑證快照的綁定會被一起洗掉。
        回傳有沒有寫綁定檔（沒有要補、沒有要清、或不能動都是 False）；寫不成就丟 OSError，綁定檔維持原樣。"""
        bindings = self._read_state(self._bindings_file)
        live = self._live_fingerprints()
        if bindings is None or None in live:
            return False
        if learn is None and not set(bindings) - live:
            return False
        if learn is not None:
            bindings[learn[0]] = {"accountId": learn[1]}
        self._write_bindings(bindings, live)
        return True

    def store_snapshot(self, label: str, data: bytes, account_id: Optional[str],
                       account_info: Optional[dict] = None) -> Stored:
        """納管一份憑證快照：data 是憑證內容，寫成帳號標籤 label 的憑證快照，並記下綁定（account_id 為 None 時
        只沿用同一憑證指紋原有的綁定），順帶清掉被換掉的舊憑證指紋與它的待命讀數。
        account_info 是納管時登入帳號的整份帳號資訊，與憑證快照一起保存；None 表示這次沒有（例如匯入），同標籤原有的會刪掉。
        依序：帳號標籤不合法丟 InvalidLabel；綁定檔讀不到丟 BindingsUnreadable（寫綁定會洗掉其他帳號的綁定）；
        data 讀不出憑證指紋丟 NoCredential（既有的憑證快照與綁定維持原樣，但納管目錄可能已先建立並收緊）。
        之後事後驗證納管目錄、工具狀態目錄、綁定檔與所有憑證快照的權限，不符就修正並回報。寫不成丟 OSError。"""
        check_label(label)
        bindings = self._read_state(self._bindings_file)
        if bindings is None:  # 先確認讀得到才寫憑證快照：讀不到就什麼都不動
            raise BindingsUnreadable(self._bindings_file)
        self._untightened = False  # 納管的告警只看這一次碰到的
        fixed = self._mkdir_private(self._path)
        fingerprint = self._write_snapshot(label, data)
        if account_id:
            bindings[fingerprint] = {"accountId": account_id}
        self._write_bindings(bindings, self._live_fingerprints())
        self._write_account_info(label, account_info)
        fixed = any([self._tighten(self._state_dir), self._tighten(self._bindings_file)]) or fixed
        # 事後驗證：連同既有的憑證快照與帳號資訊一起檢查
        fixed = any([self._tighten(self._snapshot(other)) for other in self._snapshot_labels()]) or fixed
        fixed = any([self._tighten(p) for p in self._account_info_paths()]) or fixed
        return Stored(fingerprint in bindings, fixed, self._untightened)

    def sync_snapshot(self, data: bytes) -> Optional[Synced]:
        """憑證同步（ADR-0011）：data 是當前憑證的內容。它的 refreshToken 到期時間與某份憑證快照出自同一次登入、
        只有這一份符合、而且憑證指紋不同，就把 data 寫回那份憑證快照，綁定跟著換到新的憑證指紋；帳號資訊以帳號標籤
        為鍵，不必動。沒有寫成（讀不出憑證、沒有或有兩份以上符合、已經相同、寫回失敗、已停止重試）回傳 None。
        寫回失敗不丟例外，記進寫回失敗：同一份當前憑證寫 WRITEBACK_ATTEMPTS 次都失敗就停止重試，當前憑證的指紋改變時
        重新計數。沒寫成的憑證快照已不是當前憑證那次登入的（例如換了帳號），沒有東西可以重試，直接停止重試。"""
        current = BytesCredentialStore(data)
        fingerprint, credential = current.fingerprint(), current.read()
        expires = credential.refresh_token_expires_at if credential else None
        if fingerprint is None or expires is None:
            return None
        accounts = self.list_accounts()
        matches = [a for a in accounts if same_login(a.expires_at, expires)]
        target = matches[0] if len(matches) == 1 else None
        old = target.fingerprint if target else None  # 要寫回的那份憑證快照目前的憑證指紋
        state = self._read_state(self._writeback_file)
        if state is None:  # 讀不到寫回失敗：照樣寫回，失敗不記次數
            return self._write_back(target, old, data, fingerprint) if target and old and old != fingerprint else None
        records = self._live_writeback_failures(state, accounts)
        if all(a.fingerprint for a in accounts):  # 有憑證快照讀不出指紋：分不出要寫回的是不是它，不動
            for other, failure in records.items():  # 其他沒寫成的憑證快照：當前憑證已不是那次登入，沒有東西可以重試
                if other != old and not failure.stopped:
                    records[other] = failure._replace(stopped=True)
        synced = None
        if target and old and old != fingerprint:
            previous = records.get(old)
            if previous is not None and previous.credential != fingerprint:
                previous = None  # 當前憑證又刷新了：重新計數
            if previous is None or not previous.stopped:
                synced = self._write_back(target, old, data, fingerprint)
                if synced:
                    records.pop(old, None)
                else:
                    failed = (previous.failures if previous else 0) + 1
                    records[old] = WritebackFailure(fingerprint, failed, failed >= WRITEBACK_ATTEMPTS)
        if records != self._live_writeback_failures(state, None):
            self._write_writeback_failures(records)
        return synced

    def writeback_failures(self) -> Dict[str, WritebackFailure]:
        """沒寫成的憑證快照的憑證指紋 → 寫回失敗。讀不到當成沒有，下一輪再讀。"""
        return self._live_writeback_failures(self._read_state(self._writeback_file) or {}, None)

    def _live_writeback_failures(self, state: dict, accounts) -> Dict[str, WritebackFailure]:
        """解析寫回失敗；accounts 不為 None 時只留憑證快照還在、憑證指紋沒變的（寫回成功、重新納管、移除都會換掉），
        但有憑證快照讀不出憑證指紋時不修剪。單筆讀不懂的略過。"""
        live = None if accounts is None else {a.fingerprint for a in accounts}
        records = {}
        for old, value in state.items():
            if not isinstance(value, dict) or live is not None and None not in live and old not in live:
                continue
            credential, failures = _text(value.get("credential")), value.get("failures")
            if credential and type(failures) is int and failures > 0:
                records[old] = WritebackFailure(credential, failures, value.get("stopped") is True)
        return records

    def _write_writeback_failures(self, records: Dict[str, WritebackFailure]) -> None:
        """寫不成不丟例外：這一輪的次數沒記住，下一輪再記。"""
        try:
            self._write_state(self._writeback_file, {old: {"credential": f.credential, "failures": f.failures,
                                                           "stopped": f.stopped} for old, f in records.items()})
        except OSError:
            pass

    def _write_back(self, target: WatchedAccount, old: str, data: bytes, fingerprint: str) -> Optional[Synced]:
        """把當前憑證寫回 target（目前的憑證指紋是 old）。綁定檔讀不到時不寫：寫回後綁定換不過去，帳號會被當成
        沒有帳號資訊。寫不成（含綁定檔讀不到）回傳 None。"""
        bindings = self._read_state(self._bindings_file)
        if bindings is None:
            return None
        try:
            if old in bindings:
                bindings[fingerprint] = bindings[old]
                self._write_state(self._bindings_file, bindings)
            self._write_snapshot(target.label, data)
        except OSError:
            return None
        return Synced(old, fingerprint)

    def switch_target(self, label: str) -> Optional[Tuple[bytes, dict]]:
        """切換到帳號標籤 label 要寫的內容：憑證快照的位元組與帳號資訊。沒有這份憑證快照、或沒有附帳號資訊回傳 None；
        讀不到丟 OSError。"""
        if label not in self._snapshot_labels():
            return None
        accounts = {a.label: a for a in self.list_accounts()}
        account = accounts.get(label)
        if account is None or not account.has_account_info:
            return None
        info = self._read_state(self._account_info_file(label))
        if info is None:
            raise OSError("account info unreadable")
        return self._snapshot(label).read_bytes(), info

    def save_pre_switch(self, credentials: bytes, account_info: Optional[dict]) -> Optional[bytes]:
        """保存切換前憑證：切換當下的當前憑證（原樣）與帳號資訊（讀不到為 None）。只有一份，每次切換都覆寫；
        放在工具狀態目錄，不是憑證快照，不產生卡片。回傳被蓋掉的那份（原本沒有為 None），切換沒寫成時交給
        restore_pre_switch 放回去。原本那份讀不到、或寫不成都丟 OSError，原檔不變。"""
        try:
            replaced: Optional[bytes] = self._pre_switch_file.read_bytes()
        except FileNotFoundError:
            replaced = None
        self._write_state(self._pre_switch_file, {"credentials": credentials.decode("utf-8"),
                                                  "accountInfo": account_info})
        return replaced

    def pre_switch_target(self) -> Optional[Tuple[bytes, dict]]:
        """還原要寫的內容：切換前憑證的原文與帳號資訊。沒有、讀不懂、或當時的帳號資訊是空的回傳 None
        （只還原憑證會讓帳號資訊錯配）；讀不到丟 OSError。"""
        state = self._read_state(self._pre_switch_file)
        if state is None:
            raise OSError("pre-switch credential unreadable")
        credentials, info = state.get("credentials"), state.get("accountInfo")
        if not isinstance(credentials, str) or not isinstance(info, dict) or not info:
            return None
        return credentials.encode("utf-8"), info

    def restore_pre_switch(self, replaced: Optional[bytes]) -> None:
        """放回 save_pre_switch 蓋掉的那份；原本沒有就刪掉。放不回去不丟例外：還原點這次就丟了。"""
        try:
            if replaced is None:
                atomic.remove(self._pre_switch_file)
            else:
                atomic.write_atomic(self._pre_switch_file, replaced,
                                    before_replace=lambda tmp: self._tighten(tmp, new=True))
        except OSError:
            pass

    def remove_snapshot(self, label: str) -> None:
        """移除帳號標籤 label 的憑證快照，清掉它的孤兒綁定與待命讀數。沒有這份憑證快照丟 UnknownLabel。
        綁定檔讀不到時只刪憑證快照、不寫綁定檔，留下的孤兒綁定由之後的維護清掉。刪不掉丟 OSError。"""
        if label not in self._snapshot_labels():
            raise UnknownLabel(label)
        atomic.remove(self._snapshot(label))
        self._prune_account_info()
        bindings = self._read_state(self._bindings_file)
        if bindings is not None:
            self._write_bindings(bindings, self._live_fingerprints())

    def _has_account_info(self, label: str, account_id: Optional[str]) -> bool:
        """帳號標籤 label 附有帳號資訊：讀得出帳號識別碼，而且等於憑證快照綁定的帳號識別碼（沒有綁定就不算）。"""
        if account_id is None:
            return False
        info = self._read_state(self._account_info_file(label)) or {}
        return _text(info.get("accountUuid")) == account_id

    def _write_account_info(self, label: str, info: Optional[dict]) -> None:
        """納管時把帳號資訊存成 label 的檔；沒有帳號資訊就刪掉原有的。順帶清掉憑證快照已不在的孤兒。
        目錄先收緊再往裡面寫；寫不成丟 OSError。"""
        if info:
            self._mkdir_state_dir()
            self._mkdir_private(self._account_info_dir)
            self._write_json(self._account_info_file(label), info)
        elif self._account_info_file(label).exists():
            atomic.remove(self._account_info_file(label))
        self._prune_account_info()

    def _prune_account_info(self) -> None:
        """刪掉憑證快照已不在的帳號資訊，免得它被日後放進同名檔案的別人憑證沿用。刪不掉不丟例外，下次再清。"""
        labels = set(self._snapshot_labels())
        for path in self._account_info_paths():
            if path.suffix == ".json" and path.stem not in labels:
                try:
                    atomic.remove(path)
                except OSError:
                    pass

    def _account_info_paths(self) -> Tuple[Path, ...]:
        """帳號資訊的目錄（存在的話）與裡面的檔案。"""
        if not self._account_info_dir.is_dir():
            return ()
        return (self._account_info_dir, *sorted(p for p in self._account_info_dir.iterdir() if p.is_file()))

    def _account_info_file(self, label: str) -> Path:
        return self._account_info_dir / f"{label}.json"

    def _write_snapshot(self, label: str, data: bytes) -> str:
        """替換前先驗證暫存檔讀得出憑證指紋：讀到寫到一半的憑證時，既有的憑證快照維持原樣。回傳憑證指紋。"""
        fingerprints = []

        def check(tmp: Path) -> None:
            fingerprint = FileCredentialStore(tmp).fingerprint()
            if fingerprint is None:
                raise NoCredential()
            self._tighten(tmp, new=True)
            fingerprints.append(fingerprint)
        atomic.write_atomic(self._snapshot(label), data, before_replace=check)
        return fingerprints[0]

    def _snapshot_labels(self) -> Tuple[str, ...]:
        """帳號標籤就是憑證快照的檔名去掉 .json；點開頭的是工具自己的檔案。"""
        if not self._path.is_dir():
            return ()
        return tuple(sorted(p.stem for p in self._path.glob("*.json") if p.is_file() and not p.name.startswith(".")))

    def _live_fingerprints(self) -> Set[Optional[str]]:
        """每份憑證快照的憑證指紋；讀不出來的算成 None。"""
        return {FileCredentialStore(self._snapshot(label)).fingerprint() for label in self._snapshot_labels()}

    def _write_bindings(self, bindings: dict, live: Set[Optional[str]]) -> None:
        """綁定以憑證指紋為鍵；只留還有憑證快照對應的憑證指紋，重新納管換掉的舊憑證指紋一併清掉。
        有憑證快照讀不出憑證指紋時不修剪綁定與讀數，原樣寫回，留給之後的維護。"""
        if None in live:
            self._write_state(self._bindings_file, bindings)
            return
        kept = {k: v for k, v in bindings.items() if k in live}
        self._write_state(self._bindings_file, kept)
        self._prune_standby_readings({v.get("accountId") for v in kept.values() if isinstance(v, dict)})

    def _snapshot(self, label: str) -> Path:
        return self._path / f"{label}.json"

    def read_standby_readings(self) -> Optional[Dict[str, provider.UsageReading]]:
        """帳號識別碼 → 最後一次歸屬給它的讀數。讀不到回傳 None（下一次再讀）；不存在或讀不懂就當成沒有，
        單筆讀不懂的略過。讀到之後由 module 在記憶體保管，不再回頭讀檔。"""
        if self._readings is None:
            state = self._read_state(self._readings_file)
            if state is None:
                return None
            marks = state.pop(_LAGGING_FIELD, None)
            parsed = {k: provider.parse_cache(cache) for k, cache in state.items()}
            self._readings = {k: r for k, r in parsed.items() if isinstance(r, provider.UsageReading)}
            self._lagging = {k: v for k, v in marks.items() if isinstance(v, str)} if isinstance(marks, dict) else {}
        return self._readings

    def standby_lagging(self, account_id: str) -> bool:
        """這個帳號最後一次的讀數，在切換前就已落後。讀數換了（觀測時間不同）、沒有標記、讀不到讀數檔都是 False。"""
        stored = self.read_standby_readings()
        reading = stored.get(account_id) if stored else None
        return reading is not None and self._lagging.get(account_id) == _stamp(reading)

    def mark_standby_lagging(self, account_id: str, lagging: bool) -> None:
        """標記（或清除）這個帳號目前存著的讀數是否在切換前就已落後。沒有存著的讀數、讀數檔讀不到、結果沒變就什麼都不寫。
        寫不成就丟 OSError，檔案與記憶體裡的標記都維持原樣。"""
        stored = self.read_standby_readings()
        reading = stored.get(account_id) if stored else None
        if reading is None or self.standby_lagging(account_id) == lagging:
            return
        marks = {k: v for k, v in self._lagging.items() if k != account_id}
        if lagging:
            marks[account_id] = _stamp(reading)
        self._write_readings(stored, set(stored), marks)

    def remember_standby_reading(self, reading: provider.UsageReading, bound: Set[str]) -> None:
        """額度快取的讀數歸屬到某個綁定的帳號時記下來，並只留 bound 裡的帳號；沒變就不寫。
        讀數檔讀不到時什麼都不寫，下一輪再試。寫不成就丟 OSError，檔案維持原樣。"""
        stored = self.read_standby_readings()
        if stored is None or reading.account_id not in bound or stored.get(reading.account_id) == reading:
            return
        self._write_readings({**stored, reading.account_id: reading}, bound)

    def _prune_standby_readings(self, bound: Set[str]) -> None:
        """只留 bound 裡的帳號的讀數；讀數檔讀不到、沒有要清的就不寫。"""
        stored = self.read_standby_readings()
        if stored is not None and set(stored) - bound:
            self._write_readings(stored, bound)

    def _write_readings(self, readings: Dict[str, provider.UsageReading], bound: Set[str],
                        marks: Optional[Dict[str, str]] = None) -> None:
        """存的是 cachedUsageUtilization 原文，讀回來時再解析。落後標記只留讀數還在、觀測時間沒變的帳號；沒有標記時
        不寫那個欄位。寫成了才換記憶體裡的版本。"""
        kept = {k: r for k, r in readings.items() if k in bound}
        marks = self._lagging if marks is None else marks
        live = {k: v for k, v in marks.items() if k in kept and v == _stamp(kept[k])}
        state = {k: r.source for k, r in kept.items()}
        self._write_state(self._readings_file, {**state, _LAGGING_FIELD: live} if live else state)
        self._readings, self._lagging = kept, live

    def read_window_position(self) -> Optional[Tuple[int, int]]:
        """讀不到、不存在或讀不懂都回傳 None（視窗回到預設位置，不必區分原因）。"""
        state = self._read_state(self._window_position) or {}
        x, y = state.get("x"), state.get("y")
        return (x, y) if type(x) is int and type(y) is int else None

    def write_window_position(self, x: int, y: int) -> bool:
        """回傳這次有沒有記住。工具狀態目錄還不存在（還沒成功 poll 過）、寫不成都是「這次沒記住」，
        不丟例外也不建目錄；呼叫端下次移動或結束時再試。收不緊權限照常寫入。"""
        if not self._state_dir.is_dir():
            return False
        try:
            self._write_json(self._window_position, {"x": x, "y": y})
        except OSError:
            return False
        return True

    def _write_state(self, path: Path, data: dict) -> None:
        """工具狀態一律原子寫入，暫存檔在替換前就收緊權限。"""
        self._mkdir_state_dir()
        self._write_json(path, data)

    def _write_json(self, path: Path, data: dict) -> None:
        atomic.write_atomic(path, json.dumps(data, indent=2).encode("utf-8"),
                            before_replace=lambda tmp: self._tighten(tmp, new=True))

    @staticmethod
    def _read_state(path: Path) -> Optional[dict]:
        """三態讀取的唯一一份：讀不到回傳 None；不存在、讀不懂、不是物件都回傳空的。"""
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except OSError:
            return None
        except ValueError:
            return {}
        return state if isinstance(state, dict) else {}

    def _mkdir_state_dir(self) -> None:
        """poll 在還沒納管任何帳號時也會寫工具狀態，納管目錄可能還不存在。"""
        self._mkdir_private(self._path)
        self._mkdir_private(self._state_dir)


def _private(path: Path) -> bool:
    """查不回權限（查詢本身出錯）算未收緊，與 permission_state 一致。"""
    try:
        return is_private(path)
    except OSError:
        return False


def _stamp(reading: provider.UsageReading) -> str:
    """落後標記記的是哪一份讀數：以觀測時間認，讀數換了標記就對不上。"""
    return reading.observed_at.isoformat()


def _datetime(value) -> Optional[datetime]:
    """工具狀態裡的 ISO 時間；讀不懂、沒帶時區（無法跟憑證的到期時間比較）的視為沒有。"""
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return parsed if parsed and parsed.tzinfo else None


def _text(value) -> Optional[str]:
    return value if isinstance(value, str) and value else None
