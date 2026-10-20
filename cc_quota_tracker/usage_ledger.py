"""用量帳本的檔案格式與跨行程的鎖（ADR-0013）。檔案本身的讀寫與權限在 ManagedDirectory。

帳本只存 token 數，不存金額：每一格是「UTC 小時 × 帳號識別碼（None 是未歸屬）× 模型 × 計費因素」的各種 token 數。
計費因素另外存，是因為對話紀錄被刪掉之後就分辨不出哪些用量單價表算不出來。
檔案是 JSON Lines，只追加。一次追加是一個批次：先一行 {"through": 時間, "rows": n}，再接 n 行格子。
through 之前的小時都已入帳（含沒有用量的小時），之後的小時不在帳本裡。
批次以標頭宣告行數：寫到一半被中斷的批次（行數不足、有行讀不懂）整批不採用，through 不前進，下次整批重寫，
不會有「格子寫進去了、through 沒前進」而重複入帳。"""
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, NamedTuple, Optional, Sequence, Tuple

TOKEN_FIELDS = ("input", "output", "cacheWrite5m", "cacheWrite1h", "cacheRead")
LOCK_WAIT_SECONDS = 10.0  # 另一個行程在寫帳本時最多等多久；等不到就跳過這次追加
_LOCK_POLL_SECONDS = 0.05


class LedgerCell(NamedTuple):
    hour: datetime  # UTC，整點
    account_id: Optional[str]
    model: str
    counts: Tuple[int, ...]  # 依 TOKEN_FIELDS 的順序
    factors: Tuple[str, ...] = ()  # 單價表無法計價的計費因素（見 token_report）；空的是標準計費，檔案裡不寫這個欄位
    # 格子裡最長的 prompt 的 token 數：入帳之後單價表才補上長 prompt 門檻的模型，靠它判斷這格算不算得出。
    # 記錄它之前入帳的格子是 0
    max_prompt: int = 0


class LedgerRead(NamedTuple):
    """讀回的帳本：入帳的格子、已入帳到哪個小時之前（沒有批次是 None）、讀不懂而不採用的批次與行數、整個檔案是否打不開。"""
    cells: Tuple[LedgerCell, ...]
    through: Optional[datetime]
    skipped: int
    unreadable: bool


class LedgerFailure(NamedTuple):
    """帳本更新失敗的原因：kind 是與語系無關的代碼，detail 是系統回報的說明（可以是空的）。"""
    kind: str
    detail: str = ""


class LedgerStatus(NamedTuple):
    """帳本的更新狀態：最後一次成功更新的時間、最近一次更新失敗的原因（之後成功就清掉）。"""
    updated_at: Optional[datetime]
    failure: Optional[LedgerFailure]


def encode_batch(cells: Sequence[LedgerCell], through: datetime) -> bytes:
    lines = [json.dumps({"through": through.isoformat(), "rows": len(cells)})]
    for cell in cells:
        row = dict(hour=cell.hour.isoformat(), accountId=cell.account_id, model=cell.model,
                   **dict(zip(TOKEN_FIELDS, cell.counts)), maxPrompt=cell.max_prompt)
        if cell.factors:
            row["factors"] = list(cell.factors)
        lines.append(json.dumps(row))
    return ("\n".join(lines) + "\n").encode("utf-8")


def decode(content: str) -> LedgerRead:
    cells: List[LedgerCell] = []
    through: Optional[datetime] = None
    skipped = 0
    lines = [line for line in content.split("\n") if line.strip()]  # 不用 splitlines：它會在 U+2028 上多切一刀
    i = 0
    while i < len(lines):
        header = _object(lines[i])
        rows = header.get("rows") if header else None
        marker = _datetime(header.get("through")) if header else None
        if marker is None or not isinstance(rows, int) or isinstance(rows, bool) or rows < 0:
            skipped += 1  # 批次標頭以外的行：讀不懂，或是上一個被中斷的批次留下的
            i += 1
            continue
        body: List[LedgerCell] = []
        j = i + 1
        while j < len(lines) and len(body) < rows:
            cell = _cell(_object(lines[j]))
            if cell is None:
                break
            body.append(cell)
            j += 1
        if len(body) == rows:
            cells.extend(body)
            through = marker if through is None else max(through, marker)
        else:
            skipped += 1  # 被中斷或有行讀不懂的批次：整批不採用
        i = j
    return LedgerRead(tuple(cells), through, skipped, False)


def _object(line: str) -> Optional[dict]:
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _datetime(value) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return parsed if parsed and parsed.tzinfo else None


def _cell(row: Optional[dict]) -> Optional[LedgerCell]:
    if row is None:
        return None
    hour, account_id, model = _datetime(row.get("hour")), row.get("accountId"), row.get("model")
    counts = [row.get(field) for field in TOKEN_FIELDS]
    # 記錄計費因素與最長 prompt 之前寫的格子沒有這兩個欄位
    factors, max_prompt = row.get("factors", []), row.get("maxPrompt", 0)
    if (hour is None or not (account_id is None or (isinstance(account_id, str) and account_id))
            or not (isinstance(model, str) and model)
            or not all(isinstance(c, int) and not isinstance(c, bool) and c >= 0 for c in counts + [max_prompt])
            or not (isinstance(factors, list) and all(isinstance(f, str) and f for f in factors))):
        return None
    return LedgerCell(hour, account_id, model, tuple(counts), tuple(factors), max_prompt)


@contextmanager
def exclusive(path: Path, wait: float) -> Iterator[bool]:
    """同一時間只讓一個行程進去：拿到鎖 yield True；等了 wait 秒還是被別的行程占著就 yield False（呼叫端跳過這次寫入）。
    鎖跟著檔案控制代碼走，行程中途死掉作業系統也會放掉，不會留下過期的鎖。鎖檔打不開丟 OSError。"""
    fd = os.open(path, os.O_RDWR | os.O_CREAT)
    held = False
    try:
        deadline = time.monotonic() + wait
        while True:
            if _try_lock(fd):
                held = True
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(_LOCK_POLL_SECONDS)
        yield held
    finally:
        if held:
            _unlock(fd)
        os.close(fd)


if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
