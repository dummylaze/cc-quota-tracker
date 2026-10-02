"""視窗各版面共用的文案與折行：卡片的提示、看板的橫幅，以及依字型寬度折行。版面配置不在這裡，各版面自己排。
文案取自語系檔，語系由版面渲染時傳入。"""
import re
from typing import Optional, Tuple

from . import COMMAND
from .board import Board, Card, Limit, QueryFailure, QueryStatus, ReadingState, Role
from .fmt import absolute, age, countdown, until
from .i18n import text

LINE_TAG = "wrapped-line"  # 多行文字的逐行 item；同一段的各行共用最後一個 tag。測試靠它把各行接回一段
QUERY_MESSAGE_LIMIT = 60  # Claude Code 回報的原始訊息在卡片上最多顯示幾個字，超過就截斷；卡片很窄，不能讓它撐開版面
_QUERY_REASONS = {
    QueryFailure.COMMAND_NOT_FOUND: "query.note.command_not_found",
    QueryFailure.TIMEOUT: "query.note.timeout",
    QueryFailure.NOT_WRITTEN: "query.note.not_written",
}


def notes(card: Card, board: Board, lang: str, expiry_info: bool = True, short_pending: bool = False):
    """(文字, 色點的顏色 token, 文字的顏色 token)，依顯示順序。
    expiry_info 為 False 時略過只是告知到期時間的那一條（版面另有欄位顯示）；要使用者動手的到期提示照樣列出。
    short_pending 為 True 時，讀數待更新那一條改用短句：旁邊有「更新」入口的版面，提示要維持單行。"""
    result = []
    standby = card.role is Role.STANDBY
    if card.role is Role.UNMANAGED:
        result.append((text(lang, "note.how_to_manage", command=COMMAND), "accent", "fg"))
    if card.reading_state is ReadingState.PENDING:
        result.append((text(lang, "reading.pending_short" if short_pending else "reading.pending"), "sub", "sub"))
    elif card.reading_state is ReadingState.NO_READING:
        result.append((text(lang, "reading.none" if standby else "reading.none_soon"), "sub", "sub"))
    elif standby:
        result.append((text(lang, "note.observed"), "sub", "sub"))
    if card.lagging:
        result.append((text(lang, "reading.lagging"), "warning", "fg"))
    if card.locked_reason:
        result.append((text(lang, "reading.locked", reason=card.locked_reason), "critical", "critical"))
    if expiry_info or card.snapshot_invalid or card.snapshot_expiring:
        snapshot = _snapshot_note(card, board, lang)
        if snapshot:
            result.append(snapshot)
    return result


def query_entry(card: Card, status: QueryStatus) -> Optional[Tuple[str, bool]]:
    """卡片上的「更新」入口：(語系鍵, 可不可點)。只有落後或讀數待更新的使用中（或未納管）帳號才有；
    進行中改顯示「查詢中」，冷卻中標籤不變，兩者都不可點。沒有入口是 None。"""
    if card.role is Role.STANDBY or not (card.lagging or card.reading_state is ReadingState.PENDING):
        return None
    if status.in_progress:
        return "query.entry_busy", False
    return "query.entry", not status.cooling_down


def query_notes(card: Card, status: QueryStatus, lang: str, has_entry: bool):
    """查詢額度在卡片上多出來的提示，格式同 notes()：沒有入口時的「查詢中」（右鍵選單查詢時入口不在，
    進度要有地方看），以及最後一次失敗的原因（任何狀態都顯示，下一次查詢成功才消失）。待命帳號沒有。"""
    if card.role is Role.STANDBY:
        return []
    result = []
    if status.in_progress and not has_entry:
        result.append((text(lang, "query.entry_busy"), "sub", "sub"))
    failure = status.last_failure
    if failure is not None and failure.failure is not None:
        result.append((text(lang, "query.note.failed", reason=_failure_reason(failure.failure, failure.message, lang)),
                       "critical", "fg"))
    return result


def _failure_reason(failure: QueryFailure, message: Optional[str], lang: str) -> str:
    if failure is not QueryFailure.REPORTED_ERROR:
        return text(lang, _QUERY_REASONS[failure])
    message = " ".join((message or "").split())  # 原始訊息不翻譯，只收掉換行與多餘空白，並限制長度
    if not message:
        return text(lang, "query.note.reported_error_no_message")
    if len(message) > QUERY_MESSAGE_LIMIT:
        message = message[:QUERY_MESSAGE_LIMIT] + "…"
    return text(lang, "query.note.reported_error", message=message)


def card_notes(card: Card, board: Board, lang: str):
    """有「更新」入口的版面用：(提示清單, 入口所在那條提示的序號)。入口所在的是落後或讀數待更新那一條；
    序號是 None 表示這張卡片沒有入口。查詢的狀態與失敗原因接在那條提示底下，沒有入口時排在最前面。
    入口所在那一條的文字在這裡產生也在這裡認出來，兩處的語系鍵放在一起，改文案不會讓入口靜默消失。"""
    status = board.usage_query
    has_entry = query_entry(card, status) is not None
    shown = notes(card, board, lang, short_pending=has_entry)
    host = None
    if has_entry:
        host_texts = (text(lang, "reading.pending_short"), text(lang, "reading.lagging"))
        host = next((i for i, note in enumerate(shown) if note[0] in host_texts), None)
    at = 0 if host is None else host + 1
    shown[at:at] = query_notes(card, status, lang, host is not None)
    return shown, host


def count_dot(shown):
    """提示數量前的色點取最嚴重的那一條；沒有嚴重度的提示用 sub。"""
    keys = {dot for _, dot, _ in shown}
    return next((key for key in ("critical", "warning") if key in keys), "sub")


def reset_text(lim: Limit, board: Board, lang: str) -> Optional[str]:
    """窗口的重置倒數（「重置：2小時15分（14:00）」，中文不帶「後」，三種版面一致）；已重置的窗口另有說明，這裡是 None。"""
    if lim.reset:
        return None
    if lim.resets_at is not None:
        return text(lang, "limit.resets", when=until(lim.resets_at, board.as_of, board.countdown_format, lang, short=True))
    return None if lim.percent is None else text(lang, "limit.resets", when=text(lang, "common.unknown"))


def _snapshot_note(card: Card, board: Board, lang: str):
    if card.snapshot_invalid:
        return text(lang, "snapshot.invalid"), "critical", "critical"
    expires = card.snapshot_expires_at
    if expires is None:
        return None
    when = absolute(expires, board.as_of)
    expired = expires <= board.as_of
    note = (text(lang, "snapshot.expired", when=when) if expired
            else text(lang, "snapshot.expires_in", left=countdown(expires - board.as_of, board.countdown_format, lang),
                      when=when))
    if not card.snapshot_expiring:
        return note, "sub", "fg"
    note = text(lang, "snapshot.renew", when=note)
    return (note, "critical", "critical") if expired else (note, "warning", "fg")


def banner_lines(board: Board, lang: str, missing_font: Optional[str] = None):
    """missing_font：設定檔指定、但這台電腦上找不到的字型名稱；只有畫面層知道字型存不存在，所以由版面傳進來。"""
    lines = []
    if board.settings_unreadable:
        lines.append(text(lang, "settings.unreadable"))
    if board.invalid_settings:
        lines.append(text(lang, "settings.invalid", fields=text(lang, "sep.item").join(board.invalid_settings)))
    if missing_font is not None:
        lines.append(text(lang, "font.missing", font=missing_font))
    if board.restart_required:
        lines.append(text(lang, "banner.restart_required"))
    if board.wrong_location_suspected:
        lines.append(text(lang, "board.wrong_location"))
    if board.schema_changed:
        last = board.last_reading_at
        lines.append(text(lang, "banner.schema_changed", when=absolute(last, board.as_of),
                          age=age(board.as_of - last, lang)) if last else text(lang, "banner.schema_changed_none"))
    return lines


# 折行的單位：一個西文字（連同後面的空白）、一段空白，或一個中日韓字元
_WRAP_TOKEN = re.compile(r"[^\s⺀-￿]+\s*|\s+|.")


def wrap(font, text, width):
    """把文字折成不超過 width 的各行：西文在字與字之間斷，中日韓字元逐字斷，一個字就比一行寬時逐字硬斷。
    各行保留行尾空白，依序接回去就是原文（不含換行字元）。"""
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for token in _WRAP_TOKEN.findall(paragraph):
            if font.measure((line + token).rstrip()) <= width:
                line += token
                continue
            if line:
                lines.append(line)
            line = ""
            for ch in token:
                if line and font.measure((line + ch).rstrip()) > width:
                    lines.append(line)
                    line = ""
                line += ch
        lines.append(line)
    return lines
