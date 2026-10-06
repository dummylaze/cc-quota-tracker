"""切換中蓋在整個視窗上的半透明圖層：面板色的點陣填色（底下的內容隱約可見），蓋住視窗的圓角外形；
有步驟文字時在正中央放一塊卡片色的底、前景色的字（對比取自 token，不另外挑色）。
圖層的 item 帶 TAG，每次 show 整批重建，所以一定在最上面：版面重畫之後新建的 item 不會跑到圖層上面。
點擊落在圖層上，底下的版面（摺疊區標題、「更新」）收不到；拖動與雙擊走視窗的綁定，照常運作。"""
import math
from typing import List, Optional

from .fonts import FontSet
from .tokens import RADIUS, SPACE, THEMES

TAG = "switch-overlay"
VEIL_STIPPLE = "gray50"  # 半透明：隔一個像素蓋一個


def _rounded(x1: float, y1: float, x2: float, y2: float, radius: float):
    """圓角矩形的折線頂點，順時針；折線逼近四分之一圓（理由同版面的 rrect）。"""
    r = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    steps = max(1, math.ceil(r / 2))
    points: List[float] = []
    for cx, cy, start in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0), (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
        for i in range(steps + 1):
            angle = math.radians(start + 90 * i / steps)
            points += (cx + r * math.cos(angle), cy + r * math.sin(angle))
    return points


class SwitchOverlay:
    """圖層的畫法；什麼時候蓋、蓋什麼文字由視窗決定。"""

    def __init__(self, canvas):
        self.cv = canvas
        self.scale = canvas.winfo_fpixels("1i") / 96
        self.fonts = FontSet(canvas)

    def set_font(self, custom: Optional[str]) -> None:
        """跟著版面的字型（設定檔的 font）；呼叫端接著要重新 show。"""
        self.fonts.configure(custom)

    def show(self, theme: str, message: Optional[str]) -> None:
        """蓋上圖層（已經蓋著就重建一次）。message 是要顯示的步驟文字（已經翻好語系），None 就只有半透明的一層。"""
        self.hide()
        cv, c = self.cv, THEMES[theme]
        width, height = cv.winfo_reqwidth(), cv.winfo_reqheight()  # 版面 render 時設定的視窗大小
        cv.create_polygon(*_rounded(0, 0, width, height, RADIUS["panel"] * self.scale), fill=c["panel"],
                          stipple=VEIL_STIPPLE, outline="", tags=TAG)
        if message is None:
            return
        pad = round(SPACE["banner_pad"] * self.scale)
        wrap = width - 2 * round(SPACE["panel_pad"] * self.scale) - 2 * pad
        label = cv.create_text(width / 2, height / 2, text=message, font=self.fonts["body"], fill=c["fg"],
                               width=wrap, justify="center", tags=TAG)
        left, top, right, bottom = cv.bbox(label)
        backing = cv.create_polygon(*_rounded(left - pad, top - pad, right + pad, bottom + pad,
                                              RADIUS["card"] * self.scale), fill=c["card"], outline="", tags=TAG)
        cv.tag_lower(backing, label)

    def hide(self) -> None:
        self.cv.delete(TAG)

    def destroy(self) -> None:
        self.hide()
        self.fonts.clear()
