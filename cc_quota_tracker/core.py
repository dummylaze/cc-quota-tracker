"""核心：接收解析後的路徑與時鐘，對外只有 poll、add、remove、switch。"""
import os
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, FrozenSet, NamedTuple, Optional, Tuple, Union

from . import atomic
from . import claude_provider as provider
from . import usage_query
from .board import (Board, Card, CountdownFormat, Limit, Preferences, QueryFailure, QueryStatus, ReadingState, Role,
                    Severity, SwitchOutcome, SwitchRefusal, SwitchResult, SwitchStep, UsageQueryResult, WatchOnlyReason)
from .credstore import BytesCredentialStore, FileCredentialStore
from .managed_directory import (BindingsUnreadable, InvalidLabel, ManagedDirectory, NoCredential,  # noqa: F401
                                Observed, PermissionState, Synced, UnknownLabel, WritebackFailure, check_label,
                                same_login)
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


class _SwitchInputs(NamedTuple):
    """切換寫入之前讀好的東西：當前憑證、Claude Code 設定檔的文字、目標的憑證快照與帳號資訊。"""
    current: bytes
    settings: str
    target_credential: bytes
    target_account_info: dict


@dataclass(frozen=True)
class AddResult:
    account_key: str
    warnings: FrozenSet[AddWarning] = frozenset()


class Core:
    def __init__(self, paths: ResolvedPaths, clock: Callable[[], datetime], auto_query: bool = True,
                 sync_credentials: bool = True):
        """auto_query：poll 可以依設定自動查詢額度。只有常駐的視窗該開；命令列的 poll 一次就結束，不該留下查詢。
        sync_credentials：poll 做憑證同步、寫回憑證快照（ADR-0011）。只有視窗該開；命令列的 list 不改寫任何憑證快照。"""
        self._auto_query = auto_query
        self._sync_credentials = sync_credentials
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
        return self._poll(self._auto_query)

    def _poll(self, auto_query: bool) -> Board:
        self._managed.begin_round()
        self._poll_query()  # 先於 _refresh：查詢剛寫回的額度快取，這一輪就讀得到
        self._refresh()
        self._reread_settings()
        synced = self._sync()  # 先於綁定維護：寫回後舊憑證指紋的綁定，這一輪就清掉
        accounts = self._maintain_bindings(self._accounts())
        self._remember(accounts)
        active, invalid = self._observe(accounts, synced)
        reading = self._reading
        cards = self._cards(accounts, active, invalid)
        if auto_query:
            self._maybe_auto_query(cards[0])  # 在建看板之前：這一輪啟動的查詢，這一輪的看板就顯示進行中
        self._managed.end_round()
        previous_refusal, previous_expires_at = self._previous_switch()
        return Board(cards=cards,
                     schema_changed=self._mismatch_rounds >= SCHEMA_CHANGE_ROUNDS,
                     last_reading_at=reading.observed_at if reading else None,
                     watched_accounts=tuple(a.key for a in accounts),
                     wrong_location_suspected=self._source_missing and self._paths.claude_source is PathSource.DEFAULT,
                     restart_required=self._path_fields != self._paths.path_fields,
                     settings_unreadable=self._settings_unreadable,
                     as_of=self._clock(), countdown_format=self._countdown_format,
                     preferences=self._preferences, invalid_settings=self._invalid_settings,
                     usage_query=self._query_status(), permissions_untightened=self._managed.untightened_warning_lit(),
                     restorable=previous_refusal is None, previous_expires_at=previous_expires_at)

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
        if (not settings.auto_usage_query or self._query is not None
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

    def switch(self, label: str, on_step: Optional[Callable[[SwitchStep], None]] = None) -> SwitchResult:
        """切換到帳號標籤 label：寫入它的憑證快照，Claude Code 設定檔只改帳號資訊那一個鍵（ADR-0006）。
        先跑一輪 poll 取得與畫面相同的分類，依序：檢查目標、同步當前憑證、替舊帳號查詢額度（跳過的條件見
        _old_account_needs_query）、保存切換前憑證、寫入、記切換紀錄、替新帳號查詢額度兼作驗證。
        寫入之前的任何一步不成就拒絕，當前憑證與 Claude Code 設定檔都不動（查詢只讓 Claude Code 寫它自己的額度快取）。
        不檢查刷新鎖檔，也不跟其他程序互鎖。這是同步呼叫：兩次查詢最久各等 usage_query.TIMEOUT，GUI 要放在背景執行。
        on_step：每個步驟開始之前呼叫一次（SwitchStep）；目標檢查就被拒絕時一次都不呼叫。呼叫發生在切換所在的執行緒。"""
        return self._run_switch(lambda board: self._switch_refusal(label, board),
                                lambda: self._managed.switch_target(label), on_step)

    def restore_previous(self, on_step: Optional[Callable[[SwitchStep], None]] = None) -> SwitchResult:
        """還原上一次切換：把切換前憑證寫回當前憑證，帳號資訊一起回到切換前。還原本身也是一次切換——同樣先同步、
        保存當下的憑證成為新的切換前憑證、記切換紀錄、替還原後的帳號查詢額度——所以再還原一次會回到剛才的帳號。
        沒有可還原的切換前憑證、或它已過期就拒絕，當前憑證與 Claude Code 設定檔都不動。其餘同 switch。"""
        return self._run_switch(self._restore_refusal, self._managed.pre_switch_target, on_step)

    def preflight_switch(self, label: Optional[str]) -> Tuple[Board, Optional[SwitchResult]]:
        """切換（label 是 None 就是還原上一次切換）之前的預判：跑一輪不自動查詢的 poll，回傳那一輪的看板，以及目標檢查
        會不會拒絕（會就是拒絕的結果值，不會是 None）。不查詢、不做任何切換的寫入（當前憑證、Claude Code 設定檔、切換前憑證
        都不動）；poll 本來就會做的維護（綁定檔清理等）照舊，所以不是純讀取。命令列拿它在詢問之前就擋掉問了也只會被拒絕的
        請求，並取得確認內容用的看板。真正切換時核心會再判斷一次，以那一次為準。"""
        board = self._poll(auto_query=False)
        return board, self._restore_refusal(board) if label is None else self._switch_refusal(label, board)

    def _run_switch(self, check: Callable[[Board], Optional[SwitchResult]],
                    load_target: Callable[[], Optional[Tuple[bytes, dict]]],
                    on_step: Optional[Callable[[SwitchStep], None]]) -> SwitchResult:
        """切換與還原共用的流程；差別只在怎麼檢查目標（check）與寫進去的憑證與帳號資訊從哪來（load_target）。"""
        step = on_step or (lambda _: None)
        board = self._poll(auto_query=False)
        refused = check(board)
        if refused is not None:
            return refused
        step(SwitchStep.SYNC)
        prepared = self._prepare_switch(load_target)
        if isinstance(prepared, SwitchRefusal):
            return SwitchResult(SwitchOutcome.REFUSED, prepared)
        old_query_failed = False
        if self._old_account_needs_query(board.cards[0]):
            step(SwitchStep.QUERY_OLD)
            old_query_failed = self._switch_query().failure is not None
            # 讀數落後的舊帳號：新讀數趁還沒切走就存成它的待命讀數，切換偵測才會拿它判斷離開時落不落後
            self._refresh()
            self._remember(self._accounts())
            # 查詢是 Claude Code 在用當前憑證跑的，它可能順便刷新了憑證：同步與切換前憑證都要拿刷新之後的版本
            prepared = self._prepare_switch(load_target)
            if isinstance(prepared, SwitchRefusal):
                return SwitchResult(SwitchOutcome.REFUSED, prepared, old_account_query_failed=old_query_failed)
        step(SwitchStep.WRITE)
        result = replace(self._write_switch(prepared), old_account_query_failed=old_query_failed)
        if result.outcome is not SwitchOutcome.SWITCHED:
            return result
        step(SwitchStep.QUERY_NEW)
        verified = self._switch_query()
        if verified.failure is None:
            return result
        return replace(result, outcome=SwitchOutcome.VERIFY_FAILED, verify_failure=verified)

    def _switch_refusal(self, label: str, board: Board) -> Optional[SwitchResult]:
        """依這一輪看板的分類檢查目標；能切換回傳 None。"""
        key = f"{provider.PROVIDER}:{label}"
        card = next((c for c in board.cards if c.account_key == key), None)
        if card is None:
            return SwitchResult(SwitchOutcome.REFUSED, SwitchRefusal.UNKNOWN_LABEL)
        if card.role is Role.ACTIVE:
            return SwitchResult(SwitchOutcome.REFUSED, SwitchRefusal.ALREADY_ACTIVE)
        if not card.switchable:
            return SwitchResult(SwitchOutcome.REFUSED, SwitchRefusal.WATCH_ONLY, card.watch_only_reason,
                                card.writeback_failures)
        return None

    def _restore_refusal(self, board: Board) -> Optional[SwitchResult]:
        """檢查切換前憑證；能還原回傳 None。"""
        refusal, _ = self._previous_switch()
        return None if refusal is None else SwitchResult(SwitchOutcome.REFUSED, refusal)

    def _previous_switch(self) -> Tuple[Optional[SwitchRefusal], Optional[datetime]]:
        """切換前憑證的狀態（只讀）：不能還原的原因（能還原是 None），以及它的 refreshToken 到期時間。
        到期的判法同憑證快照：沒寫到期時間不算過期。看板的「能不能還原」與還原的拒絕檢查共用這一份。"""
        try:
            target = self._managed.pre_switch_target()
        except OSError:
            return SwitchRefusal.UNREADABLE, None
        store = BytesCredentialStore(target[0]) if target else None
        if store is None or store.fingerprint() is None:
            return SwitchRefusal.NO_PREVIOUS, None
        credential = store.read()
        expires = credential.refresh_token_expires_at if credential else None
        if expires is not None and expires <= self._clock():
            return SwitchRefusal.PREVIOUS_EXPIRED, expires
        return None, expires

    def _prepare_switch(self, load_target: Callable[[], Optional[Tuple[bytes, dict]]]
                        ) -> Union[_SwitchInputs, SwitchRefusal]:
        """寫入之前要讀的東西與不能寫的條件：讀得到當前憑證、Claude Code 設定檔與目標的憑證與帳號資訊，切走前的同步成功。
        以位元組讀再解碼：read_text 會把 CRLF 換成 LF，寫回時就不是逐字保留。"""
        try:
            current = self._credentials.read_bytes()
            settings = self._source.read_bytes().decode("utf-8")
            provider.with_account_info(settings, {})  # 先確認改得了這個鍵；寫入時會重讀
            target = load_target()
        except (OSError, ValueError):
            return SwitchRefusal.UNREADABLE
        if target is None or BytesCredentialStore(current).fingerprint() is None:
            return SwitchRefusal.UNREADABLE
        if not self._synced_before_switch(current):
            return SwitchRefusal.SYNC_FAILED
        return _SwitchInputs(current, settings, *target)

    def _write_switch(self, prepared: _SwitchInputs) -> SwitchResult:
        """保存切換前憑證、寫入目標的憑證與帳號資訊、記切換紀錄。"""
        try:
            replaced = self._managed.save_pre_switch(prepared.current, provider.account_info(prepared.settings))
        except OSError:
            return SwitchResult(SwitchOutcome.REFUSED, SwitchRefusal.UNWRITABLE)
        try:
            atomic.write_atomic(self._credentials, prepared.target_credential)
        except OSError:  # 拒絕不丟掉上一次切換的還原點
            self._managed.restore_pre_switch(replaced)
            return SwitchResult(SwitchOutcome.REFUSED, SwitchRefusal.UNWRITABLE)
        try:  # 讀出到寫回之間盡量短：只用這時讀到的版本，切換開始後才寫進去的內容一併保留
            text = self._source.read_bytes().decode("utf-8")
            atomic.write_atomic(self._source,
                                provider.with_account_info(text, prepared.target_account_info).encode("utf-8"))
        except (OSError, ValueError):
            return SwitchResult(SwitchOutcome.WRITE_FAILED)
        self._record_switch()
        return SwitchResult(SwitchOutcome.SWITCHED)

    def _old_account_needs_query(self, active: Card) -> bool:
        """切換前要不要替舊帳號（當前憑證帳號）查詢額度：它是有綁定的監看帳號，而且讀數落後或待更新
        （與自動查詢同一條規則），查了它變成待命帳號之後留下的讀數才是新的。未監看帳號沒有待命讀數可更新，
        沒有綁定的帳號存不了待命讀數，沒有讀數或讀數沒落後的不必查；這些都跳過。"""
        if active.role is not Role.ACTIVE or not (active.lagging or active.reading_state is ReadingState.PENDING):
            return False
        return any(a.key == active.account_key and a.account_id for a in self._accounts())

    def _switch_query(self) -> UsageQueryResult:
        """切換觸發的同步查詢（ADR-0010 修訂段）：不啟動手動查詢的冷卻，但算進自動查詢的間隔。失敗只由切換的
        結果值回報，不記進看板的查詢狀態；成功才像其他查詢一樣讓連續失敗歸零、清掉上一次失敗。"""
        self._last_query_started = self._clock()
        result = self.query_usage()
        if result.failure is None:
            self._consecutive_failures, self._last_query_failure = 0, None
        return result

    def _synced_before_switch(self, current: bytes) -> bool:
        """切走前同步一次（命令列的 poll 不同步，這裡一定要做）。沒寫成以結果判斷，不靠例外：同步之後，
        當前憑證仍對不上任何憑證快照、卻有唯一一份出自同一次登入的，就是沒寫成（含重試中與已停止重試）。
        當前憑證帳號是未監看帳號、或快照已失效（沒有同一次登入的快照）時沒有東西要同步。"""
        self._managed.sync_snapshot(current)
        store = BytesCredentialStore(current)
        fingerprint, credential = store.fingerprint(), store.read()
        expires = credential.refresh_token_expires_at if credential else None
        accounts = self._accounts()
        if any(a.fingerprint == fingerprint for a in accounts):
            return True
        return len([a for a in accounts if same_login(a.expires_at, expires)]) != 1

    def _record_switch(self) -> None:
        """寫入後馬上跑一次切換偵測：以寫入時間追加切換紀錄、推進上一輪的觀測，之後的 poll 就不會再記同一次切換。
        離開的帳號的讀數也照常判斷落後。紀錄寫不成時由下一輪 poll 補記。"""
        self._refresh()
        self._observe(self._accounts(), None)

    def _accounts(self) -> Tuple[_Account, ...]:
        return tuple(_Account(f"{provider.PROVIDER}:{a.label}", a.fingerprint, a.account_id, a.expires_at,
                              a.has_account_info)
                     for a in self._managed.list_accounts())

    def _sync(self) -> Optional[Synced]:
        """憑證同步：把當前憑證寫回出自同一次登入的那份憑證快照。讀不到當前憑證，這一輪就不寫，下一輪再試；
        寫不成時由納管目錄記下寫回失敗與重試次數。"""
        if not self._sync_credentials:
            return None
        try:
            return self._managed.sync_snapshot(self._credentials.read_bytes())
        except OSError:
            return None

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

    def _observe(self, accounts: Tuple[_Account, ...],
                 synced: Optional[Synced]) -> Tuple[Optional[_Account], FrozenSet[str]]:
        """每輪的切換偵測。回傳當前憑證的監看帳號（未監看為 None），以及失效的憑證快照的憑證指紋。
        當前憑證帳號依序認：憑證指紋相同的憑證快照、出自同一次登入但還沒寫回的唯一一份憑證快照（命令列不同步、
        或寫回失敗）、帳號資訊的識別碼綁定的憑證快照（找不到同一次登入的證據，標為失效）。
        失效旗標分兩段：當前憑證帳號的那份是暫定的，帳號資訊在同一份憑證下改變時跟著改判（/login 先寫憑證、
        後寫帳號資訊）；切換離開時轉為持久，保留到重新納管（憑證指紋換掉）為止。
        上一輪的觀測存在工具狀態，重新啟動後接著比對；第一次運作也算一次切換。
        讀不到當前憑證（寫到一半、登出）時不動：不記錄，也不覆蓋上一輪的憑證指紋。"""
        store = FileCredentialStore(self._credentials)
        current, credential = store.fingerprint(), store.read()
        expires = credential.refresh_token_expires_at if credential else None
        by_fp = {a.fingerprint: a for a in accounts if a.fingerprint}
        # 同一次登入、還沒寫回的憑證快照：有就是找到了同一次登入的證據；唯一一份時就是當前憑證帳號
        same_login_snapshots = [a for a in accounts if same_login(a.expires_at, expires)] if current not in by_fp else []
        unsynced = same_login_snapshots[0] if len(same_login_snapshots) == 1 else None
        state = self._managed.read_observed()
        if state is None:  # 讀不到上一輪的觀測（例如短暫鎖住）：這一輪不判定
            return by_fp.get(current) or unsynced, frozenset()
        previous, provisional, flagged = state.fingerprint, state.pending_invalid, set(state.kept_invalid)
        if synced is not None:  # 寫回換掉了憑證快照的憑證指紋：上一輪記的舊指紋跟著換
            previous, provisional = synced.follow(previous), synced.follow(provisional)
            flagged = {fp for fp in map(synced.follow, flagged) if fp}
        switched, account_id, left_account = False, None, None
        if current is not None and current != previous:
            previous_account = by_fp.get(previous) or by_fp.get(provisional)  # 前一個當前憑證的監看帳號
            if same_login(state.expires_at, expires) or (previous_account and by_fp.get(current) is previous_account):
                pass  # 同一次登入的輪替（例如命令列看過、看板還沒寫回），或寫回後回到同一份憑證快照：不算切換
            elif current in by_fp:
                switched, account_id, left_account = True, by_fp[current].account_id, previous_account
            elif previous_account and previous_account.account_id \
                    and self._oauth_account_id == previous_account.account_id:
                pass  # 憑證指紋變了、帳號資訊仍是同一個帳號：不算切換（ADR-0009）
            else:
                switched, account_id, left_account = True, self._oauth_account_id, previous_account
            if switched and provisional:
                flagged.add(provisional)  # 切換離開：旗標保留到重新納管，換到別的帳號也不熄滅
        elif current is not None and provisional:
            pending = by_fp.get(provisional)
            if pending is not None and self._oauth_account_id not in (None, pending.account_id):
                # Claude Code 先寫憑證、後寫 oauthAccount：上一輪看起來像同一個帳號重新登入，其實是換了帳號
                switched, account_id, left_account = True, self._oauth_account_id, pending
        if switched or current in by_fp or same_login_snapshots or not provisional or provisional not in by_fp:
            provisional = None  # 換了帳號、找到同一次登入的證據、或憑證快照已移除或重新納管
        if current is not None and current not in by_fp and not same_login_snapshots:
            stale = self._stale_snapshot(accounts)
            if stale is not None:  # 判定只看識別碼綁給誰，不看前一個當前憑證帳號；是不是切換已在上面判完
                provisional = stale.fingerprint
        if None not in (a.fingerprint for a in accounts):  # 憑證快照都讀得出指紋才修剪，免得鎖住的那份被洗掉旗標
            flagged &= set(by_fp)
        try:
            if switched:
                self._mark_lagging_before_switch(left_account, account_id)
                self._managed.append_switch(self._clock(), account_id)
            # 紀錄寫成、這裡寫失敗時，下一輪會再記一次同一個帳號；重複的一行不影響歸屬
            self._managed.write_observed(self._clock(), Observed(
                current or previous, provisional, tuple(flagged), expires if current else state.expires_at))
        except OSError:
            pass  # 不推進上一輪的觀測，下一輪重試
        invalid = frozenset(flagged | {provisional} if provisional else flagged)
        if current in by_fp:
            return by_fp[current], invalid
        if current is not None and unsynced:
            return unsynced, invalid
        if current is not None and provisional:
            return by_fp[provisional], invalid
        return None, invalid

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

    def _cards(self, accounts: Tuple[_Account, ...], active: Optional[_Account],
               invalid: FrozenSet[str]) -> Tuple[Card, ...]:
        """當前憑證帳號在最前面，其餘監看帳號是待命帳號，依帳號鍵排序。
        active 為 None：當前憑證對不上任何憑證快照，當前憑證帳號是未監看帳號。invalid 是失效的憑證快照的憑證指紋。"""
        if active:
            first = self._active_card(active.key, Role.ACTIVE, active.account_id)
        else:
            first = self._active_card(None, Role.UNWATCHED, self._oauth_account_id)
        failures = self._managed.writeback_failures()
        return (self._with_snapshot_state(first, active, invalid, failures),
                *(self._with_snapshot_state(self._standby_card(a), a, invalid, failures)
                  for a in accounts if a is not active))

    def _with_snapshot_state(self, card: Card, account: Optional[_Account], invalid: FrozenSet[str],
                             failures: Dict[str, WritebackFailure]) -> Card:
        """剩不到設定的天數（預設 7 天）才警示：畫面的倒數一律捨去，門檻 7 天時顯示「7天0小時」不警示、
        「6天23小時」起才警示。每輪以當下時間與設定檔目前的值重算。
        順帶標出能不能切換：監看帳號分納管帳號與僅監看帳號，原因的優先順序見 WatchOnlyReason。"""
        if account is None:
            return card
        card = replace(card, snapshot_invalid=account.fingerprint in invalid)
        failure = failures.get(account.fingerprint) if account.fingerprint else None
        reason = self._watch_only_reason(account, card.snapshot_invalid, failure)
        card = replace(card, switchable=reason is None, watch_only_reason=reason,
                       writeback_failures=failure.failures if failure and reason is WatchOnlyReason.WRITEBACK_RETRYING
                       else None)
        if account.expires_at is None:
            return card
        warning = timedelta(days=self._provider_settings.expiry_warning_days)
        return replace(card, snapshot_expires_at=account.expires_at,
                       snapshot_expiring=account.expires_at - self._clock() < warning)

    def _watch_only_reason(self, account: _Account, invalid: bool,
                           failure: Optional[WritebackFailure]) -> Optional[WatchOnlyReason]:
        """納管帳號回傳 None。快到期但還沒過期仍是納管帳號；憑證快照沒寫到期時間暫當無效資料，不算過期。"""
        if account.expires_at is not None and account.expires_at <= self._clock():
            return WatchOnlyReason.EXPIRED
        if invalid:
            return WatchOnlyReason.INVALID
        if failure is not None:
            return WatchOnlyReason.WRITEBACK_STOPPED if failure.stopped else WatchOnlyReason.WRITEBACK_RETRYING
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
