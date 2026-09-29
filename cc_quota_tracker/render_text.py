"""把看板渲染成終端機文字；所有文案都在這一層套用。"""
from datetime import datetime
from typing import Optional

from . import COMMAND
from .board import Board, Card, Limit, Money, ReadingState, Role
from .fmt import absolute, account_label, age, countdown, until

_WINDOW_NAMES = {"session": "工作階段窗口", "weekly_all": "週窗口", "weekly_scoped": "週限額"}
_UPDATES_SOON = "Claude Code 更新額度快取後就會出現"
SETTINGS_UNREADABLE = "注意：設定檔無法讀取（不是合法的 JSON），裡面的設定都當成沒填；本工具不會覆寫它，請修正後再試。"


def render(board: Board) -> str:
    lines = [_render_card(c, board) for c in board.cards]
    if board.schema_changed:
        shown = (f"以下是最後一次成功的讀數（{_time(board.last_reading_at)}）" if board.last_reading_at
                 else "目前沒有成功的讀數")
        lines.insert(0, f"注意：額度快取結構已變更，本工具讀不懂新的結構；{shown}")
    if board.wrong_location_suspected:
        lines.insert(0, "注意：預設位置找不到 Claude Code 的額度快取，可能讀錯位置。"
                        "Claude Code 目錄若不在 home（例如設了 CLAUDE_CONFIG_DIR），請在設定檔的 claudeConfigDir 指定。")
    if board.settings_unreadable:
        lines.insert(0, SETTINGS_UNREADABLE)
    labels = [account_label(key) for key in board.managed_accounts]
    lines.append("納管帳號：" + "、".join(labels) if labels else "尚未納管任何帳號")
    return "\n".join(lines)


def _render_card(card: Card, board: Board) -> str:
    body = _body(card, board)
    expires = card.snapshot_expires_at
    label = account_label(card.account_key) if card.account_key else None
    if expires is not None:
        if expires <= board.as_of:
            when = f"憑證快照已過期（{absolute(expires, board.as_of)}）"
        else:
            left = countdown(expires - board.as_of, board.countdown_format)
            when = f"憑證快照 {left}後到期（{absolute(expires, board.as_of)}）"
        if card.snapshot_expiring:
            body.insert(0, f"{when}：在 Claude Code 重新登入這個帳號，再執行 {COMMAND} add {label}")
        else:
            body.append(when)
    if card.snapshot_invalid:
        body.insert(0, f"憑證快照已失效，請重新納管：Claude Code 目前登入的就是這個帳號，執行 {COMMAND} add {label}")
    return "\n".join([_header(card)] + ["  " + line for line in body])


def _header(card: Card) -> str:
    if card.role is Role.UNMANAGED:
        return f"[使用中] 未納管帳號（納管方法：在 Claude Code 登入這個帳號後執行 {COMMAND} add <帳號標籤>）"
    label = account_label(card.account_key)
    return f"[{'使用中' if card.role is Role.ACTIVE else '待命'}] {label}"


def _body(card: Card, board: Board) -> list:
    if card.reading_state is ReadingState.NO_READING:
        return ["尚無讀數" if card.role is Role.STANDBY else "尚無讀數，" + _UPDATES_SOON]
    if card.reading_state is ReadingState.PENDING:
        return ["讀數待更新，" + _UPDATES_SOON]
    if card.role is Role.STANDBY:
        lines = [f"最後觀測：{age(card.reading_age)}（觀測值：觀測之後這個帳號沒再被用過才準確）"]
    else:
        lines = ["讀數年齡：" + age(card.reading_age)]
        if card.lagging:
            lines.append("有新對話，額度尚未更新")
    if card.locked_reason:
        lines.append("額度已鎖定：" + card.locked_reason)
    lines += [_limit_line(lim, board) for lim in card.limits + card.scoped_limits]
    if card.other_limits:
        lines.append("其他限額：")
        lines += ["  " + _limit_line(lim, board) for lim in card.other_limits]
    if card.weekly_breakdown:
        b = card.weekly_breakdown
        lines.append(f"本週用量去向（{_time(b.started_at)} ～ {_time(b.ends_at)}）：")
        lines += [f"  {row.label}  {row.percent}%" for row in b.rows]
    if card.extra_usage:
        e = card.extra_usage
        lines.append(f"額外用量  {_money(e.used)} / {_money(e.limit)}")
    if card.spend:
        s = card.spend
        lines.append(f"花費  {_money(s.used)} / {_money(s.limit)}")
    return lines


def _limit_line(lim: Limit, board: Board) -> str:
    name = _WINDOW_NAMES.get(lim.kind, lim.kind)
    if lim.scope:
        name = f"{name}（{lim.scope}）"
    if lim.reset:
        return f"{name}  已重置，下次重置時間未知"
    value = "無計時中窗口" if lim.percent is None else f"{lim.percent}%"
    line = f"{name}  {value}  重置：{until(lim.resets_at, board.as_of, board.countdown_format) if lim.resets_at else '未知'}"
    if lim.dollars and lim.dollars.used is not None:
        line += f"  已用 ${lim.dollars.used:g}"
    return line


def _time(value: Optional[datetime]) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M") if value else "未知"


def _money(value: Optional[Money]) -> str:
    if value is None:
        return "—"
    amount = value.minor / 10 ** value.exponent
    return f"{amount:.{value.exponent}f} {value.currency or ''}".rstrip()

