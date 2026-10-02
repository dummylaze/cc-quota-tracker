"""版面共用的字型：家族取自設定檔的 font 或設計 token，字級與字重永遠取自 token。

字型不存在時（內建或自填）一律改用 TkDefaultFont 的家族，不讓 tk 自行替換——tk 找不到字型時會換成 Arial，
中文要靠系統補字才顯示得出來。換字型只改既有 Font 物件的家族，item 用的是同一個物件，所以 item 不必重建。"""
import tkinter.font as tkfont
from typing import AbstractSet, Dict, Optional, Tuple

from .tokens import FONTS


def resolve_families(custom: Optional[str], installed: AbstractSet[str], default: str) -> Tuple[Dict[str, str], Optional[str]]:
    """回傳各角色的字型家族，以及找不到的自填字型名稱（沒有就是 None）。
    installed 是已安裝家族名稱的 casefold 集合（字型名稱不分大小寫）；default 是系統預設字型的家族。
    自填字型找不到時所有角色都用預設；內建字型找不到只有那個角色用預設，不回報，因為那不是使用者填的。"""
    if custom is not None:
        if custom.casefold() in installed:
            return {name: custom for name in FONTS}, None
        return {name: default for name in FONTS}, custom
    return {name: family if family.casefold() in installed else default for name, (family, _, _) in FONTS.items()}, None


UNDERLINED = {"link"}  # 加底線的角色：可點的文字靠底線與一般文字分開


class FontSet:
    """一組版面用的具名字型，依角色（title、body…）取用。missing 是目前找不到的自填字型名稱。"""

    def __init__(self, canvas):
        self._canvas = canvas
        self._fonts = {name: tkfont.Font(canvas, family=family, size=size, weight=weight, underline=name in UNDERLINED)
                       for name, (family, size, weight) in FONTS.items()}
        self.missing: Optional[str] = None
        self.configure(None)

    def __getitem__(self, name: str) -> tkfont.Font:
        return self._fonts[name]

    def configure(self, custom: Optional[str]) -> None:
        """換家族。呼叫端要自己重畫：字型的量測值變了，版面要重排。"""
        installed = {family.casefold() for family in tkfont.families(self._canvas)}
        default = tkfont.Font(self._canvas, name="TkDefaultFont", exists=True).actual("family")
        families, self.missing = resolve_families(custom, installed, default)
        for name, font in self._fonts.items():
            font.configure(family=families[name])

    def clear(self) -> None:
        self._fonts.clear()  # tkfont.Font 被回收時會刪掉對應的具名字型
