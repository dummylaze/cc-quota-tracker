"""Claude Code 的對話紀錄（ADR-0013）：遞迴讀取 Claude Code 目錄底下的 projects/（含子代理的紀錄），只取帶用量的回應。

對話紀錄是未公開的內部結構。以下是用真實紀錄確認過的形狀，認不得的紀錄一律計數、不算成 0：
- 一則回應寫成多行，以「訊息識別碼＋請求識別碼」去重，跨檔也會重複（續接的 session 會帶著舊的回應）。
- 同一則回應的各行，input 與 cache 的數字一致，output 只會持平或上升，最後一行最大：留 output 最大的一行。
  各行的時間戳不同（串流中逐行寫入），歸屬用最早的那一個——請求送出時用的是當時的憑證。
- 用量全 0 的紀錄（用戶端自己合成的訊息，模型名 <synthetic>，有的還缺請求識別碼）不含任何 token，直接略過。
- 一行一筆 JSON，只以 \\n 分行：str.splitlines 會在字串內容裡的 U+2028 等字元多切一刀，把完整的行切成讀不懂。

計費因素（單價表無法計價的部分，金額記為未知）用白名單判斷：service_tier、speed、inference_geo 不是已知的標準值，
或 web search 次數大於 0，就記成一個因素；欄位不存在算標準值（舊版的紀錄沒有這些欄位）。"""
import json
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Tuple, Union, cast

PROJECTS_DIR = "projects"  # Claude Code 目錄底下放對話紀錄的子目錄


class Usage(NamedTuple):
    """一則回應的用量。時間是 UTC；cache 寫入分 5 分鐘與 1 小時兩種。"""
    at: datetime
    model: str
    input: int
    output: int
    cache_write_5m: int
    cache_write_1h: int
    cache_read: int
    factors: Tuple[str, ...] = ()  # 計費因素，如 "speed:fast"、"webSearch"；空的是標準計費


class Scan(NamedTuple):
    """掃描結果：去重後的回應、結構不符而沒計入的紀錄數、打不開（鎖住、權限）的檔案數。"""
    usages: Tuple[Usage, ...]
    mismatched: int
    unreadable_files: int


class _Verdict(Enum):
    SKIP = "skip"  # 不帶用量的紀錄，或用量全 0：略過，不是結構不符
    MISMATCH = "mismatch"


# 計費欄位 → 因素名稱、視為標準計費的值（None 是欄位不存在）
_STANDARD = {"service_tier": ("tier", {None, "standard"}), "speed": ("speed", {None, "standard"}),
             "inference_geo": ("geo", {None, "global", "not_available"})}
_FACTOR_VALUE = re.compile(r"[A-Za-z0-9_.-]{1,32}")  # 因素的值會顯示在報表上：不像代碼的一律記成 other

_Parsed = Union[_Verdict, Tuple[Tuple[str, str], Usage]]  # 結構不符／略過，或 (訊息識別碼, 請求識別碼) 與它的用量


def scan(claude_dir: Path) -> Scan:
    merged: Dict[Tuple[str, str], Usage] = {}
    mismatched = unreadable = 0
    for path in sorted((claude_dir / PROJECTS_DIR).rglob("*.jsonl")):
        try:
            for parsed in _lines(path):
                if parsed is _Verdict.MISMATCH:
                    mismatched += 1
                    continue
                assert not isinstance(parsed, _Verdict)
                key, usage = parsed
                merged[key] = _merge(merged[key], usage) if key in merged else usage
        except FileNotFoundError:
            continue  # 掃描途中被 Claude Code 依保留期限刪掉
        except OSError:
            unreadable += 1
    return Scan(tuple(merged.values()), mismatched, unreadable)


def _merge(old: Usage, new: Usage) -> Usage:
    first = min(old.at, new.at)
    return new._replace(at=first) if new.output >= old.output else old._replace(at=first)


def _lines(path: Path) -> Iterator[_Parsed]:
    """檔案裡每一行的結果，略過的不產出。檔尾沒有換行的那一行可能還在寫，讀不懂就當它還沒寫完。"""
    with open(path, encoding="utf-8", errors="replace", newline="\n") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                if line.endswith("\n"):
                    yield _Verdict.MISMATCH
                continue
            parsed = _usage_of(record)
            if parsed is not _Verdict.SKIP:
                yield parsed


def _usage_of(record) -> _Parsed:
    """type 不是 assistant 的紀錄不帶回應用量，與結構無關。"""
    if not isinstance(record, dict):
        return _Verdict.MISMATCH
    if record.get("type") != "assistant":
        return _Verdict.SKIP
    message = record.get("message")
    if not isinstance(message, dict):
        return _Verdict.MISMATCH
    usage = message.get("usage")
    creation = usage.get("cache_creation") if isinstance(usage, dict) else None
    if not isinstance(usage, dict) or not isinstance(creation, dict):
        return _Verdict.MISMATCH
    fields = [usage.get("input_tokens"), usage.get("output_tokens"), creation.get("ephemeral_5m_input_tokens"),
              creation.get("ephemeral_1h_input_tokens"), usage.get("cache_read_input_tokens")]
    if not all(isinstance(c, int) and not isinstance(c, bool) and c >= 0 for c in fields):
        return _Verdict.MISMATCH
    counts = cast(List[int], fields)
    if not any(counts):
        return _Verdict.SKIP
    model, message_id, request_id = message.get("model"), message.get("id"), record.get("requestId")
    at = _timestamp(record.get("timestamp"))
    if not (isinstance(model, str) and isinstance(message_id, str) and isinstance(request_id, str)
            and model and message_id and request_id) or at is None:
        return _Verdict.MISMATCH
    return (message_id, request_id), Usage(at, model, *counts, factors=_factors(usage))


def _factors(usage: dict) -> Tuple[str, ...]:
    factors = []
    for field, (name, standard) in _STANDARD.items():
        value = usage.get(field)
        if not ((value is None or isinstance(value, str)) and value in standard):  # list、dict 不能拿去查 set
            factors.append(f"{name}:{value if isinstance(value, str) and _FACTOR_VALUE.fullmatch(value) else 'other'}")
    tools = usage.get("server_tool_use")
    searches = tools.get("web_search_requests") if isinstance(tools, dict) else None
    if isinstance(searches, int) and not isinstance(searches, bool) and searches > 0:
        factors.append("webSearch")
    return tuple(factors)


def _timestamp(value) -> Optional[datetime]:
    """ISO 8601；Python 3.9 的 fromisoformat 不認 Z。沒帶時區的時間無從換算，視為結構不符。"""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None

