"""token 報表的資料：把對話紀錄的用量依切換紀錄歸屬到帳號，算成嵌進 HTML 的報表資料（ADR-0013）。

歸屬規則（spec〈歸屬規則〉）：時間 t 的用量歸給「t 之前（含）最後一筆切換紀錄」切到的帳號識別碼。
未歸屬：第一筆切換紀錄之前；切到帳號未知（識別碼為空）之後；t 之後的下一筆切換紀錄帶有上一次運作時間 P、且 P ≤ t
（本工具停止運作期間發生了切換，P 到切換偵測到的時間之間不知道是哪個帳號）。

報表資料不含帳號識別碼與 email：帳號只以不透明的鍵（a1、a2…）和帳號標籤出現。

資料來源是用量帳本加上最近的對話紀錄：帳本記著「through 之前的小時」，這些小時一律取帳本，對話紀錄只算 through 之後的小時
（沒入帳的最近 24 小時，遲到的紀錄因此不會漏）。兩邊的小時互不重疊，不會重複計算。"""
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import i18n
from .managed_directory import ManagedDirectory, SwitchLog, SwitchRecord, WatchedAccount
from .transcripts import Scan, Usage
from .usage_ledger import TOKEN_FIELDS, LedgerCell, LedgerFailure, LedgerRead, LedgerStatus

SCHEMA = 1  # 報表資料的版本；之後加欄位不升版，改變既有欄位的意思才升
RANGES = (("7d", 7), ("30d", 30), ("all", None))  # 區間：近 N 個本機的日（含今天），None＝全部
LEDGER_DELAY = timedelta(hours=24)  # 過了這麼久的小時才入帳；更近的每次從對話紀錄重算，遲到的紀錄才不會漏
_HourKey = Tuple[datetime, Optional[str], str]  # UTC 小時、帳號識別碼（None＝未歸屬）、模型


class ReportWarning(Exception):
    """報表上的示警，寫進錯誤紀錄用：訊息就是印給使用者看的那一句。"""


def local_zone() -> Optional[tzinfo]:
    """「日」的切法用的時區；None 是系統的本機時區（依各日期套用日光節約時間）。測試換成固定時區。"""
    return None


class Attribution:
    """把時間對到帳號識別碼；None 是未歸屬。"""

    def __init__(self, switches: Sequence[SwitchRecord]):
        kept: List[SwitchRecord] = []
        for record in switches:  # 已依時間排序
            # 切換紀錄寫成、觀測檔寫失敗時，下一輪會重記同一筆（帶同一個上一次運作時間）：留第一筆，
            # 否則兩筆之間的幾秒會被下一筆的未歸屬時段蓋住
            if (kept and record.last_run_at is not None
                    and (kept[-1].account_id, kept[-1].last_run_at) == (record.account_id, record.last_run_at)):
                continue
            kept.append(record)
        self._records = kept
        self._times = [r.at for r in kept]

    def account_at(self, t: datetime) -> Optional[str]:
        index = bisect_right(self._times, t)
        if index == 0:
            return None
        following = self._records[index] if index < len(self._records) else None
        if following is not None and following.last_run_at is not None and following.last_run_at <= t:
            return None
        return self._records[index - 1].account_id


def build_data(scan: Scan, switch_log: SwitchLog, accounts: Sequence[WatchedAccount], now: datetime,
               lang: str, ledger: LedgerRead, status: LedgerStatus) -> dict:
    zone = local_zone()
    attribution = Attribution(switch_log.records)
    keys, labels = _account_keys(switch_log.records, accounts, lang, (c.account_id for c in ledger.cells))

    # 先收成 UTC 小時（帳本就是這個粒度），再把小時換算成本機的日。小時整個歸給「小時起點」所在的日：
    # 半小時偏移的時區（+5:30、+5:45）裡，一個 UTC 小時會跨本機的日界，那半小時會歸給前一天；這是帳本粒度的代價
    live = [u for u in scan.usages if ledger.through is None or _hour_of(u.at) >= ledger.through]
    hours = _hourly(live, attribution)
    for cell in ledger.cells:
        _add(hours[(cell.hour, cell.account_id, cell.model)], cell.counts)
    days: Dict[Tuple[str, Optional[str], str], List[int]] = defaultdict(lambda: [0] * len(TOKEN_FIELDS))
    for (hour, account_id, model), counts in hours.items():
        _add(days[(hour.astimezone(zone).date().isoformat(), keys[account_id] if account_id else None, model)], counts)
    rank: Dict[Optional[str], int] = {key: i for i, key in enumerate(keys.values())}  # 帳號鍵的排序；未歸屬排最後
    rank[None] = len(rank)
    rows = [dict(day=day, account=account, model=model, **dict(zip(TOKEN_FIELDS, counts)))
            for (day, account, model), counts in sorted(
                days.items(), key=lambda kv: (kv[0][0], rank[kv[0][1]], kv[0][2]))]

    today = now.astimezone(zone).date()
    cutoff = next((r.at for r in switch_log.records if r.last_run_at is not None), None)
    earliest = min([u.at for u in live] + [c.hour for c in ledger.cells], default=None)
    return {
        "schema": SCHEMA,
        "generatedAt": now.isoformat(),
        "today": today.isoformat(),
        "language": lang,
        "accounts": [{"key": key, "label": labels[account_id]} for account_id, key in keys.items()
                     if any(r["account"] == key for r in rows)],
        "rows": rows,
        # 用量帳本：最早有資料的時間、最後一次成功更新的時間（沒更新過是 null）；更新失敗的原因在 notices
        "ledger": {"earliest": earliest.isoformat() if earliest else None,
                   "updatedAt": status.updated_at.isoformat() if status.updated_at else None},
        # 開始記錄停機時段的那一天（本機）；沒有任何一筆帶上一次運作時間時是 null
        "downtimeRecordedSince": cutoff.astimezone(zone).date().isoformat() if cutoff else None,
        "summary": {name: _summary(rows, today, span, zone, cutoff, earliest, rank) for name, span in RANGES},
        "notices": _notices(scan, switch_log, ledger, status, lang),
    }


def _hour_of(at: datetime) -> datetime:
    return at.replace(minute=0, second=0, microsecond=0)


def _hourly(usages: Iterable[Usage], attribution: Attribution) -> Dict[_HourKey, List[int]]:
    hours: Dict[_HourKey, List[int]] = defaultdict(lambda: [0] * len(TOKEN_FIELDS))
    for u in usages:
        _add(hours[(_hour_of(u.at), attribution.account_at(u.at), u.model)],
             (u.input, u.output, u.cache_write_5m, u.cache_write_1h, u.cache_read))
    return hours


def update_ledger(managed: ManagedDirectory, scan: Scan, switch_log: SwitchLog, now: datetime) -> LedgerStatus:
    """把已經過去 24 小時以上、帳本裡還沒有的小時追加進帳本，回傳更新後的狀態。
    別的行程正在寫（等不到鎖）是跳過這次，不算失敗，狀態維持原樣。失敗時帳本不變，原因記進狀態（之後成功才清掉）。
    對話紀錄有檔案讀不到時照樣入帳（報表頂端另外示警）：讀不到的檔案可能永遠讀不到，為了它擋住整個帳本，
    Claude Code 刪掉舊紀錄後所有用量都會漏掉，比少一個檔案的用量嚴重得多。"""
    previous = managed.read_ledger_status()
    through = _hour_of(now - LEDGER_DELAY)
    attribution = Attribution(switch_log.records)

    def plan(read: LedgerRead) -> Optional[Tuple[List[LedgerCell], datetime]]:
        if read.through is not None and through <= read.through:
            return None
        fresh = [u for u in scan.usages if (read.through is None or _hour_of(u.at) >= read.through)
                 and _hour_of(u.at) < through]
        cells = [LedgerCell(hour, account_id, model, tuple(counts)) for (hour, account_id, model), counts in sorted(
            _hourly(fresh, attribution).items(), key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2]))]
        if not cells:
            return None  # 沒有用量就不前進：什麼都沒有可以保住
        return cells, through

    failure: Optional[LedgerFailure] = None
    try:
        if managed.update_usage_ledger(plan):
            return previous
    except OSError as e:
        failure = LedgerFailure("io", e.strerror or type(e).__name__)  # 不用 str(e)：它帶著含使用者名稱的路徑
    status = LedgerStatus(previous.updated_at if failure else now, failure)
    try:
        managed.write_ledger_status(status)
    except OSError as e:
        if failure is None:
            status = LedgerStatus(previous.updated_at, LedgerFailure("io", e.strerror or type(e).__name__))
    return status


def _account_keys(switches: Sequence[SwitchRecord], accounts: Sequence[WatchedAccount], lang: str,
                  ledgered: Iterable[Optional[str]] = ()) -> Tuple[Dict[str, str], Dict[str, str]]:
    """帳號識別碼 → 不透明的鍵（依在切換紀錄首次出現的順序）、帳號識別碼 → 顯示的標籤。
    標籤取自現有的綁定；查不到的是未監看帳號，依首次出現的順序編號（編號跨次報表固定的規則在 token-report/05）。"""
    by_id: Dict[str, str] = {}
    for account in accounts:
        if account.account_id and account.account_id not in by_id:
            by_id[account.account_id] = account.label
    keys: Dict[str, str] = {}
    labels: Dict[str, str] = {}
    unwatched = 0
    # 帳本裡的帳號識別碼接在切換紀錄之後（切換紀錄讀不到時，帳本裡的帳號照樣要有鍵）
    for account_id in [r.account_id for r in switches] + list(ledgered):
        if account_id and account_id not in keys:
            keys[account_id] = f"a{len(keys) + 1}"
            if account_id in by_id:
                labels[account_id] = by_id[account_id]
            else:
                unwatched += 1
                labels[account_id] = i18n.text(lang, "report.account.unwatched", n=unwatched)
    return keys, labels


def _summary(rows: List[dict], today: date, span: Optional[int], zone: Optional[tzinfo],
             cutoff: Optional[datetime], earliest: Optional[datetime], rank: Dict[Optional[str], int]) -> dict:
    first = today - timedelta(days=span - 1) if span else None
    selected = [r for r in rows if first is None or r["day"] >= first.isoformat()]
    per_account: Dict[Optional[str], List[int]] = defaultdict(lambda: [0] * len(TOKEN_FIELDS))
    for r in selected:
        _add(per_account[r["account"]], [r[field] for field in TOKEN_FIELDS])
    # 用量多的在前，未歸屬排最後（有列就一定有用量：列是從用量算出來的）
    ranked = sorted(per_account.items(), key=lambda kv: (kv[0] is None, -sum(kv[1]), rank[kv[0]]))
    total = [sum(counts[i] for counts in per_account.values()) for i in range(len(TOKEN_FIELDS))]
    start: Optional[datetime] = earliest
    if first is not None:
        start = (datetime.combine(first, time.min, tzinfo=zone) if zone
                 else datetime.combine(first, time.min).astimezone())
    return {
        "from": first.isoformat() if first else None,
        "accounts": [dict(account=account, **_figures(counts)) for account, counts in ranked],
        "total": _figures(total),
        "downtimeUnrecognized": bool(selected) and (cutoff is None or (start is not None and start < cutoff)),
    }


def _add(cell: List[int], counts: Sequence[int]) -> None:
    for i, n in enumerate(counts):
        cell[i] += n


def _figures(counts: List[int]) -> dict:
    figures: dict = dict(zip(TOKEN_FIELDS, counts))
    figures["cacheHitRatio"] = cache_hit_ratio(figures)
    return figures


def cache_hit_ratio(figures: dict) -> Optional[float]:
    """cache 讀取 ÷（input＋cache 寫入＋cache 讀取），output 不計（詞彙表）；分母為 0 時沒有比例。"""
    denominator = figures["input"] + figures["cacheWrite5m"] + figures["cacheWrite1h"] + figures["cacheRead"]
    return figures["cacheRead"] / denominator if denominator else None


def _notices(scan: Scan, switch_log: SwitchLog, ledger: LedgerRead, status: LedgerStatus, lang: str) -> List[dict]:
    notices = []
    if scan.mismatched:
        notices.append({"kind": "schemaMismatch", "count": scan.mismatched})
    if scan.unreadable_files:
        notices.append({"kind": "transcriptUnreadable", "count": scan.unreadable_files})
    if switch_log.unreadable:
        notices.append({"kind": "switchLogUnreadable"})
    elif switch_log.skipped:
        notices.append({"kind": "switchLogSkipped", "count": switch_log.skipped})
    if status.failure:
        notices.append({"kind": "ledgerUpdateFailed", "reason": failure_reason(lang, status.failure)})
    if ledger.skipped:
        notices.append({"kind": "ledgerSkipped", "count": ledger.skipped})
    return notices


def failure_reason(lang: str, failure: LedgerFailure) -> str:
    """帳本更新失敗的原因，給橫幅與錯誤紀錄用的一句話。"""
    return failure.detail or i18n.text(lang, "report.ledger.reason.unknown")
