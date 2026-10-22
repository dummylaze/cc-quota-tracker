"""token 報表的資料：把對話紀錄的用量依切換紀錄歸屬到帳號，算成嵌進 HTML 的報表資料（ADR-0013）。

歸屬規則（spec〈歸屬規則〉）：時間 t 的用量歸給「t 之前（含）最後一筆切換紀錄」切到的帳號識別碼。
未歸屬：第一筆切換紀錄之前；切到帳號未知（識別碼為空）之後；t 之後的下一筆切換紀錄帶有上一次運作時間 P、且 P ≤ t
（本工具停止運作期間發生了切換，P 到切換偵測到的時間之間不知道是哪個帳號）。

報表資料不含帳號識別碼與 email：帳號只以不透明的鍵（a1、a2…）和帳號標籤出現。
帳號標籤取自「帳號識別碼 → 最後用過的標籤」的對照（納管目錄裡，每次產生報表時依現有的綁定更新）：憑證快照移除後綁定跟著清掉，
歷史用量仍用最後的標籤；從沒納管過的帳號依首次出現的順序編成「未監看帳號 n」，編號存在同一份對照裡，之後不變。

資料來源是用量帳本加上最近的對話紀錄：帳本記著「through 之前的小時」，這些小時一律取帳本，對話紀錄只算 through 之後的小時
（沒入帳的最近 24 小時，遲到的紀錄因此不會漏）。兩邊的小時互不重疊，不會重複計算。

金額在產生報表時用當下的單價表算（prices），不寫進帳本。單價表沒有的模型、或帶有計費因素（單價表無法計價）的格子，
金額是未知：該格只留原因，合計只加算得出的部分，並列出原因。"""
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from . import i18n, prices
from .managed_directory import AccountLabels, ManagedDirectory, SwitchLog, SwitchRecord, WatchedAccount
from .prices import PriceTable
from .tokens import ACCOUNT_COLORS
from .transcripts import Scan, Usage
from .usage_ledger import TOKEN_FIELDS, LedgerCell, LedgerFailure, LedgerRead, LedgerStatus

SCHEMA = 1  # 報表資料的版本；之後加欄位不升版，改變既有欄位的意思才升
RANGES = (("7d", 7), ("30d", 30), ("all", None))  # 區間：近 N 個本機的日（含今天），None＝全部
LEDGER_DELAY = timedelta(hours=24)  # 過了這麼久的小時才入帳；更近的每次從對話紀錄重算，遲到的紀錄才不會漏
_HourKey = Tuple[datetime, Optional[str], str, Tuple[str, ...]]  # UTC 小時、帳號識別碼（None＝未歸屬）、模型、計費因素
_DayModels = Dict[str, Dict[Optional[str], Dict[str, "_Tally"]]]  # 日 → 帳號鍵（None＝未歸屬）→ 模型 → 一格


class _Tally:
    """一格的 token 數與金額：cost 只加算得出的部分（沒有任何部分算得出是 None），算不出的原因依出現順序、不重複。"""

    def __init__(self):
        self.counts = [0] * len(TOKEN_FIELDS)
        self.cost: Optional[float] = None
        self.unknown: List[str] = []

    def add(self, counts: Sequence[int], cost: Optional[float], unknown: Iterable[str]) -> None:
        _add(self.counts, counts)
        if cost is not None:
            self.cost = (self.cost or 0.0) + cost
        self.unknown.extend(reason for reason in unknown if reason not in self.unknown)

    def merge(self, other: "_Tally") -> None:
        self.add(other.counts, other.cost, other.unknown)


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


class Labelling(NamedTuple):
    """帳號識別碼 → 報表上顯示的帳號標籤，與這一份對照有沒有存好（讀不到或寫不成是 False，報表頂端示警）。"""
    shown: Dict[str, str]
    saved: bool


def build_data(scan: Scan, switch_log: SwitchLog, labelling: Labelling, now: datetime,
               lang: str, ledger: LedgerRead, status: LedgerStatus, table: PriceTable) -> dict:
    zone = local_zone()
    attribution = Attribution(switch_log.records)
    keys = _account_keys(_seen_accounts(switch_log, ledger))
    labels = labelling.shown

    # 先收成 UTC 小時（帳本就是這個粒度），再把小時換算成本機的日。小時整個歸給「小時起點」所在的日：
    # 半小時偏移的時區（+5:30、+5:45）裡，一個 UTC 小時會跨本機的日界，那半小時會歸給前一天；這是帳本粒度的代價
    live = [u for u in scan.usages if ledger.through is None or _hour_of(u.at) >= ledger.through]
    hours = _hourly(live, attribution, table)
    for cell in ledger.cells:
        hours[(cell.hour, cell.account_id, cell.model, cell.factors)].add(cell.counts, cell.max_prompt)
    # 金額在換算成日之前、逐格算：同一個模型的用量裡，帶計費因素的那幾格才是未知
    days: Dict[Tuple[str, Optional[str], str], _Tally] = defaultdict(_Tally)
    for (hour, account_id, model, factors), cell in hours.items():
        day = hour.astimezone(zone).date().isoformat()
        cost, unknown = _price(table, model, factors, cell, lang)
        days[(day, keys[account_id] if account_id else None, model)].add(cell.counts, cost, unknown)
    rank: Dict[Optional[str], int] = {key: i for i, key in enumerate(keys.values())}  # 帳號鍵的排序；未歸屬排最後
    rank[None] = len(rank)
    rows = [dict(day=day, account=account, model=model, **dict(zip(TOKEN_FIELDS, tally.counts)),
                 cost=tally.cost, costUnknown=tally.unknown)
            for (day, account, model), tally in sorted(
                days.items(), key=lambda kv: (kv[0][0], rank[kv[0][1]], kv[0][2]))]

    today = now.astimezone(zone).date()
    cutoff = next((r.at for r in switch_log.records if r.last_run_at is not None), None)
    earliest = min([u.at for u in live] + [c.hour for c in ledger.cells], default=None)
    used = {r["account"] for r in rows}
    listed = [(account_id, key) for account_id, key in keys.items() if key in used]  # 有用量的帳號
    return {
        "schema": SCHEMA,
        "generatedAt": now.isoformat(),
        "today": today.isoformat(),
        "language": lang,
        # 帳號依出現的順序輪流領顏色（第 5 個起從頭再用）；顏色跟著帳號，不隨區間或檢視的帳號改變
        "accounts": [{"key": key, "label": labels[account_id], "color": ACCOUNT_COLORS[i % len(ACCOUNT_COLORS)]}
                     for i, (account_id, key) in enumerate(listed)],
        "rows": rows,
        # 用量帳本：最早有資料的時間、最後一次成功更新的時間（沒更新過是 null）；更新失敗的原因在 notices
        "ledger": {"earliest": earliest.isoformat() if earliest else None,
                   "updatedAt": status.updated_at.isoformat() if status.updated_at else None},
        # 開始記錄停機時段的那一天（本機）；沒有任何一筆帶上一次運作時間時是 null
        "downtimeRecordedSince": cutoff.astimezone(zone).date().isoformat() if cutoff else None,
        "summary": {name: _summary(rows, today, span, zone, cutoff, earliest, rank) for name, span in RANGES},
        # 單價表的版本日期；單價表讀不到是 null（所有金額都是未知，notices 裡有原因）
        "prices": {"version": table.version},
        "notices": _notices(scan, switch_log, ledger, status, labelling, lang, rows),
    }


def _hour_of(at: datetime) -> datetime:
    return at.replace(minute=0, second=0, microsecond=0)


class _Hour:
    """一小時一格的 token 數，與格子裡最長的 prompt（記錄它之前入帳的格子是 0）。"""

    def __init__(self):
        self.counts = [0] * len(TOKEN_FIELDS)
        self.max_prompt = 0

    def add(self, counts: Sequence[int], prompt: int) -> None:
        _add(self.counts, counts)
        self.max_prompt = max(self.max_prompt, prompt)


def _hourly(usages: Iterable[Usage], attribution: Attribution, table: PriceTable) -> Dict[_HourKey, _Hour]:
    hours: Dict[_HourKey, _Hour] = defaultdict(_Hour)
    for u in usages:
        key = (_hour_of(u.at), attribution.account_at(u.at), u.model, u.factors + _long_prompt(table, u))
        hours[key].add((u.input, u.output, u.cache_write_5m, u.cache_write_1h, u.cache_read), _prompt(u))
    return hours


def _prompt(u: Usage) -> int:
    """prompt 長度：input＋cache 寫入＋cache 讀取（供應商依這個長度決定長 prompt 的單價）。"""
    return u.input + u.cache_write_5m + u.cache_write_1h + u.cache_read


def _long_prompt(table: PriceTable, u: Usage) -> Tuple[str, ...]:
    """prompt 超過單價表的門檻：那一則回應要用單價表不含的另一種單價，拆到另一格，同一小時的短 prompt 才算得出。
    要在入帳前拆，入帳後只剩一小時的加總，分不出是哪一則。"""
    price = prices.lookup(table, u.model)
    if price is not None and price.long_prompt_over is not None and _prompt(u) > price.long_prompt_over:
        return (f"longPrompt:{price.long_prompt_over}",)
    return ()


def _price(table: PriceTable, model: str, factors: Sequence[str], cell: _Hour,
           lang: str) -> Tuple[Optional[float], List[str]]:
    """一格的金額（美元）與算不出的原因：算得出時原因是空的，算不出時金額是 None。"""
    if not table.readable:
        return None, [i18n.text(lang, "report.cost.prices_unreadable")]
    price = prices.lookup(table, model)
    if price is None:
        return None, [i18n.text(lang, "report.cost.unknown_model", model=model)]
    over = price.long_prompt_over
    if over is not None and cell.max_prompt > over and not any(f.startswith("longPrompt:") for f in factors):
        # 入帳時單價表還沒有這個門檻（或這個模型），沒拆格：格子裡有長 prompt，整格都算不出
        factors = tuple(factors) + (f"longPrompt:{over}",)
    if factors:
        return None, [_factor_reason(lang, model, factor) for factor in factors]
    return sum(n * rate for n, rate in zip(cell.counts, price.rates)) / 1_000_000, []


def _factor_reason(lang: str, model: str, factor: str) -> str:
    name, _, value = factor.partition(":")
    if name == "geo" and value == "us":
        return i18n.text(lang, "report.cost.factor.geo_us")
    if name == "longPrompt" and value.isascii() and value.isdigit():  # 帳本可能被手改："²" 也是 isdigit
        return i18n.text(lang, "report.cost.factor.long_prompt", model=model, n=f"{int(value):,}")
    if name == "webSearch":
        return i18n.text(lang, "report.cost.factor.web_search")
    keys = {"speed": "report.cost.factor.speed", "geo": "report.cost.factor.geo", "tier": "report.cost.factor.tier"}
    if name in keys:
        return i18n.text(lang, keys[name], value=value)
    return i18n.text(lang, "report.cost.factor.other", value=factor)  # 之後的版本記下、這一版不認得的因素


def update_ledger(managed: ManagedDirectory, scan: Scan, switch_log: SwitchLog, now: datetime,
                  table: PriceTable) -> LedgerStatus:
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
        # 單價表只用來把長 prompt 拆到另一格（門檻在單價表裡）；金額不入帳
        cells = [LedgerCell(hour, account_id, model, tuple(cell.counts), factors, cell.max_prompt)
                 for (hour, account_id, model, factors), cell in sorted(
                     _hourly(fresh, attribution, table).items(),
                     key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2], kv[0][3]))]
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


def _seen_accounts(switch_log: SwitchLog, ledger: LedgerRead) -> List[str]:
    """出現過的帳號識別碼，依首次出現的順序：切換紀錄在前，帳本裡的接在後面（切換紀錄讀不到時，帳本裡的帳號照樣要有）。"""
    seen: Dict[str, None] = {}
    for account_id in [r.account_id for r in switch_log.records] + [c.account_id for c in ledger.cells]:
        if account_id:
            seen.setdefault(account_id)
    return list(seen)


def _account_keys(seen: Sequence[str]) -> Dict[str, str]:
    """帳號識別碼 → 不透明的鍵（依首次出現的順序）。"""
    return {account_id: f"a{i}" for i, account_id in enumerate(seen, 1)}


def update_labels(managed: ManagedDirectory, switch_log: SwitchLog, ledger: LedgerRead,
                   accounts: Sequence[WatchedAccount], lang: str) -> Labelling:
    """依現有的綁定更新「帳號識別碼 → 最後用過的標籤」的對照並存好，回傳出現過的帳號各自該顯示的標籤。
    綁定優先於舊標籤（改標籤後歷史用量跟著換）；沒有標籤的帳號是未監看帳號，依首次出現的順序領到下一個沒用過的編號，
    編號存在同一份對照裡、之後不變，帳號後來納管了也不讓出。對照讀不到時不寫（不蓋掉讀不到的內容），編號只在這次報表有效。"""
    stored = managed.read_account_labels()
    before = stored or AccountLabels({}, {})
    labels = dict(before.labels)
    bound: Dict[str, str] = {}
    for account in accounts:  # 同一個帳號有幾份憑證快照時，取第一份
        if account.account_id and account.account_id not in bound:
            bound[account.account_id] = account.label
    labels.update(bound)
    unwatched = dict(before.unwatched)
    seen = _seen_accounts(switch_log, ledger)
    for account_id in seen:
        if account_id not in labels and account_id not in unwatched:
            unwatched[account_id] = max(unwatched.values(), default=0) + 1
    saved = stored is not None
    if saved and (labels, unwatched) != (before.labels, before.unwatched):
        try:
            managed.write_account_labels(AccountLabels(labels, unwatched))
        except OSError:
            saved = False
    shown = {account_id: labels[account_id] if account_id in labels
             else i18n.text(lang, "report.account.unwatched", n=unwatched[account_id]) for account_id in seen}
    return Labelling(shown, saved)


def _summary(rows: List[dict], today: date, span: Optional[int], zone: Optional[tzinfo],
             cutoff: Optional[datetime], earliest: Optional[datetime], rank: Dict[Optional[str], int]) -> dict:
    first = today - timedelta(days=span - 1) if span else None
    selected = [r for r in rows if first is None or r["day"] >= first.isoformat()]
    per_model: Dict[Optional[str], Dict[str, _Tally]] = defaultdict(lambda: defaultdict(_Tally))
    per_day: Dict[Tuple[str, Optional[str]], int] = defaultdict(int)
    per_day_model: _DayModels = defaultdict(lambda: defaultdict(lambda: defaultdict(_Tally)))
    for r in selected:
        counts = [r[field] for field in TOKEN_FIELDS]
        per_model[r["account"]][r["model"]].add(counts, r["cost"], r["costUnknown"])
        per_day_model[r["day"]][r["account"]][r["model"]].add(counts, r["cost"], r["costUnknown"])
        per_day[(r["day"], r["account"])] += sum(counts)
    per_account: Dict[Optional[str], _Tally] = {}
    for account, models in per_model.items():
        per_account[account] = _merged(models.values())
    # 用量多的在前，未歸屬排最後（有列就一定有用量：列是從用量算出來的）
    ranked = sorted(per_account.items(), key=lambda kv: (kv[0] is None, -sum(kv[1].counts), rank[kv[0]]))
    total = _merged(tally for _, tally in ranked)
    total_models = _merged_models(per_model.values())
    range_start = first or (date.fromisoformat(min(r["day"] for r in selected)) if selected else None)
    start: Optional[datetime] = earliest
    if first is not None:
        start = (datetime.combine(first, time.min, tzinfo=zone) if zone
                 else datetime.combine(first, time.min).astimezone())
    return {
        "from": first.isoformat() if first else None,
        "days": _days(range_start, selected, today),
        "daily": [{"day": day, "account": account, "tokens": tokens}
                  for (day, account), tokens in sorted(per_day.items(), key=lambda kv: (kv[0][0], rank[kv[0][1]]))],
        "byDay": _by_day(per_day_model, rank),
        "accounts": [dict(account=account, **_figures(tally, per_model[account])) for account, tally in ranked],
        "total": _figures(total, total_models),
        "downtimeUnrecognized": bool(selected) and (cutoff is None or (start is not None and start < cutoff)),
    }


def _merged_models(per_account: Iterable[Dict[str, _Tally]]) -> Dict[str, _Tally]:
    """把各帳號的「模型 → 一格」合併成不分帳號的一份。"""
    merged: Dict[str, _Tally] = defaultdict(_Tally)
    for models in per_account:
        for model, tally in models.items():
            merged[model].merge(tally)
    return merged


def _by_day(per_day_model: _DayModels, rank: Dict[Optional[str], int]) -> List[dict]:
    """每日分頁的表：有用量的日子（舊的在前），各自帶合計與各帳號的數字（未歸屬排最後），每組都附各模型的細分。"""
    entries = []
    for day, accounts in sorted(per_day_model.items()):
        total_models = _merged_models(accounts.values())
        entries.append({
            "day": day,
            "total": _figures(_merged(total_models.values()), total_models),
            "accounts": [dict(account=account, **_figures(_merged(models.values()), models))
                         for account, models in sorted(accounts.items(), key=lambda kv: rank[kv[0]])],
        })
    return entries


def _days(start: Optional[date], selected: Sequence[dict], today: date) -> List[str]:
    """長條圖的日軸：區間第一天到今天，每一天都有（沒用量的日子留空）；用量比今天還晚（時鐘被調過）時延到那一天。"""
    if start is None:
        return []
    end = max([today] + [date.fromisoformat(r["day"]) for r in selected])
    return [(start + timedelta(days=n)).isoformat() for n in range((end - start).days + 1)]


def _merged(tallies: Iterable[_Tally]) -> _Tally:
    merged = _Tally()
    for tally in tallies:
        merged.merge(tally)
    return merged


def _add(cell: List[int], counts: Sequence[int]) -> None:
    for i, n in enumerate(counts):
        cell[i] += n


def _figures(tally: _Tally, models: Optional[Dict[str, _Tally]] = None) -> dict:
    """一組合計的數字。models 有給時，另附各模型的同樣數字（token 多的在前）。"""
    figures: dict = dict(zip(TOKEN_FIELDS, tally.counts))
    figures["tokens"] = sum(tally.counts)  # 全部種類相加
    figures["cacheWrite"] = figures["cacheWrite5m"] + figures["cacheWrite1h"]
    figures["cacheHitRatio"] = cache_hit_ratio(figures)
    figures["cost"] = tally.cost  # 美元，只含算得出的部分；沒有任何部分算得出是 null
    figures["costUnknown"] = tally.unknown  # 算不出的部分的原因；空的是全部算得出
    if models is not None:
        figures["models"] = [dict(model=model, **_figures(t)) for model, t in
                             sorted(models.items(), key=lambda kv: (-sum(kv[1].counts), kv[0]))]
    return figures


def cache_hit_ratio(figures: dict) -> Optional[float]:
    """cache 讀取 ÷（input＋cache 寫入＋cache 讀取），output 不計（詞彙表）；分母為 0 時沒有比例。"""
    denominator = figures["input"] + figures["cacheWrite5m"] + figures["cacheWrite1h"] + figures["cacheRead"]
    return figures["cacheRead"] / denominator if denominator else None


def _notices(scan: Scan, switch_log: SwitchLog, ledger: LedgerRead, status: LedgerStatus, labelling: Labelling,
             lang: str, rows: Sequence[dict]) -> List[dict]:
    notices = []
    unknown = _Tally()
    for r in rows:
        unknown.add((), None, r["costUnknown"])
    if unknown.unknown:
        notices.append({"kind": "costUnknown", "reason": i18n.text(lang, "report.list_sep").join(unknown.unknown)})
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
    if not labelling.saved:
        notices.append({"kind": "labelsUnavailable"})
    return notices


def failure_reason(lang: str, failure: LedgerFailure) -> str:
    """帳本更新失敗的原因，給橫幅與錯誤紀錄用的一句話。"""
    return failure.detail or i18n.text(lang, "report.ledger.reason.unknown")
