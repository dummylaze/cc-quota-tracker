"""視窗各版面共用的文案與折行：卡片的提示、看板的橫幅，以及依字型寬度折行。版面配置不在這裡，各版面自己排。
文案取自語系檔，語系由版面渲染時傳入。"""
import re
from typing import Optional

from . import COMMAND
from .board import Board, Card, ReadingState, Role
from .fmt import absolute, age, countdown
from .i18n import text

LINE_TAG = "wrapped-line"  # 多行文字的逐行 item；同一段的各行共用最後一個 tag。測試靠它把各行接回一段


def notes(card: Card, board: Board, lang: str, expiry_info: bool = True):
    """(文字, 色點的顏色 token, 文字的顏色 token)，依顯示順序。
    expiry_info 為 False 時略過只是告知到期時間的那一條（版面另有欄位顯示）；要使用者動手的到期提示照樣列出。"""
    result = []
    standby = card.role is Role.STANDBY
    if card.role is Role.UNMANAGED:
        result.append((text(lang, "note.how_to_manage", command=COMMAND), "accent", "fg"))
    if card.reading_state is ReadingState.PENDING:
        result.append((text(lang, "reading.pending"), "sub", "sub"))
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
