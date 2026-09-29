"""版面 A（卡片列表）。精簡模式只畫使用中帳號那一張卡片；展開模式每個帳號一張卡片，使用中帳號多出展開專用資料。
提示與橫幅的文案、折行取自 canvas_text。

物件生命週期：固定部分的 item 在建構時一次建好，之後每輪只改座標、文字、顏色與顯示狀態，用不到的設成 hidden。
數量跟著看板走的部分（卡片、範圍週限額、用量去向、其他限額）由 _Pool 補建或刪到剛好的數量，所以 item 數只由
看板、模式與摺疊區開合決定：三者相同時 item 數永遠相同。展開專用的 item 第一次以展開模式渲染時才建立，
回到精簡模式就刪掉。每組 item 都帶自己與上層的 tag，刪一組就是刪它的 tag；destroy() 刪掉全部。
多行文字（附註、提示、橫幅）自己折行、逐行一個 item，行數同樣由 _Pool 補建或刪到剛好。"""
import itertools
import math
from typing import Optional

from .board import Board, Card, Limit, ReadingState, Role
from .canvas_text import LINE_TAG, banner_lines, notes, wrap
from .fmt import absolute, account_label, age, money, until
from .fonts import FontSet
from .tokens import FONTS, LINE_HEIGHT, RADIUS, SPACE, THEMES

TAG = "layout-a"
EXPANDED_TAG = "layout-a-expanded"  # 展開專用的 item
CLICKABLE_TAG = "clickable"  # 自己處理點擊的 item：視窗的雙擊切換模式在它上面不作用
_WINDOWS = (("session", "工作階段窗口"), ("weekly_all", "週窗口"))  # 兩種模式都固定顯示這兩個窗口
_NOTE_SLOTS = 4  # 一張卡片的提示最多幾條：讀數說明或未納管、落後、鎖定、憑證快照，實際同時最多 3 條
_ids = itertools.count()


class _Paint:
    """item 操作：只改屬性，不新建。"""

    def __init__(self, canvas):
        self.cv = canvas
        self.scale = canvas.winfo_fpixels("1i") / 96
        self.fonts = FontSet(canvas)

    def px(self, key):
        return round(SPACE[key] * self.scale)

    def pitch(self, font):
        """多行文字的行距：字級像素 × LINE_HEIGHT，不小於字型本身的 linespace。"""
        size_px = FONTS[font][1] * self.cv.winfo_fpixels("1i") / 72
        return max(self.fonts[font].metrics("linespace"), math.ceil(LINE_HEIGHT * size_px))

    def text(self, item, x, y, width, text, color):
        """單行標題（用量去向、其他限額）：回傳它的下緣。太長時 tk 會自己折行，行距是字型的 linespace；
        會折成多行的內文改用 _Text。"""
        self.show(item, x, y, text=text, fill=color, width=width)
        return self.cv.bbox(item)[3]

    def show(self, item, *coords, **options):
        self.cv.coords(item, *coords)
        self.cv.itemconfigure(item, state="normal", **options)

    def hide(self, *items):
        for item in items:
            self.cv.itemconfigure(item, state="hidden")

    def rrect(self, item, x1, y1, x2, y2, radius, color, **options):
        """圓角以折線逼近四分之一圓。不用 smooth 多邊形：它只經過相鄰兩點的中點，畫出的半徑只有一半。"""
        r = max(0, min(self.scale * radius, (x2 - x1) / 2, (y2 - y1) / 2))
        steps = max(1, math.ceil(r / 2))
        points = []
        # 順時針：右上、右下、左下、左上，各從角度 start 轉 90 度（畫面座標 y 朝下）
        for cx, cy, start in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0), (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
            for i in range(steps + 1):
                angle = math.radians(start + 90 * i / steps)
                points += (cx + r * math.cos(angle), cy + r * math.sin(angle))
        self.show(item, *points, **{"fill": color, "outline": "", **options})

    def row(self, row: "_Row", left, right, y, name, value, value_font, value_color, percent, bar_color, foot, c):
        """名稱與數值一列、底下一條膠囊進度條，再底下一行附註（foot 為 None 就不顯示）；回傳下緣。"""
        f = self.fonts
        height = max(f["body"].metrics("linespace"), f[value_font].metrics("linespace"))
        mid = y + height / 2
        self.show(row.name, left, mid, text=name, fill=c["sub"])
        self.show(row.value, right, mid, text=value, font=f[value_font], fill=value_color)
        y += height + self.px("bar_gap")
        bar = self.px("bar_height")
        # 圓頭線段的端點各往外凸出半個線寬，所以線段本身要內縮半個線寬
        start, end, bar_mid = left + bar / 2, right - bar / 2, y + bar / 2
        self.show(row.track, start, bar_mid, end, bar_mid, width=bar, fill=c["track"])
        if percent:
            self.show(row.fill, start, bar_mid, start + (end - start) * min(percent, 100) / 100, bar_mid,
                      width=bar, fill=bar_color)
        else:
            self.hide(row.fill)
        y += bar
        if foot is None:
            row.foot.hide()
            return y
        return row.foot.render(left, y + self.px("line_gap"), right - left, foot, c["sub"])


class _Group:
    """一組 item：帶著上層的 tag 再加一個自己的，刪掉自己的 tag 就連同底下各組一起刪掉。"""

    def __init__(self, p: _Paint, parent_tags):
        self.p = p
        self.tags = (*parent_tags, f"{TAG}-{next(_ids)}")

    def destroy(self):
        self.p.cv.delete(self.tags[-1])


class _Pool:
    """數量跟著看板走的同款 item 組：補建或刪到剛好 n 組。destroy 預設是組自己的 destroy()。"""

    def __init__(self, make, destroy=None):
        self._make, self._destroy, self._groups = make, destroy or (lambda group: group.destroy()), []

    def fit(self, n):
        while len(self._groups) < n:
            self._groups.append(self._make())
        for group in self._groups[n:]:
            self._destroy(group)
        del self._groups[n:]
        return self._groups


class _Text(_Group):
    """多行文字：tk 的 canvas 文字沒有行距選項，所以自己折行、逐行一個 item，行距照 LINE_HEIGHT。"""

    def __init__(self, p, parent_tags, font):
        super().__init__(p, parent_tags)
        self.font = font
        tags = (LINE_TAG, *self.tags)
        self._lines = _Pool(lambda: p.cv.create_text(0, 0, anchor="nw", font=p.fonts[font], tags=tags), p.cv.delete)

    def render(self, x, y, width, text, color):
        """回傳下緣。行距多出的部分上下各半，所以第一行的字也在自己那一行的中間。"""
        p = self.p
        lines = wrap(p.fonts[self.font], text, width)
        pitch = p.pitch(self.font)
        top = y + (pitch - p.fonts[self.font].metrics("linespace")) / 2
        for i, (item, line) in enumerate(zip(self._lines.fit(len(lines)), lines)):
            p.show(item, x, top + i * pitch, text=line, fill=color)
        return y + len(lines) * pitch

    def hide(self):
        self._lines.fit(0)  # 行數只由顯示中的文字決定，所以藏起來就是刪到 0 行


class _Row(_Group):
    """一列限額：名稱、數值、進度條（底軌＋填色）、附註。"""

    def __init__(self, p, parent_tags):
        super().__init__(p, parent_tags)
        cv, f, t = p.cv, p.fonts, self.tags
        self.name = cv.create_text(0, 0, anchor="w", font=f["body"], tags=t)
        self.value = cv.create_text(0, 0, anchor="e", tags=t)
        self.track = cv.create_line(0, 0, 0, 0, capstyle="round", tags=t)
        self.fill = cv.create_line(0, 0, 0, 0, capstyle="round", tags=(*t, "bar-fill"))
        self.foot = _Text(p, t, "small")

    def hide(self):
        self.p.hide(self.name, self.value, self.track, self.fill)
        self.foot.hide()


class _Pair(_Group):
    """用量去向的一列：名稱靠左、百分比靠右。"""

    def __init__(self, p, parent_tags):
        super().__init__(p, parent_tags)
        cv, f = p.cv, p.fonts
        self.name = _Text(p, self.tags, "small")
        self.value = cv.create_text(0, 0, anchor="ne", font=f["small"], tags=self.tags)

    def render(self, name, value, c, left, right, y):
        p = self.p
        first_line = y + (p.pitch("small") - p.fonts["small"].metrics("linespace")) / 2  # 與名稱的第一行同高
        p.show(self.value, right, first_line, text=value, fill=c["fg"])
        return self.name.render(left, y, right - left - p.fonts["small"].measure(value), name, c["fg"])


class _Note(_Group):
    """一條提示：嚴重度色點＋文字。"""

    def __init__(self, p, parent_tags):
        super().__init__(p, parent_tags)
        self.dot = p.cv.create_oval(0, 0, 0, 0, width=0, tags=self.tags)
        self.text = _Text(p, self.tags, "small")

    def render(self, note, c, left, right, y):
        text, dot_key, text_key = note
        p = self.p
        dot, gap = p.px("dot"), p.px("dot_gap")
        top = y + (p.pitch("small") - dot) / 2  # 對齊第一行
        p.show(self.dot, left, top, left + dot, top + dot, fill=c[dot_key])
        return self.text.render(left + dot + gap, y, right - left - dot - gap, text, c[text_key])

    def hide(self):
        self.p.hide(self.dot)
        self.text.hide()


class _Extras(_Group):
    """使用中帳號的展開專用資料：範圍週限額、週窗口起訖進度、用量去向、額外用量、花費、其他限額（摺疊區）。"""

    def __init__(self, p, parent_tags, on_toggle_others):
        super().__init__(p, (*parent_tags, EXPANDED_TAG))
        cv, f, t = p.cv, p.fonts, self.tags
        self.scoped = _Pool(lambda: _Row(p, t))
        self.week = _Row(p, t)
        self.breakdown_title = cv.create_text(0, 0, anchor="nw", font=f["body"], tags=t)
        self.breakdown = _Pool(lambda: _Pair(p, t))
        self.extra = _Row(p, t)
        self.spend = _Row(p, t)
        self.others_title = cv.create_text(0, 0, anchor="nw", font=f["body"], tags=(*t, CLICKABLE_TAG))
        cv.tag_bind(self.others_title, "<Button-1>", lambda e: on_toggle_others())
        self.others = _Pool(lambda: _Row(p, t))

    def render(self, card: Card, board: Board, c, left, right, y, others_open):
        p = self.p
        gap = p.px("section_gap")
        for row, lim in zip(self.scoped.fit(len(card.scoped_limits)), card.scoped_limits):
            name = f"週限額（{lim.scope}）" if lim.scope else "週限額"
            y = _limit_row(p, row, name, lim, board, c, left, right, y + gap, dollars=True)
        b = card.weekly_breakdown
        if b and b.started_at and b.ends_at and b.ends_at > b.started_at:
            passed = min(max(int((board.as_of - b.started_at) / (b.ends_at - b.started_at) * 100), 0), 100)
            span = f"本週 {absolute(b.started_at, board.as_of)} ～ {absolute(b.ends_at, board.as_of)}"
            y = p.row(self.week, left, right, y + gap, span, f"已過 {passed}%", "body", c["sub"], passed,
                      c["neutral"], None, c)
        else:
            self.week.hide()
        rows = b.rows if b else ()
        if rows:
            y = p.text(self.breakdown_title, left, y + gap, right - left, "本週用量去向", c["fg"])
            for pair, r in zip(self.breakdown.fit(len(rows)), rows):
                y = pair.render(r.label, f"{r.percent}%", c, left, right, y + p.px("line_gap"))
        else:
            p.hide(self.breakdown_title)
            self.breakdown.fit(0)
        e = card.extra_usage
        if e:
            y = p.row(self.extra, left, right, y + gap, "額外用量", f"{money(e.used)} / {money(e.limit)}", "body",
                      c["fg"], e.percent, c["neutral"], None, c)
        else:
            self.extra.hide()
        s = card.spend
        if s:
            y = p.row(self.spend, left, right, y + gap, "花費", f"{money(s.used)} / {money(s.limit)}", "body",
                      c["fg"], s.percent, c[s.severity.value], None, c)
        else:
            self.spend.hide()
        others = card.other_limits
        if others:
            title = f"{'▾' if others_open else '▸'} 其他限額（{len(others)}）"
            y = p.text(self.others_title, left, y + gap, right - left, title, c["sub"])
        else:
            p.hide(self.others_title)
        shown = others if others_open else ()
        for row, lim in zip(self.others.fit(len(shown)), shown):
            y = _limit_row(p, row, lim.kind, lim, board, c, left, right, y + gap, dollars=True)
        return y


class _CardView(_Group):
    """一張帳號卡片。展開專用的部分只有展開模式的使用中帳號（或未納管帳號）才建立。"""

    def __init__(self, p, on_toggle_others):
        super().__init__(p, (TAG,))
        cv, f, t = p.cv, p.fonts, self.tags
        self.shadow = cv.create_polygon(0, 0, 0, 0, 0, 0, tags=t)
        self.card = cv.create_polygon(0, 0, 0, 0, 0, 0, tags=t)
        self.title = cv.create_text(0, 0, anchor="w", font=f["title"], tags=t)
        self.chip = cv.create_polygon(0, 0, 0, 0, 0, 0, tags=t)
        self.chip_text = cv.create_text(0, 0, anchor="center", font=f["chip"], tags=t)
        self.age = cv.create_text(0, 0, anchor="e", font=f["small"], tags=t)
        self.windows = [_Row(p, t) for _ in _WINDOWS]
        self.notes = [_Note(p, t) for _ in range(_NOTE_SLOTS)]
        self.extras: Optional[_Extras] = None
        self._on_toggle_others = on_toggle_others

    def render(self, card: Card, board: Board, c, x, y, expanded, others_open):
        p = self.p
        width = p.px("card_width")
        left, right = x + p.px("card_pad_x"), x + width - p.px("card_pad_x")
        top = y
        y = self._header(card, c, left, right, y + p.px("card_pad_top"))
        limits = {lim.kind: lim for lim in card.limits} if card.reading_state is ReadingState.HAS_READING else {}
        for row, (kind, name) in zip(self.windows, _WINDOWS):
            lim = limits.get(kind)
            if lim is None:
                row.hide()
                continue
            y = _limit_row(p, row, name, lim, board, c, left, right, y + p.px("section_gap"), dollars=expanded)
        shown = notes(card, board)
        for i, slot in enumerate(self.notes):
            if i >= len(shown):
                slot.hide()
                continue
            y = slot.render(shown[i], c, left, right, y + p.px("section_gap" if i == 0 else "line_gap"))
        if expanded and card.role is not Role.STANDBY:
            if self.extras is None:
                self.extras = _Extras(p, self.tags, self._on_toggle_others)
            y = self.extras.render(card, board, c, left, right, y, others_open)
        elif self.extras is not None:
            self.extras.destroy()
            self.extras = None
        bottom = y + p.px("card_pad_bottom")
        offset = p.px("shadow_offset")
        p.rrect(self.shadow, x + offset / 2, top + offset, x + width + offset / 2, bottom + offset,
                RADIUS["card"], c["shadow"])
        highlight = card.role is not Role.STANDBY
        p.rrect(self.card, x, top, x + width, bottom, RADIUS["card"], c["card"],
                outline=c["accent"] if highlight else "", width=p.px("highlight"))  # 沒有外框時線寬不起作用
        return bottom

    def _header(self, card: Card, c, left, right, y):
        p, f = self.p, self.p.fonts
        label = account_label(card.account_key) if card.account_key else "未納管帳號"
        height = f["title"].metrics("linespace")
        mid = y + height / 2
        p.show(self.title, left, mid, text=label, fill=c["fg"])
        standby = card.role is Role.STANDBY
        chip = "待命" if standby else "使用中"
        chip_x = left + f["title"].measure(label) + p.px("chip_gap")
        chip_w = f["chip"].measure(chip) + 2 * p.px("chip_pad_x")
        chip_h = p.px("chip_height")
        p.rrect(self.chip, chip_x, mid - chip_h / 2, chip_x + chip_w, mid + chip_h / 2, RADIUS["chip"],
                c["chip_standby" if standby else "accent"])
        p.show(self.chip_text, chip_x + chip_w / 2, mid, text=chip,
               fill=c["chip_standby_fg" if standby else "chip_active_fg"])
        if card.reading_state is ReadingState.HAS_READING and card.reading_age is not None:
            p.show(self.age, right, mid, text=("觀測 " if standby else "讀數 ") + age(card.reading_age), fill=c["sub"])
        else:
            p.hide(self.age)
        return y + max(height, chip_h)


class LayoutA:
    def __init__(self, canvas):
        self.cv = canvas
        self._p = p = _Paint(canvas)
        self._panel = canvas.create_polygon(0, 0, 0, 0, 0, 0, tags=TAG)
        self._banner_bg = canvas.create_polygon(0, 0, 0, 0, 0, 0, tags=TAG)
        self._banner = _Text(p, (TAG,), "body")
        self._cards = _Pool(lambda: _CardView(p, self.toggle_other_limits))
        self._others_open = False
        self._last = None

    def set_font(self, custom):
        """換字型（設定檔的 font，None 用內建字型）：只改既有字型物件的家族，item 不重建；呼叫端接著要重新 render。"""
        self._p.fonts.configure(custom)

    def destroy(self):
        self.cv.delete(TAG)
        self._p.fonts.clear()  # tkfont.Font 被回收時會刪掉對應的具名字型
        self._last = None

    def render(self, board: Board, theme: str, expanded: bool = False):
        self._last = (board, theme, expanded)
        p, c = self._p, THEMES[theme]
        pad, width = p.px("panel_pad"), p.px("card_width")
        y = self._banner_box(board, c, pad, pad, width)
        cards = board.cards if expanded else board.cards[:1]  # 核心保證第一張是使用中帳號（或未納管帳號）
        for i, (view, card) in enumerate(zip(self._cards.fit(len(cards)), cards)):
            y = view.render(card, board, c, pad, y + (p.px("card_gap") if i else 0), expanded, self._others_open)
        total_w, total_h = width + 2 * pad, y + pad
        p.rrect(self._panel, 0, 0, total_w, total_h, RADIUS["panel"], c["panel"])
        self.cv.configure(width=total_w, height=total_h)

    def toggle_other_limits(self):
        """開合其他限額的摺疊區，以上一次的看板重畫。"""
        self._others_open = not self._others_open
        if self._last is not None:
            self.render(*self._last)

    def _banner_box(self, board: Board, c, x, y, width):
        lines = banner_lines(board, self._p.fonts.missing)
        if not lines:
            self._p.hide(self._banner_bg)
            self._banner.hide()
            return y
        pad = self._p.px("banner_pad")
        bottom = self._banner.render(x + pad, y + pad, width - 2 * pad, "\n".join(lines), c["banner_fg"]) + pad
        self._p.rrect(self._banner_bg, x, y, x + width, bottom, RADIUS["card"], c["banner"])
        return bottom + self._p.px("card_gap")


def _limit_row(p: _Paint, row: _Row, name: str, lim: Limit, board: Board, c, left, right, y, dollars: bool):
    if lim.reset:
        value, font, color = "已重置，下次重置時間未知", "body", c["sub"]
    elif lim.percent is None:
        value, font, color = "無計時中窗口", "body", c["sub"]
    else:
        value, font, color = f"{lim.percent}%", "percent", c[lim.severity.value]
    foot = _reset_text(lim, board)
    if dollars and lim.dollars and lim.dollars.used is not None:
        foot = " · ".join(filter(None, (foot, f"已用 ${lim.dollars.used:g}")))
    return p.row(row, left, right, y, name, value, font, color, lim.percent, color, foot, c)


def _reset_text(lim: Limit, board: Board) -> Optional[str]:
    if lim.reset:
        return None  # 已經寫在數值那一格
    if lim.resets_at is not None:
        return "重置：" + until(lim.resets_at, board.as_of, board.countdown_format)
    return None if lim.percent is None else "重置：未知"
