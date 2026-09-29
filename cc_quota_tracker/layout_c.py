"""版面 C（環形儀表）。一個帳號一格：外圈是週窗口、內圈是工作階段窗口，中央顯示工作階段百分比，底下是帳號標籤、
狀態標籤、讀數年齡與兩個窗口的文字說明。精簡模式只有使用中帳號那一格；展開模式每列三格，使用中帳號那一格加外框，
提示接在該列的格子下方、冠上帳號標籤。外框離卡片邊 row_inset，圓角與卡片同心。不與其他版面共用版面程式碼；提示與橫幅的文案、折行取自 canvas_text。

物件生命週期同版面 A、B：一格裡固定部分的 item 一次建好，之後每輪只改座標、文字、顏色與顯示狀態；數量跟著看板走的部分
（格子、提示、多行文字的行）由 _Pool 補建或刪到剛好，所以 item 數只由看板與模式決定。第二格起只在展開模式存在，
帶 EXPANDED_TAG。每組 item 都帶自己與上層的 tag，destroy() 刪掉全部。"""
import itertools
import math
import tkinter.font as tkfont
from typing import NamedTuple, Optional

from .board import Board, Card, Limit, ReadingState, Role
from .canvas_text import LINE_TAG, banner_lines, notes, wrap
from .fmt import account_label, age
from .tokens import FONTS, LINE_HEIGHT, RADIUS, SPACE, THEMES

TAG = "layout-c"
EXPANDED_TAG = "layout-c-expanded"  # 第二格起：只在展開模式存在
WEEK_TAG = "ring-week"  # 外圈填色的弧
SESSION_TAG = "ring-session"  # 內圈填色的弧
_WINDOWS = (("session", "工作階段"), ("weekly_all", "週"))  # 兩種模式都固定顯示這兩個窗口
_COLUMNS = 3  # 展開模式每列幾格
_NONE = "—"
_ids = itertools.count()


class _Paint:
    """item 操作：只改屬性，不新建。"""

    def __init__(self, canvas):
        self.cv = canvas
        self.scale = canvas.winfo_fpixels("1i") / 96
        self.fonts = {name: tkfont.Font(canvas, family=family, size=size, weight=weight)
                      for name, (family, size, weight) in FONTS.items()}

    def px(self, key):
        return round(SPACE[key] * self.scale)

    def height(self, font):
        return self.fonts[font].metrics("linespace")

    def pitch(self, font):
        """多行文字的行距：字級像素 × LINE_HEIGHT，不小於字型本身的 linespace。"""
        size_px = FONTS[font][1] * self.cv.winfo_fpixels("1i") / 72
        return max(self.height(font), math.ceil(LINE_HEIGHT * size_px))

    def show(self, item, *coords, **options):
        self.cv.coords(item, *coords)
        self.cv.itemconfigure(item, state="normal", **options)

    def hide(self, *items):
        for item in items:
            self.cv.itemconfigure(item, state="hidden")

    def rrect(self, item, x1, y1, x2, y2, radius, color, **options):
        """圓角以折線逼近四分之一圓（smooth 多邊形畫出的半徑只有一半）。"""
        r = max(0, min(self.scale * radius, (x2 - x1) / 2, (y2 - y1) / 2))
        steps = max(1, math.ceil(r / 2))
        points = []
        for cx, cy, start in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0), (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
            for i in range(steps + 1):
                angle = math.radians(start + 90 * i / steps)
                points += (cx + r * math.cos(angle), cy + r * math.sin(angle))
        self.show(item, *points, **{"fill": color, "outline": "", **options})


class _Group:
    """一組 item：帶著上層的 tag 再加一個自己的，刪掉自己的 tag 就連同底下各組一起刪掉。"""

    def __init__(self, p: _Paint, parent_tags):
        self.p = p
        self.tags = (*parent_tags, f"{TAG}-{next(_ids)}")

    def destroy(self):
        self.p.cv.delete(self.tags[-1])


class _Pool:
    """數量跟著看板走的同款 item 組：補建或刪到剛好 n 組。"""

    def __init__(self, make, destroy=None):
        self._make, self._destroy, self._groups = make, destroy or (lambda group: group.destroy()), []

    def __len__(self):
        return len(self._groups)

    def fit(self, n):
        while len(self._groups) < n:
            self._groups.append(self._make())
        for group in self._groups[n:]:
            self._destroy(group)
        del self._groups[n:]
        return self._groups


class _Lines(_Group):
    """多行文字：自己折行、逐行一個 item，行距照 LINE_HEIGHT。center 為真時 x 是中線、各行置中；否則 x 是左緣。"""

    def __init__(self, p, parent_tags, font, center=False):
        super().__init__(p, parent_tags)
        self.font = font
        tags, anchor = (LINE_TAG, *self.tags), "n" if center else "nw"
        self._lines = _Pool(lambda: p.cv.create_text(0, 0, anchor=anchor, font=p.fonts[font], tags=tags), p.cv.delete)

    def render(self, x, y, width, text, color):
        """回傳下緣。行距多出的部分上下各半。"""
        p = self.p
        lines = wrap(p.fonts[self.font], text, width)
        pitch = p.pitch(self.font)
        top = y + (pitch - p.height(self.font)) / 2
        for i, (item, line) in enumerate(zip(self._lines.fit(len(lines)), lines)):
            p.show(item, x, top + i * pitch, text=line, fill=color)
        return y + len(lines) * pitch

    def hide(self):
        self._lines.fit(0)


class _Note(_Group):
    """一條提示：嚴重度色點＋文字。"""

    def __init__(self, p, parent_tags):
        super().__init__(p, parent_tags)
        self.dot = p.cv.create_oval(0, 0, 0, 0, width=0, tags=self.tags)
        self.text = _Lines(p, self.tags, "small")

    def render(self, note, c, left, right, y):
        text, dot_key, text_key = note
        p = self.p
        dot, gap = p.px("dot"), p.px("dot_gap")
        top = y + (p.pitch("small") - dot) / 2  # 對齊第一行
        p.show(self.dot, left, top, left + dot, top + dot, fill=c[dot_key])
        return self.text.render(left + dot + gap, y, right - left - dot - gap, text, c[text_key])


class _Value(NamedTuple):
    """一個窗口在畫面上的呈現。percent 為 None 時圈上沒有填色的弧；foot 是已重置時補充的「下次重置時間未知」。"""
    text: str
    color: str  # 顏色 token
    percent: Optional[int] = None
    foot: Optional[str] = None


def _window(lim: Optional[Limit]) -> _Value:
    if lim is None:
        return _Value(_NONE, "sub")
    if lim.reset:
        return _Value("已重置", "sub", foot="下次重置時間未知")
    if lim.percent is None:
        return _Value("無計時中窗口", "sub")
    return _Value(f"{lim.percent}%", lim.severity.value, lim.percent)


def _windows(card: Card):
    """(工作階段窗口, 週窗口) 的呈現；還沒有讀數時兩個都是 None（圈是空的、不寫窗口說明）。"""
    limits = {lim.kind: lim for lim in card.limits} if card.reading_state is ReadingState.HAS_READING else {}
    return [_window(limits.get(kind)) if limits else None for kind, _ in _WINDOWS]


def _label(card: Card):
    return account_label(card.account_key) if card.account_key else "未納管帳號"


def _chip(card: Card):
    """(狀態標籤文字, 底色 token, 文字顏色 token)。"""
    if card.role is Role.STANDBY:
        return "待命", "chip_standby", "chip_standby_fg"
    return "使用中", "accent", "chip_active_fg"


class _Ring(_Group):
    """一格的環：外圈週窗口、內圈工作階段窗口，各有一條底軌與一段從正上方順時針填色的弧；中央是工作階段百分比。"""

    def __init__(self, p, parent_tags):
        super().__init__(p, parent_tags)
        cv, t = p.cv, self.tags
        self.week_track = cv.create_oval(0, 0, 0, 0, tags=t)
        self.week = cv.create_arc(0, 0, 0, 0, style="arc", start=90, tags=(*t, WEEK_TAG))
        self.session_track = cv.create_oval(0, 0, 0, 0, tags=t)
        self.session = cv.create_arc(0, 0, 0, 0, style="arc", start=90, tags=(*t, SESSION_TAG))
        self.center = cv.create_text(0, 0, anchor="center", tags=t)

    def render(self, cx, cy, session: Optional[_Value], week: Optional[_Value], c):
        p = self.p
        stroke = p.px("ring_stroke")
        outer = p.px("ring_size") / 2 - stroke / 2  # 線寬以圓周為中線，所以半徑內縮半個線寬
        inner = outer - stroke - p.px("ring_gap")
        for track, arc, radius, value in ((self.week_track, self.week, outer, week),
                                          (self.session_track, self.session, inner, session)):
            box = (cx - radius, cy - radius, cx + radius, cy + radius)
            p.show(track, *box, outline=c["track"], width=stroke, fill="")
            if value and value.percent:
                extent = -min(360 / 100 * value.percent, 359.99)  # 整圈的弧要略小於 360 度，否則起點與終點重合、什麼都不畫
                p.show(arc, *box, outline=c[value.color], width=stroke, extent=extent)
            else:
                p.hide(arc)
        if session and session.percent is not None:
            p.show(self.center, cx, cy, text=session.text, font=p.fonts["percent"], fill=c[session.color])
        else:
            p.show(self.center, cx, cy, text=_NONE, font=p.fonts["small"], fill=c["sub"])


class _Cell(_Group):
    """一個帳號一格：環、帳號標籤、狀態標籤、讀數年齡、兩個窗口的說明；使用中帳號加外框。提示由 render_notes 畫在該列下方。"""

    def __init__(self, p, parent_tags):
        super().__init__(p, parent_tags)
        cv, f, t = p.cv, p.fonts, self.tags
        self.frame = cv.create_polygon(0, 0, 0, 0, 0, 0, tags=t)
        self.ring = _Ring(p, t)
        self.label = _Lines(p, t, "title", center=True)
        self.chip = cv.create_polygon(0, 0, 0, 0, 0, 0, tags=t)
        self.chip_text = cv.create_text(0, 0, anchor="center", font=f["chip"], tags=t)
        self.age = cv.create_text(0, 0, anchor="n", font=f["small"], tags=t)
        self.legend = [_Lines(p, t, "small", center=True) for _ in _WINDOWS]
        self.notes = _Pool(lambda: _Note(p, t))

    def render(self, card: Card, c, x, y, width):
        """x、y 是這一格的左上角。回傳下緣。"""
        p = self.p
        pad, cx = p.px("ring_cell_pad"), x + width / 2
        inner_width = width - 2 * pad
        y += pad
        session, week = _windows(card)
        size = p.px("ring_size")
        self.ring.render(cx, y + size / 2, session, week, c)
        y = self.label.render(cx, y + size + p.px("section_gap"), inner_width, _label(card), c["fg"])
        chip, chip_bg, chip_fg = _chip(card)
        chip_w, chip_h = p.fonts["chip"].measure(chip) + 2 * p.px("chip_pad_x"), p.px("chip_height")
        y += p.px("line_gap")
        p.rrect(self.chip, cx - chip_w / 2, y, cx + chip_w / 2, y + chip_h, RADIUS["chip"], c[chip_bg])
        p.show(self.chip_text, cx, y + chip_h / 2, text=chip, fill=c[chip_fg])
        y += chip_h
        if card.reading_state is ReadingState.HAS_READING and card.reading_age is not None:
            y += p.px("line_gap")
            prefix = "觀測 " if card.role is Role.STANDBY else "讀數 "
            p.show(self.age, cx, y, text=prefix + age(card.reading_age), fill=c["sub"])
            y += p.height("small")
        else:
            p.hide(self.age)
        for lines, (_, name), value in zip(self.legend, _WINDOWS, (session, week)):
            if value is None:
                lines.hide()
                continue
            text = f"{name} " + "，".join(filter(None, (value.text, value.foot)))
            y = lines.render(cx, y + p.px("line_gap"), inner_width, text, c[value.color])
        return y + pad

    def outline(self, card: Card, c, x, top, width, bottom, framed: bool):
        """使用中帳號（含未納管）的外框，框住這一格；同一列的格子等高。待命帳號沒有；只有一格的精簡模式也不畫。"""
        p = self.p
        if not framed or card.role is Role.STANDBY:
            p.hide(self.frame)
            return
        p.rrect(self.frame, x, top, x + width, bottom, RADIUS["cell"], "", outline=c["accent"], width=p.px("highlight"))

    def render_notes(self, card: Card, board: Board, c, left, right, y, named: bool):
        """這一格的提示，畫在整列格子的下方、與格子的內容對齊左右邊。多個帳號並列時冠上帳號標籤，才看得出是哪一格的。回傳下緣。"""
        p = self.p
        shown = notes(card, board)
        if named:
            shown = [(f"{_label(card)}：{text}", dot, fg) for text, dot, fg in shown]
        for i, (slot, note) in enumerate(zip(self.notes.fit(len(shown)), shown)):
            y = slot.render(note, c, left, right, y + p.px("section_gap" if i == 0 else "line_gap"))
        return y


class LayoutC:
    def __init__(self, canvas):
        self.cv = canvas
        self._p = p = _Paint(canvas)
        self._panel = canvas.create_polygon(0, 0, 0, 0, 0, 0, tags=TAG)
        self._banner_bg = canvas.create_polygon(0, 0, 0, 0, 0, 0, tags=TAG)
        self._banner = _Lines(p, (TAG,), "body")
        self._shadow = canvas.create_polygon(0, 0, 0, 0, 0, 0, tags=TAG)
        self._card = canvas.create_polygon(0, 0, 0, 0, 0, 0, tags=TAG)
        # 補建時 len(self._cells) 就是新格的序號：第二格起帶 EXPANDED_TAG
        self._cells = _Pool(lambda: _Cell(p, (TAG, EXPANDED_TAG) if len(self._cells) else (TAG,)))

    def destroy(self):
        self.cv.delete(TAG)
        self._p.fonts.clear()  # tkfont.Font 被回收時會刪掉對應的具名字型
        self._cells.fit(0)

    def render(self, board: Board, theme: str, expanded: bool = False):
        p, c = self._p, THEMES[theme]
        pad, inset, cell_w, gap = p.px("panel_pad"), p.px("row_inset"), p.px("ring_cell_width"), p.px("card_gap")
        content = _COLUMNS * cell_w + (_COLUMNS - 1) * gap if expanded else p.px("ring_compact_width")
        width = content + 2 * inset
        top = self._banner_box(board, c, pad, pad, width)
        cards = board.cards if expanded else board.cards[:1]  # 核心保證第一張是使用中帳號（或未納管帳號）
        cells = self._cells.fit(len(cards))
        left = pad + inset
        note_left, note_right = left + p.px("ring_cell_pad"), left + content - p.px("ring_cell_pad")  # 對齊格子的內容
        first_x = left if expanded else left + (content - cell_w) / 2  # 精簡模式的一格置中
        y = top + inset
        for start in range(0, len(cards), _COLUMNS):
            row = list(zip(cells[start:start + _COLUMNS], cards[start:start + _COLUMNS]))
            xs = [first_x + i * (cell_w + gap) for i in range(len(row))]
            row_bottom = max(cell.render(card, c, x, y, cell_w) for (cell, card), x in zip(row, xs))
            for (cell, card), x in zip(row, xs):
                cell.outline(card, c, x, y, cell_w, row_bottom, framed=expanded)
            y = row_bottom
            for cell, card in row:
                y = cell.render_notes(card, board, c, note_left, note_right, y, named=len(cards) > 1)
            if start + _COLUMNS < len(cards):
                y += gap
        # 最後一列底下沒有提示時，外框離卡片底邊也是 row_inset，四個角才同心
        bottom = y + (inset if y == row_bottom else p.px("card_pad_bottom"))
        offset = p.px("shadow_offset")
        p.rrect(self._shadow, pad + offset / 2, top + offset, pad + width + offset / 2, bottom + offset,
                RADIUS["card"], c["shadow"])
        p.rrect(self._card, pad, top, pad + width, bottom, RADIUS["card"], c["card"])
        total_w, total_h = width + 2 * pad, bottom + pad
        p.rrect(self._panel, 0, 0, total_w, total_h, RADIUS["panel"], c["panel"])
        self.cv.configure(width=total_w, height=total_h)

    def _banner_box(self, board: Board, c, x, y, width):
        lines = banner_lines(board)
        if not lines:
            self._p.hide(self._banner_bg)
            self._banner.hide()
            return y
        pad = self._p.px("banner_pad")
        bottom = self._banner.render(x + pad, y + pad, width - 2 * pad, "\n".join(lines), c["banner_fg"]) + pad
        self._p.rrect(self._banner_bg, x, y, x + width, bottom, RADIUS["card"], c["banner"])
        return bottom + self._p.px("card_gap")
