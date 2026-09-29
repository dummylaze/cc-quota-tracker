"""懸浮視窗：無邊框、以透明色鍵挖出圓角、拖動任何位置可移動、雙擊切換精簡／展開；每 5 秒 poll 一次交給版面渲染。
右鍵選單調整偏好與納管帳號。偏好每輪取自看板（核心依設定檔的修改時間重讀），GUI 的改動合併寫回設定檔；
主題選「跟隨系統」時每輪讀一次 Windows 的應用程式深淺色；
視窗位置存在納管目錄的工具狀態，不進設定檔。"""
import json
import os
import subprocess
import sys
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Callable, Optional, Tuple

from . import atomic
from .board import Board, Preferences
from .core import STATE_DIR, AddWarning, InvalidLabel, NoCredential
from .layout_a import CLICKABLE_TAG, LayoutA
from .permissions import make_private
from .fmt import account_label
from .render_text import ADD_NOT_BOUND, ADD_WARNINGS, IMPORT_NOT_BOUND, INVALID_LABEL, NO_CREDENTIAL, NOT_A_CREDENTIAL_FILE
from .settings import PREFERENCE_FIELDS, ResolvedPaths, write_preference
from .tokens import TRANSPARENT_KEY

POLL_MS = 5000  # 固定值，不開放設定
DEFAULT_POSITION = (40, 40)  # 主螢幕上的位置：第一次啟動，或上次的位置已經不在任何螢幕內
_GRIP = 20  # 判斷位置在不在螢幕內時，看視窗左上角往內這麼多的那一點：要拖得到視窗才算在螢幕內
_TITLE = "cc-quota-tracker"
_ATTRS = {field: attr for field, (attr, _) in PREFERENCE_FIELDS.items()}
_MODES = (("精簡", "compact"), ("展開", "expanded"))
_THEMES = (("跟隨系統", "system"), ("淺色", "light"), ("深色", "dark"))
_OPACITIES = PREFERENCE_FIELDS["opacity"][1]
_PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"  # 登錄機碼，在 HKEY_CURRENT_USER 底下


def enable_dpi_awareness():
    """必須在建立 Tk 之前呼叫；否則 Windows 會把整個視窗點陣放大，字變糊。"""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass  # Windows 8.1 以前沒有 shcore


def on_any_screen(root: tk.Misc) -> Callable[[int, int], bool]:
    """這一點是否落在任何一個螢幕內。Windows 問作業系統（多螢幕、主螢幕左上方的負座標都算）；其他平台只認主螢幕。"""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        monitor_from_point = ctypes.windll.user32.MonitorFromPoint
        monitor_from_point.argtypes = (wintypes.POINT, wintypes.DWORD)
        monitor_from_point.restype = wintypes.HMONITOR
        return lambda x, y: bool(monitor_from_point(wintypes.POINT(x, y), 0))  # 0：不在任何螢幕內時回傳 NULL
    return lambda x, y: 0 <= x < root.winfo_screenwidth() and 0 <= y < root.winfo_screenheight()


def windows_app_theme() -> str:
    """Windows 的應用程式深淺色（light／dark）。讀不到（Windows 10 1809 以前沒有這個值、或不是 Windows）就當淺色。"""
    if sys.platform != "win32":
        return "light"
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE_KEY) as key:
            apps_use_light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")  # DWORD：0 是深色
    except OSError:
        return "light"
    return "dark" if apps_use_light == 0 else "light"


class Widget:
    def __init__(self, root: tk.Tk, core, paths: ResolvedPaths,
                 on_screen: Optional[Callable[[int, int], bool]] = None,
                 system_theme: Callable[[], str] = windows_app_theme):
        """core 提供 poll、add、import_snapshot；paths 是啟動時解析的路徑，設定檔與納管目錄都取自它。
        system_theme 回傳系統目前的深淺色，主題選「跟隨系統」時每次渲染都問一次。"""
        self.root = root
        self._core = core
        self._paths = paths
        self._system_theme = system_theme
        self._position_file = paths.managed_dir / STATE_DIR / "window.json"
        self._board: Optional[Board] = None
        self._prefs: Optional[Preferences] = None  # 目前套用中的偏好；None 表示還沒套用過
        self._in_memory = {}  # 設定檔讀不懂時 GUI 的改動（欄位 → 值）：只在記憶體生效，修好設定檔後以設定檔為準
        self._unwritten = {}  # 設定檔讀得懂、但這次寫不進去（例如被防毒鎖住）的改動：每輪重試，寫進去為止
        self._position: Optional[Tuple[int, int]] = None
        self._after = None
        root.overrideredirect(True)
        root.configure(bg=TRANSPARENT_KEY)
        try:
            root.attributes("-transparentcolor", TRANSPARENT_KEY)
        except tk.TclError:
            pass  # 只有 Windows 支援透明色鍵；其他平台圓角外側會露出底色
        self.canvas = tk.Canvas(root, bg=TRANSPARENT_KEY, highlightthickness=0, borderwidth=0)
        self.canvas.pack()
        self.layout = LayoutA(self.canvas)
        self._build_menu()
        self._restore_position(on_screen or on_any_screen(root))
        root.bind("<ButtonPress-1>", self._press)
        root.bind("<B1-Motion>", self._drag)
        root.bind("<ButtonRelease-1>", lambda e: self._save_position())
        root.bind("<Button-3>", lambda e: self._menu.tk_popup(e.x_root, e.y_root))
        root.bind("<Double-Button-1>", self._double_click)
        self.refresh()

    def _build_menu(self):
        """選單不能變長：只放常切換的偏好。變數建一次，每輪只改值，不累積。"""
        self._menu = menu = tk.Menu(self.root, tearoff=0)
        self._topmost_var = tk.BooleanVar(self.root)
        self._mode_var = tk.StringVar(self.root)
        self._theme_var = tk.StringVar(self.root)
        self._opacity_var = tk.IntVar(self.root)
        menu.add_checkbutton(label="置頂", variable=self._topmost_var,
                             command=lambda: self.set_preference("alwaysOnTop", self._topmost_var.get()))
        modes = tk.Menu(menu, tearoff=0)
        for label, value in _MODES:
            modes.add_radiobutton(label=label, value=value, variable=self._mode_var,
                                  command=lambda: self.set_preference("mode", self._mode_var.get()))
        menu.add_cascade(label="模式", menu=modes)
        themes = tk.Menu(menu, tearoff=0)
        for label, value in _THEMES:
            themes.add_radiobutton(label=label, value=value, variable=self._theme_var,
                                   command=lambda: self.set_preference("theme", self._theme_var.get()))
        menu.add_cascade(label="主題", menu=themes)
        opacities = tk.Menu(menu, tearoff=0)
        for value in _OPACITIES:
            opacities.add_radiobutton(label=f"{value}%", value=value, variable=self._opacity_var,
                                      command=lambda: self.set_preference("opacity", self._opacity_var.get()))
        menu.add_cascade(label="透明度", menu=opacities)
        menu.add_separator()
        menu.add_command(label="納管目前登入的帳號…", command=self.add_current_account)
        menu.add_command(label="匯入憑證檔…", command=self.import_credential_file)
        menu.add_command(label="開啟納管目錄", command=self.open_managed_dir)
        menu.add_separator()
        menu.add_command(label="結束", command=self.close)

    def menu_labels(self):
        last = self._menu.index("end")
        return [self._menu.entrycget(i, "label") for i in range(last + 1) if self._menu.type(i) != "separator"]

    def menu_state(self) -> Preferences:
        return replace(self._prefs, always_on_top=self._topmost_var.get(), mode=self._mode_var.get(),
                       theme=self._theme_var.get(), opacity=self._opacity_var.get())

    def refresh(self):
        """poll 一次並渲染，再排下一輪；排程永遠只有一個。這一輪出錯也照樣排下一輪，視窗才不會就此凍結。"""
        if self._after is not None:
            self.root.after_cancel(self._after)
        try:
            # 先重試寫不進去的改動再 poll：這一輪讀到的設定檔就已經包含它們
            self._unwritten = {f: v for f, v in self._unwritten.items() if not self._write(f, v)}
            self._board = self._core.poll()
            if not self._board.settings_unreadable:
                self._in_memory.clear()
            pending = {**self._in_memory, **self._unwritten}
            self._apply(replace(self._board.preferences, **{_ATTRS[f]: v for f, v in pending.items()}))
        finally:
            self._after = self.root.after(POLL_MS, self.refresh)

    def set_preference(self, field: str, value):
        """GUI 改一項偏好：立即生效、不跳確認。設定檔讀不懂時不寫回，只在記憶體生效。"""
        self._unwritten.pop(field, None)
        self._in_memory.pop(field, None)
        try:
            if not write_preference(self._paths.settings_file, field, value):
                self._in_memory[field] = value
        except OSError:
            self._unwritten[field] = value
        self._apply(replace(self._prefs, **{_ATTRS[field]: value}))

    def _write(self, field: str, value) -> bool:
        """重試寫不進去的改動。設定檔這時讀不懂就轉成只在記憶體生效。"""
        try:
            if not write_preference(self._paths.settings_file, field, value):
                self._in_memory[field] = value
        except OSError:
            return False
        return True

    def toggle_mode(self):
        """精簡／展開互換並記住，以上一輪的看板立即重畫；不另外 poll，也不動排程。"""
        self.set_preference("mode", "compact" if self._prefs.mode == "expanded" else "expanded")

    def _apply(self, prefs: Preferences):
        previous, self._prefs = self._prefs, prefs
        if previous is None or prefs.always_on_top != previous.always_on_top:
            self.root.attributes("-topmost", prefs.always_on_top)
        if previous is None or prefs.opacity != previous.opacity:
            self.root.attributes("-alpha", prefs.opacity / 100)
        self._topmost_var.set(prefs.always_on_top)
        self._mode_var.set(prefs.mode)
        self._theme_var.set(prefs.theme)
        self._opacity_var.set(prefs.opacity)
        if self._board is not None:
            # 跟隨系統：每輪 poll 都會走到這裡，系統切換深淺色後下一輪就跟上
            theme = self._system_theme() if prefs.theme == "system" else prefs.theme
            self.layout.render(self._board, theme, prefs.mode == "expanded")

    def _double_click(self, event):
        # 摺疊區標題自己處理點擊：雙擊它等於開合兩次，不該同時切換模式
        if CLICKABLE_TAG in self.canvas.gettags("current"):
            return
        self.toggle_mode()

    def add_current_account(self):
        label = simpledialog.askstring(_TITLE, "帳號標籤（會顯示在畫面上，也是憑證快照的檔名）：", parent=self.root)
        if label is None:
            return
        try:
            result = self._core.add(label)
        except InvalidLabel:
            messagebox.showerror(_TITLE, INVALID_LABEL.format(label=label), parent=self.root)
            return
        except NoCredential:
            messagebox.showerror(_TITLE, NO_CREDENTIAL, parent=self.root)
            return
        warnings = [ADD_NOT_BOUND if w is AddWarning.NOT_BOUND else ADD_WARNINGS[w]
                    for w in sorted(result.warnings, key=lambda w: w.value)]
        self._report(f"已納管「{label}」", warnings)

    def import_credential_file(self):
        source = filedialog.askopenfilename(parent=self.root, title="匯入憑證檔",
                                            filetypes=(("JSON", "*.json"), ("所有檔案", "*.*")))
        if not source:
            return
        label = simpledialog.askstring(_TITLE, "帳號標籤（會顯示在畫面上，也是憑證快照的檔名）：",
                                       initialvalue=Path(source).stem, parent=self.root)
        if label is None:
            return
        # 標籤就是檔名，Windows 的檔名不分大小寫
        taken = {account_label(key).casefold() for key in self._board.managed_accounts} if self._board else set()
        if label.casefold() in taken and not messagebox.askyesno(
                _TITLE, f"已經有帳號標籤「{label}」，要用這個檔案取代它的憑證快照嗎？", parent=self.root):
            return
        try:
            result = self._core.import_snapshot(Path(source), label)
        except InvalidLabel:
            messagebox.showerror(_TITLE, INVALID_LABEL.format(label=label), parent=self.root)
            return
        except NoCredential:
            messagebox.showerror(_TITLE, NOT_A_CREDENTIAL_FILE, parent=self.root)
            return
        warnings = [IMPORT_NOT_BOUND if w is AddWarning.NOT_BOUND else ADD_WARNINGS[w]
                    for w in sorted(result.warnings, key=lambda w: w.value)]
        self._report(f"已匯入「{label}」", warnings)

    def _report(self, done: str, warnings):
        self.refresh()  # 新帳號立刻出現在看板上，不必等下一輪
        messagebox.showinfo(_TITLE, "\n\n".join([done, *warnings]), parent=self.root)

    def open_managed_dir(self):
        directory = self._paths.managed_dir
        if not directory.is_dir():
            messagebox.showinfo(_TITLE, f"納管目錄還不存在：{directory}\n納管第一個帳號時會建立。", parent=self.root)
            return
        if sys.platform == "win32":
            os.startfile(directory)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(directory)])

    def close(self):
        if self._after is not None:
            self.root.after_cancel(self._after)
            self._after = None
        self._save_position()
        self.layout.destroy()
        self.root.destroy()

    def _restore_position(self, on_screen: Callable[[int, int], bool]):
        try:
            saved = json.loads(self._position_file.read_text(encoding="utf-8"))
            x, y = saved["x"], saved["y"]
            valid = all(type(v) is int for v in (x, y))
        except (OSError, ValueError, TypeError, KeyError):
            valid = False
        position = (x, y) if valid and on_screen(x + _GRIP, y + _GRIP) else DEFAULT_POSITION
        self.root.geometry("+%d+%d" % position)
        self._position = position

    def _save_position(self):
        """位置變了才寫。工具狀態目錄由核心建立並收緊權限；還不存在（還沒 poll 成功過）就不記。"""
        self.root.update_idletasks()
        position = (self.root.winfo_x(), self.root.winfo_y())
        if position == self._position or not self._position_file.parent.is_dir():
            return
        try:
            atomic.write_atomic(self._position_file, json.dumps({"x": position[0], "y": position[1]}).encode("utf-8"),
                                before_replace=make_private)
        except OSError:
            return  # 下次移動或結束時再記
        self._position = position

    def _press(self, event):
        self._dx = event.x_root - self.root.winfo_x()
        self._dy = event.y_root - self.root.winfo_y()

    def _drag(self, event):
        self.root.geometry(f"+{event.x_root - self._dx}+{event.y_root - self._dy}")
