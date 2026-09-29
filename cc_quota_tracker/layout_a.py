"""版面 A（卡片列表）的精簡模式：只畫使用中帳號那一張卡片。文案先以正體中文暫置。

物件生命週期：所有 Canvas item 在建構時一次建好，之後每輪只改座標、文字、顏色與顯示狀態；
這一輪用不到的 item 設成 hidden，不刪除也不新建。destroy() 是唯一的銷毀路徑。"""
import tkinter.font as tkfont
from typing import Optional

from .board import Board, Card, Limit, ReadingState
from .fmt import absolute, account_label, age, countdown, until
from .tokens import FONTS, RADIUS, SPACE, THEMES

TAG = "layout-a"
_WINDOWS = (("session", "工作階段窗口"), ("weekly_all", "週窗口"))  # 精簡模式固定顯示這兩個窗口
_UPDATES_SOON = "Claude Code 更新額度快取後就會出現"


class _WindowRow:
    """一個窗口的 item：名稱、數值、進度條（底軌＋填色）、重置時間。"""

    def __init__(self, cv, fonts):
        self.name = cv.create_text(0, 0, anchor="w", font=fonts["body"], tags=TAG)
        self.value = cv.create_text(0, 0, anchor="e", tags=TAG)
        self.track = cv.create_line(0, 0, 0, 0, capstyle="round", tags=TAG)
        self.fill = cv.create_line(0, 0, 0, 0, capstyle="round", tags=(TAG, "bar-fill"))
        self.reset = cv.create_text(0, 0, anchor="nw", font=fonts["small"], tags=TAG)

    def items(self):
        return self.name, self.value, self.track, self.fill, self.reset


class LayoutA:
    def __init__(self, canvas):
        self.cv = cv = canvas
        self._scale = canvas.winfo_fpixels("1i") / 96
        self._fonts = {name: tkfont.Font(canvas, family=family, size=size, weight=weight)
                       for name, (family, size, weight) in FONTS.items()}
        f = self._fonts
        self._panel = cv.create_polygon(0, 0, 0, 0, 0, 0, smooth=True, tags=TAG)
        self._shadow = cv.create_polygon(0, 0, 0, 0, 0, 0, smooth=True, tags=TAG)
        self._card = cv.create_polygon(0, 0, 0, 0, 0, 0, smooth=True, tags=TAG)
        self._title = cv.create_text(0, 0, anchor="w", font=f["title"], tags=TAG)
        self._chip = cv.create_polygon(0, 0, 0, 0, 0, 0, smooth=True, tags=TAG)
        self._chip_text = cv.create_text(0, 0, anchor="center", font=f["chip"], tags=TAG)
        self._age = cv.create_text(0, 0, anchor="e", font=f["small"], tags=TAG)
        self._windows = [_WindowRow(cv, f) for _ in _WINDOWS]
        self._message = cv.create_text(0, 0, anchor="nw", font=f["small"], tags=TAG)
        self._expiry_dot = cv.create_oval(0, 0, 0, 0, width=0, tags=TAG)
        self._expiry = cv.create_text(0, 0, anchor="nw", font=f["small"], tags=TAG)

    def destroy(self):
        self.cv.delete(TAG)
        self._fonts.clear()  # tkfont.Font 被回收時會刪掉對應的具名字型

    def render(self, board: Board, theme: str):
        c = THEMES[theme]
        card = board.cards[0]  # 核心保證第一張是使用中帳號（或未納管帳號）
        pad, width = self._px("panel_pad"), self._px("card_width")
        left, right = pad + self._px("card_pad_x"), pad + width - self._px("card_pad_x")
        y = pad + self._px("card_pad_top")
        y = self._header(card, c, left, right, y)
        if card.reading_state is ReadingState.HAS_READING:
            self._hide(self._message)
            limits = {lim.kind: lim for lim in card.limits}
            for row, (kind, name) in zip(self._windows, _WINDOWS):
                lim = limits.get(kind)
                if lim is None:
                    self._hide(*row.items())
                    continue
                y = self._window(row, name, lim, board, c, left, right, y + self._px("section_gap"))
        else:
            for row in self._windows:
                self._hide(*row.items())
            y = self._text(self._message, left, y + self._px("section_gap"), right - left,
                           _reading_message(card), c["sub"])
        y = self._expiry_line(card, board, c, left, right, y)
        bottom = y + self._px("card_pad_bottom")
        offset = self._px("shadow_offset")
        self._rrect(self._shadow, pad + offset / 2, pad + offset, pad + width + offset / 2, bottom + offset,
                    RADIUS["card"], c["shadow"])
        self._rrect(self._card, pad, pad, pad + width, bottom, RADIUS["card"], c["card"])
        total_w, total_h = width + 2 * pad, bottom + pad
        self._rrect(self._panel, 0, 0, total_w, total_h, RADIUS["panel"], c["panel"])
        self.cv.configure(width=total_w, height=total_h)

    def _header(self, card: Card, c, left, right, y):
        f = self._fonts
        label = account_label(card.account_key) if card.account_key else "未納管帳號"
        height = f["title"].metrics("linespace")
        mid = y + height / 2
        self._show(self._title, left, mid, text=label, fill=c["fg"])
        chip = "使用中"  # 精簡模式只畫使用中帳號（或未納管帳號，同樣是使用中）
        chip_x = left + f["title"].measure(label) + self._px("chip_gap")
        chip_w = f["chip"].measure(chip) + 2 * self._px("chip_pad_x")
        chip_h = self._px("chip_height")
        self._rrect(self._chip, chip_x, mid - chip_h / 2, chip_x + chip_w, mid + chip_h / 2, RADIUS["chip"],
                    c["accent"])
        self._show(self._chip_text, chip_x + chip_w / 2, mid, text=chip, fill=c["chip_fg"])
        if card.reading_state is ReadingState.HAS_READING and card.reading_age is not None:
            self._show(self._age, right, mid, text="讀數 " + age(card.reading_age), fill=c["sub"])
        else:
            self._hide(self._age)
        return y + max(height, chip_h)

    def _window(self, row: _WindowRow, name: str, lim: Limit, board: Board, c, left, right, y):
        f = self._fonts
        height = max(f["body"].metrics("linespace"), f["percent"].metrics("linespace"))
        mid = y + height / 2
        self._show(row.name, left, mid, text=name, fill=c["sub"])
        if lim.reset:
            self._show(row.value, right, mid, text="已重置，下次重置時間未知", font=f["body"], fill=c["sub"])
        elif lim.percent is None:
            self._show(row.value, right, mid, text="無計時中窗口", font=f["body"], fill=c["sub"])
        else:
            self._show(row.value, right, mid, text=f"{lim.percent}%", font=f["percent"],
                       fill=c[lim.severity.value])
        y += height + self._px("bar_gap")
        bar = self._px("bar_height")
        # 圓頭線段的端點各往外凸出半個線寬，所以線段本身要內縮半個線寬
        start, end, bar_mid = left + bar / 2, right - bar / 2, y + bar / 2
        self._show(row.track, start, bar_mid, end, bar_mid, width=bar, fill=c["track"])
        if lim.percent:
            self._show(row.fill, start, bar_mid, start + (end - start) * min(lim.percent, 100) / 100, bar_mid,
                       width=bar, fill=c[lim.severity.value])
        else:
            self._hide(row.fill)
        y += bar
        reset = _reset_text(lim, board)
        if reset is None:
            self._hide(row.reset)
            return y
        return self._text(row.reset, left, y + self._px("line_gap"), right - left, reset, c["sub"])

    def _expiry_line(self, card: Card, board: Board, c, left, right, y):
        """憑證快照到期倒數，前面加嚴重度色點。"""
        text, color = _expiry(card, board, c)
        if text is None:
            self._hide(self._expiry_dot, self._expiry)
            return y
        y += self._px("section_gap")
        dot, gap = self._px("dot"), self._px("dot_gap")
        top = y + (self._fonts["small"].metrics("linespace") - dot) / 2
        self._show(self._expiry_dot, left, top, left + dot, top + dot, fill=color)
        return self._text(self._expiry, left + dot + gap, y, right - left - dot - gap, text,
                          c["fg"] if color == c["sub"] else color)

    # -- item 操作：只改屬性，不新建 --

    def _text(self, item, x, y, width, text, color):
        """多行文字：回傳它的下緣。"""
        self._show(item, x, y, text=text, fill=color, width=width)
        return self.cv.bbox(item)[3]

    def _show(self, item, *coords, **options):
        self.cv.coords(item, *coords)
        self.cv.itemconfigure(item, state="normal", **options)

    def _hide(self, *items):
        for item in items:
            self.cv.itemconfigure(item, state="hidden")

    def _rrect(self, item, x1, y1, x2, y2, radius, color):
        r = max(0, min(self._scale * radius, (x2 - x1) / 2, (y2 - y1) / 2))
        points = (x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                  x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1)
        self._show(item, *points, fill=color, outline="")

    def _px(self, key):
        return round(SPACE[key] * self._scale)


def _reading_message(card: Card) -> str:
    if card.reading_state is ReadingState.PENDING:
        return "讀數待更新，" + _UPDATES_SOON
    return "尚無讀數，" + _UPDATES_SOON


def _reset_text(lim: Limit, board: Board) -> Optional[str]:
    if lim.reset:
        return None  # 已經寫在數值那一格
    if lim.resets_at is not None:
        return "重置：" + until(lim.resets_at, board.as_of, board.countdown_format)
    return None if lim.percent is None else "重置：未知"


def _expiry(card: Card, board: Board, c):
    """(文字, 色點顏色)；沒有到期時間可顯示時文字為 None。"""
    if card.snapshot_invalid:
        return "憑證快照已失效，請重新納管", c["critical"]
    expires = card.snapshot_expires_at
    if expires is None:
        return None, None
    if expires <= board.as_of:
        return f"憑證快照已過期（{absolute(expires, board.as_of)}）", c["critical"]
    text = f"憑證快照 {countdown(expires - board.as_of, board.countdown_format)}後到期（{absolute(expires, board.as_of)}）"
    return text, c["warning"] if card.snapshot_expiring else c["sub"]
