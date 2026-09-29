"""視窗各版面共用的文案與折行：卡片的提示、看板的橫幅，以及依字型寬度折行。版面配置不在這裡，各版面自己排。
文案先以正體中文暫置。"""
import re

from . import COMMAND
from .board import Board, Card, ReadingState, Role
from .fmt import absolute, account_label, age, countdown
from .render_text import INVALID_SETTINGS

LINE_TAG = "wrapped-line"  # 多行文字的逐行 item；同一段的各行共用最後一個 tag。測試靠它把各行接回一段
_UPDATES_SOON = "Claude Code 更新額度快取後就會出現"
_HOW_TO_MANAGE = (f"這個帳號還沒納管：在 Claude Code 登入它之後執行 {COMMAND} add <帳號標籤>，"
                  "或在視窗按右鍵選「納管目前登入的帳號…」")
_OBSERVED = "觀測值：觀測之後這個帳號沒再被用過才準確；在別台機器上用過，這台看不到"


def notes(card: Card, board: Board, expiry_info: bool = True):
    """(文字, 色點的顏色 token, 文字的顏色 token)，依顯示順序。
    expiry_info 為 False 時略過只是告知到期時間的那一條（版面另有欄位顯示）；要使用者動手的到期提示照樣列出。"""
    result = []
    standby = card.role is Role.STANDBY
    if card.role is Role.UNMANAGED:
        result.append((_HOW_TO_MANAGE, "accent", "fg"))
    if card.reading_state is ReadingState.PENDING:
        result.append(("讀數待更新，" + _UPDATES_SOON, "sub", "sub"))
    elif card.reading_state is ReadingState.NO_READING:
        result.append(("尚無讀數" if standby else "尚無讀數，" + _UPDATES_SOON, "sub", "sub"))
    elif standby:
        result.append((_OBSERVED, "sub", "sub"))
    if card.lagging:
        result.append(("有新對話，額度尚未更新", "warning", "fg"))
    if card.locked_reason:
        result.append(("額度已鎖定：" + card.locked_reason, "critical", "critical"))
    if expiry_info or card.snapshot_invalid or card.snapshot_expiring:
        snapshot = _snapshot_note(card, board)
        if snapshot:
            result.append(snapshot)
    return result


def _snapshot_note(card: Card, board: Board):
    label = account_label(card.account_key) if card.account_key else None
    if card.snapshot_invalid:
        return (f"憑證快照已失效：Claude Code 目前登入的就是這個帳號，執行 {COMMAND} add {label} 重新納管",
                "critical", "critical")
    expires = card.snapshot_expires_at
    if expires is None:
        return None
    when = absolute(expires, board.as_of)
    expired = expires <= board.as_of
    text = (f"憑證快照已過期（{when}）" if expired
            else f"憑證快照 {countdown(expires - board.as_of, board.countdown_format)}後到期（{when}）")
    if not card.snapshot_expiring:
        return text, "sub", "fg"
    text += f"：在 Claude Code 重新登入這個帳號，再執行 {COMMAND} add {label}"
    return (text, "critical", "critical") if expired else (text, "warning", "fg")


def banner_lines(board: Board):
    lines = []
    if board.settings_unreadable:
        lines.append("設定檔無法讀取（不是合法的 JSON），裡面的設定都當成沒填；本工具不會覆寫它，請修正後再試。")
    if board.invalid_settings:
        lines.append(INVALID_SETTINGS.format(fields="、".join(board.invalid_settings)))
    if board.restart_required:
        lines.append("設定檔的路徑欄位改了；路徑只在啟動時讀取，重新啟動本工具後才生效。")
    if board.wrong_location_suspected:
        lines.append("預設位置找不到 Claude Code 的額度快取，可能讀錯位置。Claude Code 目錄若不在 home"
                     "（例如設了 CLAUDE_CONFIG_DIR），請在設定檔的 claudeConfigDir 指定。")
    if board.schema_changed:
        last = board.last_reading_at
        shown = (f"下面是最後一次成功的讀數（{absolute(last, board.as_of)}，{age(board.as_of - last)}）" if last
                 else "目前沒有成功的讀數")
        lines.append("額度快取結構已變更，本工具讀不懂新的結構；" + shown)
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
