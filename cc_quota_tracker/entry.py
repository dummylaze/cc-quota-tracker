"""卡片上可點的「更新」入口：三種版面共用的一個 Canvas 文字 item。標籤與可不可點由 canvas_text.query_entry 決定，
這裡只管畫（位置、字型、顏色）與點擊、游標；版面只提供自己的 _Paint（cv、fonts、lang、px、show、hide）。"""
from typing import Callable, Optional, Tuple

from .canvas_text import ENTRY_LABELS
from .i18n import text

CLICKABLE_TAG = "clickable"  # 自己處理點擊的 item：視窗的雙擊切換模式在它上面不作用；「更新」只有可點時才帶


class UpdateEntry:
    def __init__(self, p, tags, on_click: Optional[Callable[[], None]]):
        """p：版面的 _Paint；tags：入口 item 所屬的組；on_click：按下時呼叫，None 就什麼都不做（只畫、不接線的呼叫端）。"""
        cv = p.cv
        self._p, self._tags, self._on_click = p, tags, on_click
        self.item = cv.create_text(0, 0, anchor="e", tags=tags)
        self._clickable = False
        cv.tag_bind(self.item, "<Button-1>", lambda e: self._click())
        cv.tag_bind(self.item, "<Enter>", lambda e: cv.configure(cursor="hand2" if self._clickable else ""))
        cv.tag_bind(self.item, "<Leave>", lambda e: cv.configure(cursor=""))

    def _click(self):
        if self._clickable and self._on_click is not None:  # 查詢中與冷卻中不可點，item 沒有 CLICKABLE_TAG，這裡再擋一次
            self._on_click()

    def width(self) -> int:
        """入口文字的寬度：取兩種標籤的較大者，旁邊的版面才不會隨進行中與否變來變去。"""
        p = self._p
        return max(p.fonts["link"].measure(text(p.lang, label)) for label in ENTRY_LABELS)

    def place(self, entry: Tuple[str, bool], c, right, mid) -> int:
        """把入口放在右緣 right、垂直中線 mid，回傳它佔掉的寬度（含與旁邊文字之間的空隙）。entry 是 (語系鍵, 可不可點)。"""
        p = self._p
        key, clickable = entry
        font = p.fonts["link"]
        was_clickable, self._clickable = self._clickable, clickable
        tags = (*self._tags, CLICKABLE_TAG) if clickable else self._tags  # 不可點時不帶 CLICKABLE_TAG，雙擊照常切換模式
        p.cv.itemconfigure(self.item, tags=tags)
        p.show(self.item, right, mid, text=text(p.lang, key),
               font=font if clickable else p.fonts["small"], fill=c["fg"] if clickable else c["sub"])
        self._release_cursor(was_clickable)
        return self.width() + p.px("entry_gap")

    def hide(self):
        was_clickable, self._clickable = self._clickable, False
        self._p.hide(self.item)
        self._release_cursor(was_clickable)

    def _release_cursor(self, was_clickable):
        if was_clickable and not self._clickable:
            self._p.cv.configure(cursor="")  # 懸停期間入口變成不可點或被藏起來：<Leave> 不會觸發，手形游標要自己收掉
