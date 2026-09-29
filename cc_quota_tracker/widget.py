"""懸浮視窗骨架：無邊框、以透明色鍵挖出圓角、拖動任何位置可移動、預設置頂、雙擊切換精簡／展開；每 5 秒 poll 一次交給版面渲染。"""
import sys
import tkinter as tk
from typing import Callable, Optional

from .board import Board
from .layout_a import LayoutA
from .tokens import TRANSPARENT_KEY

POLL_MS = 5000  # 固定值，不開放設定


def enable_dpi_awareness():
    """必須在建立 Tk 之前呼叫；否則 Windows 會把整個視窗點陣放大，字變糊。"""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass  # Windows 8.1 以前沒有 shcore


class Widget:
    def __init__(self, root: tk.Tk, poll: Callable[[], Board], theme: str = "light"):
        self.root = root
        self._poll = poll
        self._theme = theme
        self._expanded = False
        self._board: Optional[Board] = None
        self._after = None
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=TRANSPARENT_KEY)
        try:
            root.attributes("-transparentcolor", TRANSPARENT_KEY)
        except tk.TclError:
            pass  # 只有 Windows 支援透明色鍵；其他平台圓角外側會露出底色
        self.canvas = tk.Canvas(root, bg=TRANSPARENT_KEY, highlightthickness=0, borderwidth=0)
        self.canvas.pack()
        self.layout = LayoutA(self.canvas)
        self._menu = tk.Menu(root, tearoff=0)
        self._menu.add_command(label="結束", command=self.close)
        root.bind("<ButtonPress-1>", self._press)
        root.bind("<B1-Motion>", self._drag)
        root.bind("<Button-3>", lambda e: self._menu.tk_popup(e.x_root, e.y_root))
        root.bind("<Double-Button-1>", lambda e: self.toggle_mode())
        self.refresh()

    def refresh(self):
        """poll 一次並渲染，再排下一輪；排程永遠只有一個。這一輪出錯也照樣排下一輪，視窗才不會就此凍結。"""
        if self._after is not None:
            self.root.after_cancel(self._after)
        try:
            self._board = self._poll()
            self.layout.render(self._board, self._theme, self._expanded)
        finally:
            self._after = self.root.after(POLL_MS, self.refresh)

    def toggle_mode(self):
        """精簡／展開互換，以上一輪的看板立即重畫；不另外 poll，也不動排程。"""
        self._expanded = not self._expanded
        if self._board is not None:
            self.layout.render(self._board, self._theme, self._expanded)

    def close(self):
        if self._after is not None:
            self.root.after_cancel(self._after)
            self._after = None
        self.layout.destroy()
        self.root.destroy()

    def _press(self, event):
        self._dx = event.x_root - self.root.winfo_x()
        self._dy = event.y_root - self.root.winfo_y()

    def _drag(self, event):
        self.root.geometry(f"+{event.x_root - self._dx}+{event.y_root - self._dy}")
