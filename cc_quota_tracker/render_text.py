"""把看板渲染成終端機文字；所有文案都在這一層套用。"""
from datetime import timedelta

from .board import Board, Card, ReadingState

_WINDOW_NAMES = {"session": "工作階段窗口", "weekly_all": "週窗口"}


def render(board: Board) -> str:
    return "\n".join(_render_card(c) for c in board.cards)


def _render_card(card: Card) -> str:
    if card.reading_state is ReadingState.NO_READING:
        return "尚無讀數，請在該帳號下發一次 prompt"
    lines = ["讀數年齡：" + _age(card.reading_age)]
    for w in card.windows:
        reset = w.resets_at.astimezone().strftime("%Y-%m-%d %H:%M") if w.resets_at else "未知"
        lines.append(f"{_WINDOW_NAMES.get(w.kind, w.kind)}  {w.percent}%  重置：{reset}")
    return "\n".join(lines)


def _age(age: timedelta) -> str:
    minutes = int(age.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} 分鐘前"
    if minutes < 60 * 24:
        return f"{minutes // 60} 小時前"
    return f"{minutes // (60 * 24)} 天前"
