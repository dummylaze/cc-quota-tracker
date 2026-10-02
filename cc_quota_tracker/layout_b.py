"""版面 B（密集表格／單行條）。精簡模式是使用中帳號的一行橫條；展開模式是表格，一列一個帳號，提示接在該列下方，
使用中帳號那一列加淡色底。不與版面 A 共用版面程式碼；提示與橫幅的文案、折行取自 canvas_text，「更新」入口（item、點擊、游標）取自 entry；其餘文案取自語系檔，語系由 render 傳入、存在 _Paint.lang，切換語系只是重畫。

物件生命週期同版面 A：固定部分的 item 一次建好，之後每輪只改座標、文字、顏色與顯示狀態；數量跟著看板走的部分
（表格的列、提示、多行文字的行）由 _Pool 補建或刪到剛好，所以 item 數只由看板與模式決定。單行條只在精簡模式存在、
表格只在展開模式存在：切換模式時建立要用的那一個、刪掉另一個。每組 item 都帶自己與上層的 tag，destroy() 刪掉全部。"""
import itertools
import math
from typing import Callable, NamedTuple, Optional

from .board import Board, Card, Limit, ReadingState, Role
from .canvas_text import LINE_TAG, banner_lines, card_notes, count_dot, notes, query_entry, query_notes, reset_text, wrap
from .entry import UpdateEntry
from .fmt import absolute, account_label, age, until
from .fonts import FontSet
from .i18n import ZH_TW, text
from .tokens import FONTS, LINE_HEIGHT, RADIUS, SPACE, THEMES

TAG = "layout-b"
EXPANDED_TAG = "layout-b-expanded"  # 表格：只在展開模式存在
# 兩種模式都固定顯示這兩個窗口；名稱是單行條上的簡稱。值都是語系鍵
_WINDOWS = (("session", "window.session_short"), ("weekly_all", "window.weekly_all_short"))
_HEADERS = ("table.account", "window.session", "window.weekly_all", "table.reading", "table.credential_expiry")
_NONE = "—"
_ids = itertools.count()


class _Paint:
    """item 操作：只改屬性，不新建。"""

    def __init__(self, canvas):
        self.cv = canvas
        self.scale = canvas.winfo_fpixels("1i") / 96
        self.fonts = FontSet(canvas)
        self.lang = ZH_TW  # 這一輪使用的語系；每次 render 一開始就換成呼叫端給的

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

    def bar(self, track, fill, x1, x2, mid, percent, color, c):
        """膠囊進度條。圓頭線段的端點各往外凸出半個線寬，所以線段本身要內縮半個線寬。"""
        width = self.px("bar_height")
        start, end = x1 + width / 2, x2 - width / 2
        self.show(track, start, mid, end, mid, width=width, fill=c["track"])
        if percent:
            self.show(fill, start, mid, start + (end - start) * min(percent, 100) / 100, mid, width=width, fill=color)
        else:
            self.hide(fill)


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

    def fit(self, n):
        while len(self._groups) < n:
            self._groups.append(self._make())
        for group in self._groups[n:]:
            self._destroy(group)
        del self._groups[n:]
        return self._groups


class _Lines(_Group):
    """多行文字：自己折行、逐行一個 item，行距照 LINE_HEIGHT。"""

    def __init__(self, p, parent_tags, font):
        super().__init__(p, parent_tags)
        self.font = font
        tags = (LINE_TAG, *self.tags)
        self._lines = _Pool(lambda: p.cv.create_text(0, 0, anchor="nw", font=p.fonts[font], tags=tags), p.cv.delete)

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
    """一個窗口在畫面上的呈現。percent 為 None 時不畫進度條；foot 是已重置時補充的「下次重置時間未知」；
    reset 是有進度條的窗口的重置倒數，畫在進度條下面的小字。"""
    text: str
    font: str
    color: str  # 顏色 token
    percent: Optional[int] = None
    foot: Optional[str] = None
    reset: Optional[str] = None


def _window(lim: Optional[Limit], board: Board, lang: str) -> _Value:
    if lim is None:
        return _Value(_NONE, "small", "sub")
    if lim.reset:
        return _Value(text(lang, "limit.reset_short"), "small", "sub", foot=text(lang, "limit.next_reset_unknown"))
    if lim.percent is None:
        return _Value(text(lang, "limit.no_open_window"), "small", "sub")
    return _Value(f"{lim.percent}%", "percent", lim.severity.value, lim.percent, reset=reset_text(lim, board, lang))


def _windows(card: Card, board: Board, lang: str):
    """兩個窗口的呈現；還沒有讀數時整個是 None（精簡模式不顯示窗口，表格顯示「—」）。"""
    limits = {lim.kind: lim for lim in card.limits} if card.reading_state is ReadingState.HAS_READING else {}
    return [_window(limits.get(kind), board, lang) if limits else None for kind, _ in _WINDOWS]


def _label(card: Card, lang: str):
    return account_label(card.account_key) if card.account_key else text(lang, "account.unmanaged")


def _chip(card: Card, lang: str):
    """(狀態標籤文字, 底色 token, 文字顏色 token)。"""
    if card.role is Role.STANDBY:
        return text(lang, "role.standby"), "chip_standby", "chip_standby_fg"
    return text(lang, "role.active"), "accent", "chip_active_fg"


def _age(card: Card, lang: str):
    if card.reading_state is ReadingState.HAS_READING and card.reading_age is not None:
        return age(card.reading_age, lang)
    return None


def _expiry(card: Card, board: Board, lang: str):
    """憑證到期倒數：兩個單位＋絕對時間。失效、過期的處置寫在該列的提示裡。"""
    expires = card.snapshot_expires_at
    if card.snapshot_invalid:
        return text(lang, "expiry.invalid")
    if expires is None:
        return _NONE
    if expires <= board.as_of:
        return text(lang, "expiry.expired", when=absolute(expires, board.as_of))
    return until(expires, board.as_of, board.countdown_format, lang)


class _Strip(_Group):
    """精簡模式的橫條：帳號標籤、兩個窗口（名稱、小進度條、百分比，進度條下面一行小字是重置倒數）、讀數年齡、提示數量、
    「更新」入口（落後或讀數待更新時，接在提示數量之後）。所有窗口都沒有重置倒數時只有一行；查詢的狀態與失敗原因
    不收進提示數量，另起一行接在橫條底下。"""

    def __init__(self, p, parent_tags, on_query):
        super().__init__(p, parent_tags)
        cv, f, t = p.cv, p.fonts, self.tags
        self.label = cv.create_text(0, 0, anchor="w", font=f["title"], tags=t)
        self.windows = [(cv.create_text(0, 0, anchor="w", font=f["small"], tags=t),
                         cv.create_line(0, 0, 0, 0, capstyle="round", tags=t),
                         cv.create_line(0, 0, 0, 0, capstyle="round", tags=(*t, "bar-fill")),
                         cv.create_text(0, 0, anchor="w", tags=t),
                         cv.create_text(0, 0, anchor="w", font=f["small"], tags=t)) for _ in _WINDOWS]
        self.age = cv.create_text(0, 0, anchor="w", font=f["small"], tags=t)
        self.dot = cv.create_oval(0, 0, 0, 0, width=0, tags=t)
        self.count = cv.create_text(0, 0, anchor="w", font=f["small"], tags=t)
        self.entry = UpdateEntry(p, t, on_query)
        self.status_notes = _Pool(lambda: _Note(p, t))

    def _entry_and_status(self, card: Card, board: Board):
        """(入口, 狀態提示)：入口是 (語系鍵, 可不可點) 或 None；狀態提示是查詢中、失敗原因、自動查詢已暫停。"""
        status = board.usage_query
        entry = query_entry(card, status)
        return entry, query_notes(card, status, self.p.lang, entry is not None)

    def _parts(self, card: Card, board: Board):
        """要顯示的各段，由左而右：[(段, 寬度, 內容)]；段是 "label"、窗口的序號、"age"、"count" 或 "entry"。"""
        p, f, lang = self.p, self.p.fonts, self.p.lang
        label = _label(card, lang)
        parts = [("label", f["title"].measure(label), label)]
        for i, ((_, name_key), window) in enumerate(zip(_WINDOWS, _windows(card, board, lang))):
            if window is None:
                continue
            name = text(lang, name_key)
            value = text(lang, "sep.clause").join(filter(None, (window.text, window.foot)))
            bar = p.px("cell_bar_width") + p.px("cell_gap") if window.percent is not None else 0
            # 進度條下面的倒數比「進度條＋百分比」寬時，這一段以倒數為準
            width = f["small"].measure(name) + p.px("cell_gap") + max(
                bar + f[window.font].measure(value), f["small"].measure(window.reset or ""))
            parts.append((i, width, (name, window, value)))
        shown_age = _age(card, lang)
        if shown_age:
            parts.append(("age", f["small"].measure(shown_age), shown_age))
        shown = notes(card, board, lang, expiry_info=False)
        if shown:
            count = text(lang, "notes.count", count=len(shown))
            parts.append(("count", p.px("dot") + p.px("dot_gap") + f["small"].measure(count), (count, shown)))
        entry, _ = self._entry_and_status(card, board)
        if entry:
            parts.append(("entry", self.entry.width(), entry))
        return parts

    def width(self, card: Card, board: Board):
        """橫條的寬度。有狀態提示時至少與版面 A 的卡片同寬（扣掉內距），失敗原因才不會折成很多行。"""
        p = self.p
        parts = self._parts(card, board)
        width = sum(width for _, width, _ in parts) + p.px("col_gap") * (len(parts) - 1)
        if self._entry_and_status(card, board)[1]:
            width = max(width, p.px("card_width") - 2 * p.px("card_pad_x"))
        return width

    def render(self, card: Card, board: Board, c, x, y):
        """回傳下緣。"""
        p, f = self.p, self.p.fonts
        height = max(p.height("title"), p.height("percent"))
        mid, x_start = y + height / 2, x
        edge = x_start + self.width(card, board)  # 橫條的右緣
        parts, windows = self._parts(card, board), _windows(card, board, p.lang)
        p.hide(self.age, self.dot, self.count, *itertools.chain(*self.windows))  # 這一輪用到的下面再顯示
        entry, status = self._entry_and_status(card, board)
        if entry is None:
            self.entry.hide()  # 有入口時不先藏：藏了再顯示會把懸停中的手形游標收掉
        if any(window.reset for window in windows if window):
            foot_mid = y + height + p.px("line_gap") + p.height("small") / 2
            height += p.px("line_gap") + p.height("small")
        else:
            foot_mid = None
        for part, width, content in parts:
            if part == "label":
                p.show(self.label, x, mid, text=content, fill=c["fg"])
            elif part == "age":
                p.show(self.age, x, mid, text=content, fill=c["sub"])
            elif part == "count":
                count, shown = content
                dot = p.px("dot")
                p.show(self.dot, x, mid - dot / 2, x + dot, mid + dot / 2, fill=c[count_dot(shown)])
                p.show(self.count, x + dot + p.px("dot_gap"), mid, text=count, fill=c["fg"])
            elif part == "entry":
                self.entry.place(content, c, edge, mid)  # 靠右對齊橫條的右緣（被狀態提示撐寬時也與它對齊）
            else:
                name_item, track, fill, value_item, foot_item = self.windows[part]
                name, window, value = content
                p.show(name_item, x, mid, text=name, fill=c["sub"])
                left = x + f["small"].measure(name) + p.px("cell_gap")
                if window.percent is not None:
                    right = left + p.px("cell_bar_width")
                    p.bar(track, fill, left, right, mid, window.percent, c[window.color], c)
                    if window.reset:
                        p.show(foot_item, left, foot_mid, text=window.reset, fill=c["sub"])
                    left = right + p.px("cell_gap")
                p.show(value_item, left, mid, text=value, font=f[window.font], fill=c[window.color])
            x += width + p.px("col_gap")
        bottom = y + height
        for i, (slot, note) in enumerate(zip(self.status_notes.fit(len(status)), status)):
            bottom = slot.render(note, c, x_start, edge, bottom + p.px("section_gap" if i == 0 else "line_gap"))
        return bottom


class _Cell(_Group):
    """表格裡的一格窗口：數值、小進度條、附註（有進度條的窗口是重置倒數；已重置時是「下次重置時間未知」）。"""

    def __init__(self, p, parent_tags):
        super().__init__(p, parent_tags)
        cv, f, t = p.cv, p.fonts, self.tags
        self.value = cv.create_text(0, 0, anchor="w", tags=t)
        self.track = cv.create_line(0, 0, 0, 0, capstyle="round", tags=t)
        self.fill = cv.create_line(0, 0, 0, 0, capstyle="round", tags=(*t, "bar-fill"))
        self.foot = cv.create_text(0, 0, anchor="nw", font=f["small"], tags=t)

    def render(self, window: _Value, c, left, width, mid, below):
        """mid 是第一行的中線、below 是第一行的下緣；回傳這一格的下緣。"""
        p = self.p
        p.show(self.value, left, mid, text=window.text, font=p.fonts[window.font], fill=c[window.color])
        y = below
        if window.percent is not None:
            y += p.px("bar_gap")
            p.bar(self.track, self.fill, left, left + width, y + p.px("bar_height") / 2, window.percent,
                  c[window.color], c)
            y += p.px("bar_height")
        else:
            p.hide(self.track, self.fill)
        foot = window.reset or window.foot
        if foot:
            y += p.px("line_gap")
            p.show(self.foot, left, y, text=foot, fill=c["sub"])
            y += p.height("small")
        else:
            p.hide(self.foot)
        return y


class _TableRow(_Group):
    """表格的一列：帳號標籤與狀態標籤、兩格窗口、讀數年齡、憑證到期倒數，底下接提示；使用中帳號加淡色底。
    有「更新」入口時，它與落後（或讀數待更新）那條提示同一行靠右，查詢的狀態與失敗原因接在那條提示底下。"""

    def __init__(self, p, parent_tags, on_query):
        super().__init__(p, parent_tags)
        cv, f, t = p.cv, p.fonts, self.tags
        self.band = cv.create_polygon(0, 0, 0, 0, 0, 0, tags=t)
        self.label = cv.create_text(0, 0, anchor="w", font=f["title"], tags=t)
        self.chip = cv.create_polygon(0, 0, 0, 0, 0, 0, tags=t)
        self.chip_text = cv.create_text(0, 0, anchor="center", font=f["chip"], tags=t)
        self.cells = [_Cell(p, t) for _ in _WINDOWS]
        self.age = cv.create_text(0, 0, anchor="w", font=f["small"], tags=t)
        self.expiry = cv.create_text(0, 0, anchor="w", font=f["small"], tags=t)
        self.note_rows = _Pool(lambda: _Note(p, t))
        self.entry = UpdateEntry(p, t, on_query)

    def render(self, card: Card, board: Board, c, columns, x1, x2, y):
        """columns 是各欄的 (左緣, 寬度)；x1、x2 是卡片的左右緣。回傳這一列的下緣。"""
        p, f = self.p, self.p.fonts
        top = y
        y += p.px("row_pad_y")
        height = max(p.height("title"), p.height("percent"), p.px("chip_height"))
        mid, below = y + height / 2, y + height
        lang = p.lang
        label = _label(card, lang)
        (label_x, _), *window_cols, (age_x, _), (expiry_x, _) = columns
        p.show(self.label, label_x, mid, text=label, fill=c["fg"])
        chip, chip_bg, chip_fg = _chip(card, lang)
        chip_x = label_x + f["title"].measure(label) + p.px("chip_gap")
        chip_w, chip_h = _chip_width(p, chip), p.px("chip_height")
        p.rrect(self.chip, chip_x, mid - chip_h / 2, chip_x + chip_w, mid + chip_h / 2, RADIUS["chip"], c[chip_bg])
        p.show(self.chip_text, chip_x + chip_w / 2, mid, text=chip, fill=c[chip_fg])
        bottom = below
        for cell, (left, width), window in zip(self.cells, window_cols, _windows(card, board, lang)):
            bottom = max(bottom, cell.render(window or _window(None, board, lang), c, left, width, mid, below))
        shown_age = _age(card, lang)
        p.show(self.age, age_x, mid, text=shown_age or _NONE, fill=c["sub"])
        expiry = _expiry(card, board, lang)
        p.show(self.expiry, expiry_x, mid, text=expiry, fill=c["sub" if expiry == _NONE else "fg"])
        y = bottom
        left, right = x1 + p.px("card_pad_x"), x2 - p.px("card_pad_x")
        shown, host = card_notes(card, board, lang, expiry_info=False)
        entry, reserve = query_entry(card, board.usage_query), 0
        for i, (slot, note) in enumerate(zip(self.note_rows.fit(len(shown)), shown)):
            y += p.px("section_gap" if i == 0 else "line_gap")
            if i == host:
                reserve = self.entry.place(entry, c, right, y + p.pitch("small") / 2)
            y = slot.render(note, c, left, right - reserve if i == host else right, y)
        if host is None:
            self.entry.hide()
        y += p.px("row_pad_y")
        if card.role is Role.STANDBY:
            p.hide(self.band)
        else:
            inset = p.px("row_inset")
            p.rrect(self.band, x1 + inset, top, x2 - inset, y, RADIUS["row"], c["active_row"])
        return y


def _chip_width(p: _Paint, chip):
    return p.fonts["chip"].measure(chip) + 2 * p.px("chip_pad_x")


class _Table(_Group):
    """展開模式的表格：欄名一列，接著一列一個帳號。"""

    def __init__(self, p, parent_tags, on_query):
        super().__init__(p, (*parent_tags, EXPANDED_TAG))
        cv, f, t = p.cv, p.fonts, self.tags
        self.headers = [cv.create_text(0, 0, anchor="w", font=f["small"], tags=t) for _ in _HEADERS]
        self.rows = _Pool(lambda: _TableRow(p, t, on_query))

    def columns(self, board: Board):
        """各欄寬度：欄名與這一輪每一列內容的最大寬度；窗口欄至少容得下小進度條。"""
        p, f, lang = self.p, self.p.fonts, self.p.lang
        widths = [f["small"].measure(text(lang, key)) for key in _HEADERS]
        for i in (1, 2):
            widths[i] = max(widths[i], p.px("cell_bar_width"))
        for card in board.cards:
            chip = _chip_width(p, _chip(card, lang)[0])
            widths[0] = max(widths[0], f["title"].measure(_label(card, lang)) + p.px("chip_gap") + chip)
            for i, window in enumerate(_windows(card, board, lang), start=1):
                window = window or _window(None, board, lang)
                widths[i] = max(widths[i], f[window.font].measure(window.text),
                                f["small"].measure(window.reset or window.foot or ""))
            widths[3] = max(widths[3], f["small"].measure(_age(card, lang) or _NONE))
            widths[4] = max(widths[4], f["small"].measure(_expiry(card, board, lang)))
        return widths

    def render(self, board: Board, c, widths, x1, x2, y):
        """回傳下緣。"""
        p = self.p
        columns, x = [], x1 + p.px("card_pad_x")
        for width in widths:
            columns.append((x, width))
            x += width + p.px("col_gap")
        mid = y + p.height("small") / 2
        for item, header, (left, _) in zip(self.headers, _HEADERS, columns):
            p.show(item, left, mid, text=text(p.lang, header), fill=c["sub"])
        y += p.height("small") + p.px("line_gap")
        for row, card in zip(self.rows.fit(len(board.cards)), board.cards):
            y = row.render(card, board, c, columns, x1, x2, y)
        return y


class LayoutB:
    def __init__(self, canvas, on_query: Optional[Callable[[], None]] = None):
        """on_query：使用者按下「更新」時呼叫；None 就什麼都不做（只畫、不接線的呼叫端，例如測試）。"""
        self.cv = canvas
        self._on_query = on_query
        self._p = p = _Paint(canvas)
        self._panel = canvas.create_polygon(0, 0, 0, 0, 0, 0, tags=TAG)
        self._banner_bg = canvas.create_polygon(0, 0, 0, 0, 0, 0, tags=TAG)
        self._banner = _Lines(p, (TAG,), "body")
        self._shadow = canvas.create_polygon(0, 0, 0, 0, 0, 0, tags=TAG)
        self._card = canvas.create_polygon(0, 0, 0, 0, 0, 0, tags=TAG)
        self._strip: Optional[_Strip] = None
        self._table: Optional[_Table] = None

    def set_font(self, custom):
        """換字型（設定檔的 font，None 用內建字型）：只改既有字型物件的家族，item 不重建；呼叫端接著要重新 render。"""
        self._p.fonts.configure(custom)

    def destroy(self):
        self.cv.delete(TAG)
        self._p.fonts.clear()  # tkfont.Font 被回收時會刪掉對應的具名字型
        self._strip = self._table = None

    def render(self, board: Board, theme: str, expanded: bool = False, lang: str = ZH_TW):
        """lang 的預設值只給不在意語系的呼叫端（測試）；視窗每輪都明確傳入。"""
        p, c = self._p, THEMES[theme]
        p.lang = lang
        pad, pad_x = p.px("panel_pad"), p.px("card_pad_x")
        if expanded:
            if self._strip is not None:
                self._strip.destroy()
                self._strip = None
            if self._table is None:
                self._table = _Table(p, (TAG,), self._on_query)
            widths = self._table.columns(board)
            width = sum(widths) + p.px("col_gap") * (len(widths) - 1) + 2 * pad_x
        else:
            if self._table is not None:
                self._table.destroy()
                self._table = None
            if self._strip is None:
                self._strip = _Strip(p, (TAG,), self._on_query)
            card = board.cards[0]  # 核心保證第一張是使用中帳號（或未納管帳號）
            width = self._strip.width(card, board) + 2 * pad_x
        top = self._banner_box(board, c, pad, pad, width)
        if expanded:
            bottom = self._table.render(board, c, widths, pad, pad + width, top + p.px("card_pad_top"))
        else:
            bottom = self._strip.render(card, board, c, pad + pad_x, top + p.px("card_pad_top"))
        bottom += p.px("card_pad_bottom")
        offset = p.px("shadow_offset")
        p.rrect(self._shadow, pad + offset / 2, top + offset, pad + width + offset / 2, bottom + offset,
                RADIUS["card"], c["shadow"])
        p.rrect(self._card, pad, top, pad + width, bottom, RADIUS["card"], c["card"])
        total_w, total_h = width + 2 * pad, bottom + pad
        p.rrect(self._panel, 0, 0, total_w, total_h, RADIUS["panel"], c["panel"])
        self.cv.configure(width=total_w, height=total_h)

    def _banner_box(self, board: Board, c, x, y, width):
        lines = banner_lines(board, self._p.lang, self._p.fonts.missing)
        if not lines:
            self._p.hide(self._banner_bg)
            self._banner.hide()
            return y
        pad = self._p.px("banner_pad")
        bottom = self._banner.render(x + pad, y + pad, width - 2 * pad, "\n".join(lines), c["banner_fg"]) + pad
        self._p.rrect(self._banner_bg, x, y, x + width, bottom, RADIUS["card"], c["banner"])
        return bottom + self._p.px("card_gap")
