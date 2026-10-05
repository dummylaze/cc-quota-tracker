"""核心：接收解析後的路徑與時鐘，對外只有 poll、add、remove。"""
import os
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable, FrozenSet, NamedTuple, Optional, Tuple

from . import claude_provider as provider
from . import usage_query
from .board import (Board, Card, CountdownFormat, Limit, Preferences, QueryFailure, QueryStatus, ReadingState, Role,
                    Severity, UsageQueryResult, WatchOnlyReason)
from .credstore import FileCredentialStore
from .managed_directory import (BindingsUnreadable, InvalidLabel, ManagedDirectory, NoCredential,  # noqa: F401
                                Observed, PermissionState, UnknownLabel, check_label)
# 納管會丟的例外定義在納管目錄，核心仍對外匯出：命令列、GUI 與既有測試的匯入路徑不變
from .settings import (CLAUDE_CONFIG_DIR, COUNTDOWN_FORMAT_FIELD, PathSource, ResolvedPaths, path_fields,
                       read_preferences, read_settings)

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
SCHEMA_CHANGE_ROUNDS = 3  # 結構不符連續這麼多輪才判定為結構變更；偶發一次不亮橫幅
# 沒落後時多久重掃一次對話紀錄：落後提示最多晚這麼久出現，換來不必每輪 poll 都 stat 所有對話紀錄
LAG_SCAN_INTERVAL = timedelta(seconds=60)
QUERY_COOLDOWN = timedelta(seconds=30)  # 固定值：手動查詢完成（成功或失敗）後，這麼久之內不能再觸發
QUERY_CHECK_SECONDS = 0.05  # 同步查詢時，多久看一次子行程與額度快取（真實時間）
AUTO_QUERY_PAUSE_AFTER = 3  # 固定值：查詢連續失敗這麼多次，自動查詢就暫停；一次成功（含手動）才恢復


class _LagScan(NamedTuple):
    """上一次掃描對話紀錄：比對的是哪個觀測時間、何時掃的、結果是否落後。"""
    observed_at: datetime
    scanned_at: datetime
    lagging: bool


class AddWarning(Enum):
    PERMISSIONS_FIXED = "permissions_fixed"  # 納管目錄或檔案的權限原本不符（他人可存取或靠繼承），已修正
    LABEL_LOOKS_LIKE_EMAIL = "label_looks_like_email"  # 帳號標籤會顯示在畫面上
    PERMISSIONS_UNTIGHTENED = "permissions_untightened"  # 納管目錄的權限收不緊（例如 FAT32／exFAT），照常寫入
    NOT_BOUND = "not_bound"  # 讀不到目前登入帳號的識別碼，憑證快照暫時沒有綁定


@dataclass(frozen=True)
class _Account:
    """監看帳號：帳號鍵、憑證快照的憑證指紋、綁定的帳號識別碼（沒有綁定為 None）、refreshToken 的到期時間、
    是否附有帳號資訊。"""
    key: str
    fingerprint: Optional[str]
    account_id: Optional[str]
    expires_at: Optional[datetime] = None
    has_account_info: bool = False


@dataclass(frozen=True)
class AddResult:
    account_key: str
    warnings: FrozenSet[AddWarning] = frozenset()


class Core:
    def __init__(self, paths: ResolvedPaths, clock: Callable[[], datetime], auto_query: bool = True):
        """auto_query：poll 可以依設定自動查詢額度。只有常駐的視窗該開；命令列的 poll 一次就結束，不該留下查詢。"""
        self._auto_query = auto_query
        self._source = paths.claude_json
        self._credentials = paths.claude_dir / provider.CREDENTIALS
        self._transcripts = paths.claude_dir / provider.TRANSCRIPTS
        self._lag_scan: Optional[_LagScan] = None
        self._managed = ManagedDirectory(paths.managed_dir)
        self._paths = paths
        self._source_missing = False
        self._settings_mtime: Optional[int] = None
        self._path_fields = paths.path_fields  # 設定檔目前寫的路徑欄位；與啟動時不同就要重新啟動
        self._settings_unreadable = False  # 第一輪 poll 就會重讀設定檔
        self._countdown_format = CountdownFormat.TWO_UNITS
        self._provider_settings = provider.ProviderSettings()  # 設定檔的 providers.claude
        self._preferences, self._invalid_settings = Preferences(), ()
        self._oauth_account_id: Optional[str] = None  # 目前登入帳號的識別碼（oauthAccount），未監看帳號靠它歸屬讀數
        self._clock = clock
        self._mtime: Optional[int] = None
        self._reading: Optional[provider.UsageReading] = None
        self._result: provider.ParseResult = provider.NoReading()
        self._mismatch_rounds = 0
        self._query: Optional[usage_query.UsageQuery] = None  # 進行中的查詢；查詢狀態都只存在記憶體
        self._cooldown_until: Optional[datetime] = None
        self._last_query_failure: Optional[UsageQueryResult] = None
        self._last_query_started: Optional[datetime] = None  # 工具上一次查詢的開始時間（手動、自動都算）
        self._query_is_auto = False  # 進行中的查詢是不是自動觸發的：手動查詢才有冷卻
        self._consecutive_failures = 0  # 查詢連續失敗的次數，一次成功歸零

    def poll(self) -> Board:
        self._managed.begin_round()
        self._poll_query()  # 先於 _refresh：查詢剛寫回的額度快取，這一輪就讀得到
        self._refresh()
        self._reread_settings()
        accounts = self._maintain_bindings(self._accounts())
        self._remember(accounts)
        active, invalid = self._observe(accounts)
        reading = self._reading
        cards = self._cards(accounts, active, invalid)
        self._maybe_auto_query(cards[0])  # 在建看板之前：這一輪啟動的查詢，這一輪的看板就顯示進行中
        self._managed.end_round()
        return Board(cards=cards,
                     schema_changed=self._mismatch_rounds >= SCHEMA_CHANGE_ROUNDS,
                     last_reading_at=reading.observed_at if reading else None,
                     watched_accounts=tuple(a.key for a in accounts),
                     wrong_location_suspected=self._source_missing and self._paths.claude_source is PathSource.DEFAULT,
                     restart_required=self._path_fields != self._paths.path_fields,
                     settings_unreadable=self._settings_unreadable,
                     as_of=self._clock(), countdown_format=self._countdown_format,
                     preferences=self._preferences, invalid_settings=self._invalid_settings,
                     usage_query=self._query_status(), permissions_untightened=self._managed.untightened_warning_lit())

    def dismiss_untightened_warning(self) -> None:
        """使用者從右鍵選單關掉看板的「未收緊」告警（ADR-0008）；下一輪 poll 起看板不再帶這個狀態。"""
        self._managed.dismiss_untightened_warning()

    def start_query(self) -> bool:
        """不阻塞的手動查詢入口，給 GUI 用：立刻返回，之後由 poll 檢查子行程。進行中或冷卻中回傳 False、什麼都不做。
        開不起來（找不到 claude）也算受理：失敗與冷卻照常記進查詢狀態。"""
        if self._query is not None or self._cooling_down():
            return False
        self._reread_settings()
        self._launch(auto=False)
        return True

    def _launch(self, auto: bool) -> None:
        self._last_query_started = self._clock()
        query = self._open_query()
        if query is None:
            self._finish_query(UsageQueryResult(QueryFailure.COMMAND_NOT_FOUND), auto)
        else:
            self._query, self._query_is_auto = query, auto

    def _maybe_auto_query(self, active: Card) -> None:
        """自動查詢，全部成立才查：已開啟、當前憑證帳號的卡片落後或讀數待更新、沒有查詢在進行、沒有暫停，
        且距離「工具上一次查詢的開始」與「目前讀數的觀測時間」兩者中較晚的那個已滿一個間隔
        （後者讓使用者自己打的 /usage 也算一次）。閒置時讀數不落後，所以自然不查。"""
        settings, reading = self._provider_settings, self._reading
        if (not self._auto_query or not settings.auto_usage_query or self._query is not None
                or self._consecutive_failures >= AUTO_QUERY_PAUSE_AFTER or reading is None
                or not (active.lagging or active.reading_state is ReadingState.PENDING)):
            return
        since = max(filter(None, (self._last_query_started, reading.observed_at)))
        if self._clock() - since >= timedelta(minutes=settings.auto_usage_query_minutes):
            self._launch(auto=True)

    def query_usage(self) -> UsageQueryResult:
        """同步查詢一次額度：請 Claude Code 寫回額度快取，等到成功、失敗或逾時。設定檔改了，這一次就照新的值。"""
        self._reread_settings()
        query = self._open_query()
        if query is None:
            return UsageQueryResult(QueryFailure.COMMAND_NOT_FOUND)
        while True:
            result = query.check(self._clock())
            if result is not None:
                return result
            time.sleep(QUERY_CHECK_SECONDS)

    def _open_query(self) -> Optional[usage_query.UsageQuery]:
        """開子行程送出查詢；找不到、開不起來回傳 None。"""
        command = usage_query.find_command(self._provider_settings, os.environ)
        if command is None:
            return None
        query = usage_query.UsageQuery(command, self._query_env(), self._source, self._clock() + usage_query.TIMEOUT)
        try:
            query.start()
        except OSError:
            return None
        return query

    def _poll_query(self) -> None:
        if self._query is None:
            return
        result = self._query.check(self._clock())
        if result is not None:
            self._query = None
            self._finish_query(result, self._query_is_auto)

    def _finish_query(self, result: UsageQueryResult, auto: bool) -> None:
        """冷卻只管手動查詢（避免連按）；自動查詢有自己的間隔。連續失敗只數自動查詢的失敗：
        手動失敗既不累計也不歸零，成功（手動或自動）才歸零。"""
        self._last_query_failure = result if result.failure else None
        if not result.failure:
            self._consecutive_failures = 0
        elif auto:
            self._consecutive_failures += 1
        if not auto:
            self._cooldown_until = self._clock() + QUERY_COOLDOWN

    def _cooling_down(self) -> bool:
        return self._cooldown_until is not None and self._clock() < self._cooldown_until

    def _query_status(self) -> QueryStatus:
        auto = self._provider_settings.auto_usage_query
        return QueryStatus(in_progress=self._query is not None, cooling_down=self._cooling_down(),
                           last_failure=self._last_query_failure, auto_enabled=auto,
                           auto_paused=auto and self._consecutive_failures >= AUTO_QUERY_PAUSE_AFTER,
                           interval_below_floor=self._provider_settings.interval_below_floor)

    def _query_env(self) -> dict:
        """讓查詢寫回的正是本工具在讀的那份額度快取：Claude Code 目錄是 home 預設時拿掉 CLAUDE_CONFIG_DIR，
        否則設成解析出的目錄。"""
        env = dict(os.environ)
        env.pop(CLAUDE_CONFIG_DIR, None)
        if self._paths.claude_source is not PathSource.DEFAULT:
            env[CLAUDE_CONFIG_DIR] = str(self._paths.claude_dir)
        return env

    def add(self, label: str) -> AddResult:
        check_label(label)  # 先於讀當前憑證：標籤不合法時，不論有沒有登入都回報標籤
        try:
            data = self._credentials.read_bytes()
        except OSError:
            raise NoCredential() from None
        try:
            text = self._source.read_text(encoding="utf-8")
        except OSError:
            account_id, info = None, None
        else:
            account_id, info = provider.account_id(text), provider.account_info(text)
        return self._store(label, data, account_id, info)

    def import_snapshot(self, source: Path, label: str) -> AddResult:
        """把一份憑證檔複製進納管目錄成為憑證快照，權限與 add 一樣收緊。不決定綁定：
        同一憑證指紋原有的綁定仍然有效，沒有的話由 poll 依直接放檔的補學規則處理。讀不出憑證就丟 NoCredential。"""
        check_label(label)
        try:
            data = Path(source).read_bytes()
        except OSError:
            raise NoCredential() from None
        return self._store(label, data, None, None)

    def _store(self, label: str, data: bytes, account_id: Optional[str], info: Optional[dict]) -> AddResult:
        # 沒有識別碼：同一憑證指紋原有的綁定仍然有效；沒有的話留給之後補學。沒有帳號資訊：成為僅監看帳號
        stored = self._managed.store_snapshot(label, data, account_id, info)
        warnings = {AddWarning.PERMISSIONS_FIXED} if stored.permissions_fixed else set()
        if stored.untightened:
            warnings.add(AddWarning.PERMISSIONS_UNTIGHTENED)
        if not stored.bound:
            warnings.add(AddWarning.NOT_BOUND)
        if _EMAIL.search(label):
            warnings.add(AddWarning.LABEL_LOOKS_LIKE_EMAIL)
        return AddResult(f"{provider.PROVIDER}:{label}", frozenset(warnings))

    def remove(self, label: str) -> None:
        self._managed.remove_snapshot(label)  # 綁定檔讀不到就不寫：留下的孤兒綁定由之後的 poll 清掉

    def _accounts(self) -> Tuple[_Account, ...]:
        return tuple(_Account(f"{provider.PROVIDER}:{a.label}", a.fingerprint, a.account_id, a.expires_at,
                              a.has_account_info)
                     for a in self._managed.list_accounts())

    def _maintain_bindings(self, accounts: Tuple[_Account, ...]) -> Tuple[_Account, ...]:
        """不經過 add 的綁定維護：直接放進目錄的憑證快照補學綁定，快照被刪掉的孤兒綁定清掉。
        這一輪能不能動（綁定檔讀不到、有憑證快照讀不出憑證指紋）由納管目錄判斷；寫不成時什麼都不動。"""
        target = self._snapshot_to_bind(accounts)
        learn = (target.fingerprint, self._oauth_account_id) if target and self._oauth_account_id else None
        try:
            changed = self._managed.maintain_bindings(learn)
        except OSError:
            return accounts
        return self._accounts() if changed else accounts

    def _snapshot_to_bind(self, accounts: Tuple[_Account, ...]) -> Optional[_Account]:
        """要補學綁定的憑證快照，沒有就是 None。這份快照本身還沒有綁定，而且三個條件同時成立才補學，缺一就不猜：
        它是當前憑證帳號、額度快取的識別碼等於 oauthAccount 的識別碼、該識別碼還沒綁給其他帳號。"""
        reading, account_id = self._reading, self._oauth_account_id
        if reading is None or account_id is None or reading.account_id != account_id:
            return None
        if any(a.account_id == account_id for a in accounts):
            return None
        current = FileCredentialStore(self._credentials).fingerprint()
        if current is None:
            return None
        return next((a for a in accounts if a.fingerprint == current and a.account_id is None), None)

    def _remember(self, accounts: Tuple[_Account, ...]) -> None:
        """額度快取的讀數歸屬到某個監看帳號時存進工具狀態：它換成待命帳號、甚至重新啟動後仍看得到。
        只留還有綁定的帳號；有變化才寫檔。"""
        if self._reading is not None:
            self._managed.remember_standby_reading(self._reading, {a.account_id for a in accounts if a.account_id})

    def _observe(self, accounts: Tuple[_Account, ...]) -> Tuple[Optional[_Account], bool]:
        """每輪的切換偵測。回傳當前憑證的監看帳號（未監看為 None），以及它的憑證快照是否已失效。
        當前指紋對不上任何憑證快照時，看 oauthAccount 的識別碼綁給哪份憑證快照：有就是那個帳號、快照已失效。
        上一輪的憑證指紋與失效標記存在工具狀態，重新啟動後接著比對；第一次運作也算一次切換。
        讀不到當前憑證（寫到一半、登出）時不動：不記錄，也不覆蓋上一輪的憑證指紋。"""
        current = FileCredentialStore(self._credentials).fingerprint()
        by_fp = {a.fingerprint: a for a in accounts if a.fingerprint}
        state = self._managed.read_observed()
        if state is None:  # 讀不到上一輪的觀測（例如短暫鎖住）：這一輪不判定
            return by_fp.get(current), False
        previous, invalid_snapshot = state.fingerprint, state.invalid_snapshot
        switched, account_id, left_account = False, None, None
        if current is not None and current != previous:
            previous_account = by_fp.get(previous) or by_fp.get(invalid_snapshot)  # 前一個當前憑證的監看帳號
            if current in by_fp:
                switched, account_id, left_account = True, by_fp[current].account_id, previous_account
            elif previous_account and previous_account.account_id \
                    and self._oauth_account_id == previous_account.account_id:
                invalid_snapshot = previous_account.fingerprint  # 憑證被輪替：同一個帳號，不算切換（ADR-0002）
            else:
                switched, account_id, left_account = True, self._oauth_account_id, previous_account
        elif current is not None and invalid_snapshot:
            flagged = by_fp.get(invalid_snapshot)
            if flagged is None:  # 憑證快照已移除或重新納管
                invalid_snapshot = None
            elif self._oauth_account_id not in (None, flagged.account_id):
                # Claude Code 先寫憑證、後寫 oauthAccount：上一輪看起來像輪替，其實是切到未監看帳號
                switched, account_id, left_account = True, self._oauth_account_id, flagged
        if switched or current in by_fp:
            invalid_snapshot = None
        if current is not None and current not in by_fp:
            stale = self._stale_snapshot(accounts)
            if stale is not None:  # 判定只看識別碼綁給誰，不看前一個當前憑證帳號；是不是切換已在上面判完
                invalid_snapshot = stale.fingerprint
        try:
            if switched:
                self._mark_lagging_before_switch(left_account, account_id)
                self._managed.append_switch(self._clock(), account_id)
            # 紀錄寫成、這裡寫失敗時，下一輪會再記一次同一個帳號；重複的一行不影響歸屬
            self._managed.write_observed(self._clock(), Observed(current or previous, invalid_snapshot))
        except OSError:
            pass  # 不推進上一輪的觀測，下一輪重試
        if current in by_fp:
            return by_fp[current], False
        flagged = by_fp.get(invalid_snapshot) if current is not None and invalid_snapshot else None
        return flagged, flagged is not None

    def _stale_snapshot(self, accounts: Tuple[_Account, ...]) -> Optional[_Account]:
        """oauthAccount 的識別碼綁定的憑證快照，沒有就是 None（識別碼讀不到、或沒綁給任何憑證快照）。
        綁了多份時只取到期最晚的那份；到期相同或都沒有到期時間，取帳號鍵排序在前的。"""
        account_id = self._oauth_account_id
        if account_id is None:
            return None
        bound = [a for a in accounts if a.account_id == account_id and a.fingerprint]
        # min 取排序最前：到期越晚越前（沒有到期時間墊底），再來是帳號鍵
        return min(bound, key=lambda a: (-a.expires_at.timestamp() if a.expires_at else float("inf"), a.key),
                   default=None)

    def _mark_lagging_before_switch(self, left_account: Optional[_Account], arrived_id: Optional[str]) -> None:
        """切換的那一輪：離開的帳號存著的讀數，不管距離上次掃描多久都重新判斷一次落後（切換前最後一分鐘的對話也算），
        結果與那份待命讀數一起存進工具狀態。切換之後的對話是新帳號的，不算。
        切換只偵測這一次，標記漏掉就補不回來：讀數檔讀不到、或寫不成都丟 OSError，由呼叫端下一輪整段重試。"""
        if left_account is None or left_account.account_id is None or left_account.account_id == arrived_id:
            return
        stored = self._managed.read_standby_readings()
        if stored is None:
            raise OSError("standby readings unreadable")
        reading = stored.get(left_account.account_id)
        if reading is not None:
            lagging = provider.transcripts_modified_after(self._transcripts, reading.observed_at.timestamp())
            self._managed.mark_standby_lagging(left_account.account_id, lagging)

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
        """設定檔改了才重讀。讀不懂時全部用預設，且不記修改時間，下一輪再讀；路徑欄位沿用上一次讀到的值。"""
        try:
            mtime = os.stat(self._paths.settings_file).st_mtime_ns
        except FileNotFoundError:
            self._settings_mtime, self._path_fields, self._settings_unreadable = None, (None, None), False
            self._apply_settings({})
            return
        except OSError:
            return
        if mtime == self._settings_mtime:
            return
        fields = read_settings(self._paths.settings_file)
        self._settings_unreadable = fields is None
        self._apply_settings(fields or {})
        if fields is not None:
            self._settings_mtime, self._path_fields = mtime, path_fields(fields)

    def _apply_settings(self, fields: dict) -> None:
        self._countdown_format = _countdown_format(fields.get(COUNTDOWN_FORMAT_FIELD))
        self._provider_settings, provider_invalid = provider.read_settings(fields)
        self._preferences, invalid = read_preferences(fields)
        self._invalid_settings = tuple(sorted((*invalid, *provider_invalid)))

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
        """當前憑證帳號在最前面，其餘監看帳號是待命帳號，依帳號鍵排序。
        active 為 None：當前憑證對不上任何憑證快照，當前憑證帳號是未監看帳號。"""
        if active:
            first = replace(self._active_card(active.key, Role.ACTIVE, active.account_id), snapshot_invalid=invalid)
        else:
            first = self._active_card(None, Role.UNWATCHED, self._oauth_account_id)
        return (self._with_snapshot_state(first, active),
                *(self._with_snapshot_state(self._standby_card(a), a) for a in accounts if a is not active))

    def _with_snapshot_state(self, card: Card, account: Optional[_Account]) -> Card:
        """剩不到設定的天數（預設 7 天）才警示：畫面的倒數一律捨去，門檻 7 天時顯示「7天0小時」不警示、
        「6天23小時」起才警示。每輪以當下時間與設定檔目前的值重算。
        順帶標出能不能切換：監看帳號分納管帳號與僅監看帳號，原因的優先順序見 WatchOnlyReason。"""
        if account is None:
            return card
        reason = self._watch_only_reason(account, card.snapshot_invalid)
        card = replace(card, switchable=reason is None, watch_only_reason=reason)
        if account.expires_at is None:
            return card
        warning = timedelta(days=self._provider_settings.expiry_warning_days)
        return replace(card, snapshot_expires_at=account.expires_at,
                       snapshot_expiring=account.expires_at - self._clock() < warning)

    def _watch_only_reason(self, account: _Account, invalid: bool) -> Optional[WatchOnlyReason]:
        """納管帳號回傳 None。快到期但還沒過期仍是納管帳號；憑證快照沒寫到期時間暫當無效資料，不算過期。"""
        if account.expires_at is not None and account.expires_at <= self._clock():
            return WatchOnlyReason.EXPIRED
        if invalid:
            return WatchOnlyReason.INVALID
        return None if account.has_account_info else WatchOnlyReason.NO_ACCOUNT_INFO

    def _active_card(self, key: Optional[str], role: Role, owner: Optional[str]) -> Card:
        """額度快取的識別碼等於 owner 才歸屬；否則是別的帳號的讀數（例如剛切換），讀數待更新。"""
        reading = self._reading
        if reading is None:
            return Card(key, role, ReadingState.NO_READING)
        if owner is None or reading.account_id != owner:
            return Card(key, role, ReadingState.PENDING)
        return self._reading_card(key, role, reading, self._lagging(reading))

    def _standby_card(self, account: _Account) -> Card:
        stored = self._managed.read_standby_readings() or {}
        reading = stored.get(account.account_id) if account.account_id else None
        if reading is None:
            return Card(account.key, Role.STANDBY, ReadingState.NO_READING)
        return self._reading_card(account.key, Role.STANDBY, reading, self._managed.standby_lagging(account.account_id))

    def _reading_card(self, key: Optional[str], role: Role, reading: provider.UsageReading, lagging: bool) -> Card:
        now = self._clock()
        breakdown = reading.weekly_breakdown
        if breakdown and breakdown.ends_at and not _counting(breakdown.ends_at, now):
            breakdown = None  # 週窗口已重置，舊的用量去向不再屬於計時中的這一週
        return Card(
            key, role, ReadingState.HAS_READING,
            reading_age=now - reading.observed_at,
            lagging=lagging,
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


def _countdown_format(value) -> CountdownFormat:
    """不認得的值用預設的「天＋時」。"""
    try:
        return CountdownFormat(value)
    except ValueError:
        return CountdownFormat.TWO_UNITS


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
