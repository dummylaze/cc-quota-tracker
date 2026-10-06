"""懸浮視窗：無邊框、以透明色鍵挖出圓角、拖動任何位置可移動、雙擊切換精簡／展開；每 5 秒 poll 一次交給版面渲染。
同一時間只建立目前選用的版面；換版面時舊版面的 item 整批銷毀、再建新的。
右鍵選單調整偏好與納管帳號。偏好每輪取自看板（核心依設定檔的修改時間重讀），GUI 的改動合併寫回設定檔；
主題選「跟隨系統」時每輪讀一次 Windows 的應用程式深淺色；語系同理，選「跟隨系統」時每輪問一次作業系統的介面語言；
切換語系只改既有選單項與版面 item 的文字，不重建選單、也不重建版面；
視窗位置存在納管目錄的工具狀態，不進設定檔。開機自動啟動的開關狀態每次開選單時問登錄，不存在設定檔也不另存一份。"""
import os
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Callable, Optional, Tuple, Union

from . import i18n
from .board import Board, Preferences, SwitchOutcome, SwitchResult, SwitchStep
from .canvas_text import stalled_banner
from .core import BindingsUnreadable, InvalidLabel, NoCredential
from .entry import CLICKABLE_TAG
from .error_log import ErrorLog
from .layout_a import LayoutA
from .layout_b import LayoutB
from .layout_c import LayoutC
from .managed_directory import ManagedDirectory
from .fmt import account_label, query_reason, restore_confirmation, switch_confirmation, switch_refusal, switch_step
from .i18n import text
from .render_text import add_warning
from .claude_provider import AUTO_QUERY_FIELD, PROVIDER
from .switch_overlay import SwitchOverlay
from .settings import PREFERENCE_FIELDS, ResolvedPaths, WriteResult, write_preference, write_provider_setting
from .tokens import TRANSPARENT_KEY

POLL_MS = 5000  # 固定值，不開放設定
QUERY_POLL_MS = 500  # 固定值：查詢進行中縮短間隔，查完的新讀數才不必再等一整輪（查詢最久 20 秒，這段期間最多多 poll 約 40 次）
SWITCH_CHECK_MS = 100  # 固定值：切換在背景執行，每隔這麼久看一次有沒有跑完
STALL_ROUNDS = 12  # 固定值：連續這麼多輪沒有完成（約 1 分鐘）才亮停止更新橫幅
DEFAULT_POSITION = (40, 40)  # 主螢幕上的位置：第一次啟動，或上次的位置已經不在任何螢幕內
_GRIP = 20  # 判斷位置在不在螢幕內時，看視窗左上角往內這麼多的那一點：要拖得到視窗才算在螢幕內
_TITLE = "cc-quota-tracker"
_ATTRS = {field: attr for field, (attr, _) in PREFERENCE_FIELDS.items()}
_LAYOUTS = {"cards": LayoutA, "table": LayoutB, "ring": LayoutC}
# 選項：(語系鍵, 值)；合法值與 settings.PREFERENCE_FIELDS 一致。語系鍵為 None 的選項在每個語系都用同一個名稱
_LAYOUT_NAMES = (("layout.cards", "cards"), ("layout.table", "table"), ("layout.ring", "ring"))
_MODES = (("mode.compact", "compact"), ("mode.expanded", "expanded"))
_THEMES = (("theme.system", "system"), ("theme.light", "light"), ("theme.dark", "dark"))
_LANGUAGES = (("language.system", "system"), (None, "zh-TW"), (None, "en"))
_LANGUAGE_NAMES = {"zh-TW": "正體中文", "en": "English"}  # 各語系用自己的名稱，選錯語系的人也找得到自己看得懂的那一項
_OPACITIES = PREFERENCE_FIELDS["opacity"][1]
_AUTO_QUERY_NOT_WRITTEN = {WriteResult.UNREADABLE: "dialog.auto_query_unreadable",
                           WriteResult.MALFORMED: "dialog.auto_query_malformed"}  # 開關沒寫進設定檔的原因 → 語系鍵
_PERSONALIZE_KEY =r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"  # 登錄機碼，在 HKEY_CURRENT_USER 底下


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
                 system_theme: Callable[[], str] = windows_app_theme, autostart=None,
                 system_language: Callable[[], Optional[str]] = i18n.system_tag,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        """core 提供 poll、add、import_snapshot；paths 是啟動時解析的路徑，設定檔與納管目錄都取自它。
        system_theme 回傳系統目前的深淺色，主題選「跟隨系統」時每次渲染都問一次。
        autostart 提供 is_enabled、enable、disable；None 表示這個平台沒有開機自動啟動，選單就不放這一項。
        system_language 回傳作業系統的語系標籤（例如 zh-TW），語系選「跟隨系統」時每次渲染都問一次。
        clock 回傳目前時間，停止更新橫幅以它算最後一次完成一輪是多久前。"""
        self.root = root
        self._core = core
        self._autostart = autostart
        self._paths = paths
        self._system_theme = system_theme
        self._system_language = system_language
        self._clock = clock
        self._missed = 0  # 連續沒有完成的輪數；到 STALL_ROUNDS 就亮停止更新橫幅
        self._done_at: Optional[datetime] = None  # 最後一次完成一輪的時間；None 表示啟動後從沒完成過
        self._lang = i18n.resolve("system", system_language())  # 目前套用中的語系；第一次套用偏好時會校正
        self._menu_labels = []  # (選單, 項目序號, 語系鍵)：換語系時逐項改字，選單本身不重建
        self._managed = ManagedDirectory(paths.managed_dir)
        self._error_log = ErrorLog(paths.settings_file.parent, clock)
        self._board: Optional[Board] = None
        self._prefs: Optional[Preferences] = None  # 目前套用中的偏好；None 表示還沒套用過
        self._in_memory = {}  # 設定檔讀不懂時 GUI 的改動（欄位 → 值）：只在記憶體生效，修好設定檔後以設定檔為準
        self._unwritten = {}  # 設定檔讀得懂、但這次寫不進去（例如被防毒鎖住）的改動：每輪重試，寫進去為止
        self._position: Optional[Tuple[int, int]] = None
        self._after = None
        self._switch_thread: Optional[threading.Thread] = None  # 背景執行中的切換；None 表示沒有在切換
        # 背景執行緒留下的結果（核心的結果值，或丟出的例外），主執行緒收走
        self._switch_outcome: Union[SwitchResult, Exception, None] = None
        self._switch_after = None
        self._switch_label: Optional[str] = None  # 切換的目標帳號標籤：圖層的寫入步驟要寫出來；None 表示在還原上一次切換
        self._switch_step: Optional[SwitchStep] = None  # 背景執行緒回報的最新步驟，主執行緒讀走；None 表示還沒回報
        self._shown_step: Optional[SwitchStep] = None  # 圖層目前畫出來的步驟，與上一行不同就重畫
        self._switch_rows = None  # 子選單目前列出的內容（語系，各列的標籤與可不可選，能不能還原）；沒變就不碰選單
        root.overrideredirect(True)
        root.configure(bg=TRANSPARENT_KEY)
        try:
            root.attributes("-transparentcolor", TRANSPARENT_KEY)
        except tk.TclError:
            pass  # 只有 Windows 支援透明色鍵；其他平台圓角外側會露出底色
        self.canvas = tk.Canvas(root, bg=TRANSPARENT_KEY, highlightthickness=0, borderwidth=0)
        self.canvas.pack()
        self.layout = None  # 目前選用的版面：第一次套用偏好時才建立
        self._overlay = SwitchOverlay(self.canvas)  # 切換中才有 item；字型跟著版面
        self._build_menu()
        self._restore_position(on_screen or on_any_screen(root))
        root.bind("<ButtonPress-1>", self._press)
        root.bind("<B1-Motion>", self._drag)
        root.bind("<ButtonRelease-1>", lambda e: self._save_position())
        root.bind("<Button-3>", self._popup_menu)
        root.bind("<Double-Button-1>", self._double_click)
        self.refresh()

    def _popup_menu(self, event):
        if not self.switching:  # 切換中右鍵打不開：避免切到一半又觸發另一個動作
            self._menu.tk_popup(event.x_root, event.y_root)

    def _add_entry(self, parent, kind, key, **options):
        """加一個選單項，並記下它的語系鍵：key 為 None 的項目在每個語系都用同一個名稱，由 label 直接給。"""
        label = options.pop("label", None) or text(self._lang, key)
        getattr(parent, f"add_{kind}")(label=label, **options)
        if key is not None:
            self._menu_labels.append((parent, parent.index("end"), key))

    def _add_choices(self, menu, key, choices, var, field):
        """一組單選：右鍵選單的一個子選單。"""
        submenu = tk.Menu(menu, tearoff=0)
        for choice_key, value in choices:
            self._add_entry(submenu, "radiobutton", choice_key, value=value, variable=var,
                            label=_LANGUAGE_NAMES.get(value) if choice_key is None else None,
                            command=lambda: self.set_preference(field, var.get()))
        self._add_entry(menu, "cascade", key, menu=submenu)

    def _build_menu(self):
        """選單不能變長：只放常切換的偏好。變數建一次，每輪只改值，不累積。"""
        self._menu = menu = tk.Menu(self.root, tearoff=0, postcommand=self.sync_autostart)
        self._layout_var = tk.StringVar(self.root)
        self._topmost_var = tk.BooleanVar(self.root)
        self._mode_var = tk.StringVar(self.root)
        self._language_var = tk.StringVar(self.root)
        self._theme_var = tk.StringVar(self.root)
        self._opacity_var = tk.IntVar(self.root)
        self._autostart_var = tk.BooleanVar(self.root)
        self._auto_query_var = tk.BooleanVar(self.root)
        self._add_choices(menu, "menu.layout", _LAYOUT_NAMES, self._layout_var, "layout")
        self._add_entry(menu, "checkbutton", "menu.topmost", variable=self._topmost_var,
                        command=lambda: self.set_preference("alwaysOnTop", self._topmost_var.get()))
        self._add_choices(menu, "menu.mode", _MODES, self._mode_var, "mode")
        self._add_choices(menu, "menu.language", _LANGUAGES, self._language_var, "language")
        self._add_choices(menu, "menu.theme", _THEMES, self._theme_var, "theme")
        opacities = tk.Menu(menu, tearoff=0)
        for value in _OPACITIES:
            opacities.add_radiobutton(label=f"{value}%", value=value, variable=self._opacity_var,
                                      command=lambda: self.set_preference("opacity", self._opacity_var.get()))
        self._add_entry(menu, "cascade", "menu.opacity", menu=opacities)
        if self._autostart is not None:
            self._add_entry(menu, "checkbutton", "menu.autostart", variable=self._autostart_var,
                            command=self._toggle_autostart)
        menu.add_separator()
        self._switch_menu = tk.Menu(menu, tearoff=0)
        self._add_entry(menu, "cascade", "menu.switch", menu=self._switch_menu)
        self._switch_index = menu.index("end")
        self._add_entry(menu, "command", "menu.query", command=self.query_usage)
        self._query_index = menu.index("end")
        self._add_entry(menu, "checkbutton", "menu.auto_query", variable=self._auto_query_var,
                        command=self._toggle_auto_query)
        self._add_entry(menu, "command", "menu.add", command=self.add_current_account)
        self._add_entry(menu, "command", "menu.import", command=self.import_credential_file)
        folders = tk.Menu(menu, tearoff=0)
        self._add_entry(folders, "command", "menu.open_managed_dir", command=self.open_managed_dir)
        self._add_entry(folders, "command", "menu.open_settings_dir", command=self.open_settings_dir)
        self._add_entry(menu, "cascade", "menu.open_folder", menu=folders)
        self._dismiss_index = menu.index("end") + 1  # 「不再提醒權限未收緊」只在告警亮著時插在這裡
        self._dismiss_shown = False
        menu.add_separator()
        self._add_entry(menu, "command", "menu.quit", command=self.close)

    def _relabel_menu(self):
        for menu, index, key in self._menu_labels:
            menu.entryconfigure(index, label=text(self._lang, key))

    def menu_labels(self):
        last = self._menu.index("end")
        return [self._menu.entrycget(i, "label") for i in range(last + 1) if self._menu.type(i) != "separator"]

    def menu_state(self) -> Preferences:
        return replace(self._prefs, layout=self._layout_var.get(), always_on_top=self._topmost_var.get(), mode=self._mode_var.get(),
                       language=self._language_var.get(), theme=self._theme_var.get(), opacity=self._opacity_var.get())

    def _sync_dismiss_menu(self):
        """看板帶「未收緊」時才多出「不再提醒權限未收緊」。插入、移除會讓後面項目的序號位移，換語系改字靠序號，
        所以一併調整。狀態沒變就不碰選單（理由同 _sync_query_menu）。"""
        lit = self._board is not None and self._board.permissions_untightened
        if lit == self._dismiss_shown:
            return
        self._dismiss_shown = lit
        menu, at = self._menu, self._dismiss_index
        if lit:
            self._menu_labels = [(m, i + 1 if m is menu and i >= at else i, k) for m, i, k in self._menu_labels]
            menu.insert_command(at, label=text(self._lang, "menu.dismiss_untightened"),
                                command=self.dismiss_untightened_warning)
            self._menu_labels.append((menu, at, "menu.dismiss_untightened"))
        else:
            menu.delete(at)
            self._menu_labels = [(m, i - 1 if m is menu and i > at else i, k) for m, i, k in self._menu_labels
                                 if not (m is menu and i == at)]

    def dismiss_untightened_warning(self):
        """右鍵選單的「不再提醒權限未收緊」：關掉看板的橫幅並立刻 poll 一次重畫；換納管目錄或權限恢復後會重新出現。"""
        if self.switching:  # 核心正被背景的切換使用；切換中右鍵打不開之後，這個守衛只剩保險
            return
        self._core.dismiss_untightened_warning()
        self.refresh()

    def _sync_query_menu(self):
        """選單的「查詢額度」隨看板的查詢狀態：進行中與冷卻中不可點，其餘任何時候都可用（不必落後）。
        「自動查詢額度」的勾選一律取自看板（設定檔目前的值），所以寫不進設定檔時會回到實際生效的那一邊。
        狀態沒變就不碰選單項：Windows 上改動彈出中的選單項會重建原生選單，展開中的子選單被收掉、整個選單跟著關閉，
        游標所在項目的反白也被清掉。游標停在這一項時 Tk 把它設成 active，那仍是可點，只比較可不可點。"""
        status = self._board.usage_query if self._board is not None else None
        busy = self.switching or status is not None and (status.in_progress or status.cooling_down)
        if (self._menu.entrycget(self._query_index, "state") == "disabled") != busy:
            self._menu.entryconfigure(self._query_index, state="disabled" if busy else "normal")
        self._auto_query_var.set(status is not None and status.auto_enabled)

    @property
    def switching(self) -> bool:
        return self._switch_thread is not None

    def _sync_switch_menu(self):
        """「切換帳號」子選單依看板：待命帳號依帳號鍵的順序以標籤列出，僅監看帳號反灰；沒有任何可選的帳號時多放一列
        反灰的說明。查詢進行中或正在切換時，整個子選單反灰（核心的切換不檢查進行中的查詢，同時會有兩個 claude 子行程）。
        最後一列固定是「還原上一次切換」，沒有可還原的切換前憑證、或它已過期（看板的 restorable）時反灰。
        內容與狀態都沒變就不碰選單（理由同 _sync_query_menu）。"""
        board = self._board
        standby = board.cards[1:] if board is not None else ()
        restorable = board is not None and board.restorable
        rows = (self._lang, tuple((account_label(c.account_key), c.switchable) for c in standby), restorable)
        if rows != self._switch_rows:
            self._switch_rows = rows
            menu = self._switch_menu
            menu.delete(0, "end")
            for label, switchable in rows[1]:
                menu.add_command(label=label, state="normal" if switchable else "disabled",
                                 command=lambda label=label: self.switch_to(label))
            if not any(switchable for _, switchable in rows[1]):
                menu.add_command(label=text(self._lang, "menu.switch_none"), state="disabled")
            menu.add_separator()
            menu.add_command(label=text(self._lang, "menu.restore"), state="normal" if restorable else "disabled",
                             command=self.restore_previous)
        busy = self.switching or board is not None and board.usage_query.in_progress
        if (self._menu.entrycget(self._switch_index, "state") == "disabled") != busy:
            self._menu.entryconfigure(self._switch_index, state="disabled" if busy else "normal")

    def switch_to(self, label: str):
        """子選單選了一個帳號：確認之後在背景切換，視窗的事件迴圈照常運作。切換進行中、或查詢進行中就什麼都不做
        （選單這時本來就不可點，這裡只擋過期看板的漏網之魚）。確認的內容取自最近一輪的看板。"""
        board = self._board
        if self.switching or board is None or board.usage_query.in_progress:
            return
        lang = self._lang
        if not messagebox.askyesno(text(lang, "dialog.switch_title"), switch_confirmation(board, label, lang),
                                   parent=self.root):
            return
        self._start_switch(label)

    def restore_previous(self):
        """子選單的「還原上一次切換」：跟一般切換一樣要確認、在背景執行、蓋上圖層。確認的內容取自最近一輪的看板
        （切換前憑證的到期時間）；能不能還原由核心重新判斷，被拒絕（看板過期等）會顯示原因。"""
        board = self._board
        if self.switching or board is None or board.usage_query.in_progress:
            return
        lang = self._lang
        if not messagebox.askyesno(text(lang, "dialog.switch_title"), restore_confirmation(board, lang),
                                   parent=self.root):
            return
        self._start_switch(None)

    def _start_switch(self, label: Optional[str]) -> bool:
        """確認之後開始背景的切換（label 是 None 就是還原上一次切換）。對話框開著時 Tk 照常跑排程：這段時間可能已有
        查詢（自動查詢）啟動，所以這裡再驗一次，已在切換或在查就什麼都不做、回傳 False。"""
        latest = self._board
        if self.switching or latest is None or latest.usage_query.in_progress:
            return False
        self._switch_outcome = None
        self._switch_label, self._switch_step = label, None
        self._switch_thread = threading.Thread(target=self._run_switch, args=(label,), daemon=True)
        self._switch_thread.start()
        self._sync_overlay()
        self._sync_switch_menu()
        self._sync_query_menu()
        self._switch_after = self.root.after(SWITCH_CHECK_MS, self._check_switch, label)
        return True

    def _run_switch(self, label: Optional[str]):
        """背景執行緒：不碰 Tk，結果與目前的步驟留給主執行緒收。核心不是執行緒安全的，切換期間 refresh 不 poll、
        query_usage 不啟動查詢；右鍵選單在切換中打不開，納管、匯入等入口的守衛只剩保險。"""
        try:
            self._switch_outcome = (self._core.switch(label, on_step=self._report_step) if label is not None
                                    else self._core.restore_previous(on_step=self._report_step))
        except Exception as e:  # 沒人看得到背景執行緒的例外：交給主執行緒告訴使用者
            self._switch_outcome = e

    def _report_step(self, step: SwitchStep):
        """背景執行緒回報進度。"""
        self._switch_step = step  # 單純指派：主執行緒每 SWITCH_CHECK_MS 看一次，不必加鎖

    def _theme(self, prefs: Preferences) -> str:
        """實際套用的深淺色：偏好選「跟隨系統」就問作業系統。"""
        return self._system_theme() if prefs.theme == "system" else prefs.theme  # 跟隨系統：每次渲染都問一次

    def _sync_overlay(self):
        """切換中蓋上圖層，結束就拿掉。展開模式在圖層上寫目前的步驟，精簡模式只有半透明的一層。
        圖層整批重建，所以一定在最上面；版面重畫（換模式、換語系）之後要再呼叫一次。"""
        if not self.switching:
            self._overlay.hide()
            return
        step = self._shown_step = self._switch_step
        expanded = self._prefs is not None and self._prefs.mode == "expanded"
        shown = switch_step(step, self._switch_label, self._lang) if expanded and step is not None else None
        self._overlay.show(self._theme(self._prefs or Preferences()), shown)

    def _check_switch(self, label: Optional[str]):
        assert self._switch_thread is not None
        if self._switch_thread.is_alive():
            if self._switch_step is not self._shown_step:
                self._sync_overlay()
            self._switch_after = self.root.after(SWITCH_CHECK_MS, self._check_switch, label)
            return
        outcome, self._switch_thread, self._switch_after = self._switch_outcome, None, None
        self._sync_overlay()  # 拿掉圖層：下面的 refresh 這一輪出錯也一樣
        self.refresh()  # 先重畫：成功時第一列換成新帳號、讀數更新就是回饋；之後才跳提示
        lang = self._lang
        if isinstance(outcome, Exception):
            message = text(lang, "dialog.switch_failed", error=outcome)
        elif outcome is None:
            return  # 沒有結果可報（背景執行緒不會不留結果就結束）
        elif outcome.outcome is SwitchOutcome.REFUSED:
            message = switch_refusal(outcome, label, lang)
        elif outcome.outcome is SwitchOutcome.WRITE_FAILED:
            message = text(lang, "switch.restore_write_failed" if label is None else "switch.write_failed", label=label)
        elif outcome.outcome is SwitchOutcome.VERIFY_FAILED:
            assert outcome.verify_failure is not None  # 驗證失敗一定帶查詢的失敗結果
            reason = query_reason(outcome.verify_failure, lang)
            if label is None:  # 還原自己驗證失敗：再問一次「要還原嗎」只會繞回剛離開的帳號，只說明
                message = text(lang, "switch.restore_verify_failed", reason=reason)
            else:
                message = text(lang, "dialog.verify_failed", label=label, reason=reason)
                if self._board is not None and self._board.restorable:  # 還原不了的話，問了也只會得到拒絕
                    self._offer_restore(message)
                    return
        else:
            return  # 成功不提示；舊帳號查詢失敗不提示
        messagebox.showerror(_TITLE, message, parent=self.root)

    def _offer_restore(self, message: str):
        """驗證失敗的提示：說明之後問要不要還原上一次切換。「是」就是在回答「要不要還原」，不再跳確認對話框。
        問的時候對話框是模態的、Tk 的排程照跑，人離開座位久了自動查詢可能已啟動：還原被守衛擋下時要說出來，
        不能讓按了「是」的人以為已經還原。"""
        lang = self._lang
        question = text(lang, "dialog.verify_failed_ask")
        if not messagebox.askyesno(text(lang, "dialog.switch_title"), f"{message}\n\n{question}", parent=self.root):
            return
        if not self._start_switch(None):
            messagebox.showerror(_TITLE, text(lang, "dialog.restore_busy"), parent=self.root)

    def _toggle_auto_query(self):
        """右鍵選單的「自動查詢額度」：寫回 providers.claude.autoUsageQuery 並立刻 poll，核心讀到新值，下一輪起生效。
        設定檔讀不懂、格式不對或寫不進去時不寫，跳對話框說明原因；勾選狀態由看板拉回實際生效的那一邊
        （不像偏好那樣暫存在記憶體重試：這個開關會花請求額度，以設定檔為準）。"""
        message = None
        try:
            result = write_provider_setting(self._paths.settings_file, PROVIDER, AUTO_QUERY_FIELD,
                                            self._auto_query_var.get())
            if result is not WriteResult.WRITTEN:
                message = text(self._lang, _AUTO_QUERY_NOT_WRITTEN[result])
        except OSError as e:
            message = text(self._lang, "dialog.auto_query_write_failed", error=e)
        if message is not None:
            messagebox.showerror(_TITLE, message, parent=self.root)
        self.refresh()

    def sync_autostart(self):
        """勾選狀態以登錄的實際值為準：每次開選單前對一次，使用者自己在別處刪掉啟動項時才不會不同步。"""
        if self._autostart is not None:
            self._autostart_var.set(self._autostart.is_enabled())

    def autostart_shown(self) -> bool:
        return self._autostart_var.get()

    def _toggle_autostart(self):
        try:
            (self._autostart.enable if self._autostart_var.get() else self._autostart.disable)()
        except OSError as e:
            messagebox.showerror(_TITLE, text(self._lang, "dialog.autostart_failed", error=e), parent=self.root)
        self.sync_autostart()  # 寫不進去時勾選不能停在使用者剛點的那一邊

    def refresh(self):
        """poll 一次並渲染，再排下一輪；排程永遠只有一個。這一輪出錯也照樣排下一輪，視窗才不會就此凍結。
        重試寫回設定檔、poll、渲染任一步丟出例外都算這一輪沒有完成：例外不往外丟（由 Tk 排程呼叫時，pythonw 下沒人看得到；
        由選單或按鈕直接呼叫時，會丟回它們的處理函式），畫面維持最後一次成功的看板，連續 STALL_ROUNDS 輪才亮停止更新橫幅；錯誤詳情寫進錯誤紀錄（error_log）。"""
        if self._after is not None:
            self.root.after_cancel(self._after)
        if self.switching:  # 背景的切換正在用核心：這一輪不 poll，畫面維持原樣，切換結束時會立刻重畫
            self._after = self.root.after(POLL_MS, self.refresh)
            return
        missed, self._missed = self._missed, 0  # 先當成會完成：完成的這一輪渲染時橫幅就已熄滅
        try:
            # 先重試寫不進去的改動再 poll：這一輪讀到的設定檔就已經包含它們
            self._unwritten = {f: v for f, v in self._unwritten.items() if not self._write(f, v)}
            self._board = self._core.poll()
            if not self._board.settings_unreadable:
                self._in_memory.clear()
            pending = {**self._in_memory, **self._unwritten}
            self._apply(replace(self._board.preferences, **{_ATTRS[f]: v for f, v in pending.items()}))
            self._done_at = self._clock()
            self._error_log.completed()
        except Exception as e:
            self._missed = missed + 1
            self._error_log.failed(e)
            if self._missed >= STALL_ROUNDS:
                try:
                    self._apply(self._prefs or Preferences())  # 從沒套用過偏好時用預設值，才有版面可以亮橫幅
                except Exception:
                    pass  # 渲染本身就是出錯的那一步：盡力而為，下一輪再試
        finally:
            querying = self._board is not None and self._board.usage_query.in_progress
            self._after = self.root.after(QUERY_POLL_MS if querying else POLL_MS, self.refresh)

    def query_usage(self):
        """卡片上的「更新」與右鍵選單的「查詢額度」：請核心開始查詢，立刻 poll 一次讓畫面顯示進行中。
        進行中或冷卻中核心會拒絕，這時什麼都不做（入口與選單項這時本來就不可點，這裡只擋過期看板的漏網之魚）。"""
        if not self.switching and self._core.start_query():  # 切換進行中核心已被背景執行緒佔用
            self.refresh()

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
        # 跟隨系統：每輪 poll 都會走到這裡，系統換介面語言後下一輪就跟上
        lang = i18n.resolve(prefs.language, self._system_language())
        if lang != self._lang:
            self._lang = lang
            self._relabel_menu()
        self._sync_query_menu()
        self._sync_switch_menu()
        self._sync_dismiss_menu()
        self._layout_var.set(prefs.layout)
        self._topmost_var.set(prefs.always_on_top)
        self._mode_var.set(prefs.mode)
        self._language_var.set(prefs.language)
        self._theme_var.set(prefs.theme)
        self._opacity_var.set(prefs.opacity)
        new_layout = self.layout is None or prefs.layout != previous.layout
        if new_layout:
            if self.layout is not None:
                self.layout.destroy()
            make = _LAYOUTS[prefs.layout]
            self.layout = make(self.canvas, on_query=self.query_usage)
        if new_layout or prefs.font != previous.font:
            self.layout.set_font(prefs.font)  # 字型存不存在只有畫面層知道；找不到時版面自己在橫幅提示
            self._overlay.set_font(prefs.font)
        stalled = self._missed >= STALL_ROUNDS
        if self._board is not None or stalled:
            # 跟隨系統：每輪 poll 都會走到這裡，系統切換深淺色後下一輪就跟上
            theme = self._theme(prefs)
            now = self._clock()
            board = self._board or Board(cards=(), as_of=now)  # 從沒完成過一輪：沒有看板，只畫橫幅
            self.layout.render(board, theme, prefs.mode == "expanded", self._lang,
                               stalled_banner(self._lang, self._done_at, now) if stalled else None)
        self._sync_overlay()  # 版面剛重畫過：圖層要重蓋，才在新 item 上面、也跟上模式與語系的改變

    def _double_click(self, event):
        # 摺疊區標題自己處理點擊：雙擊它等於開合兩次，不該同時切換模式
        if CLICKABLE_TAG in self.canvas.gettags("current"):
            return
        self.toggle_mode()

    def add_current_account(self):
        if self.switching:
            return
        lang = self._lang
        label = simpledialog.askstring(_TITLE, text(lang, "dialog.label_prompt"), parent=self.root)
        if label is None:
            return
        try:
            result = self._core.add(label)
        except InvalidLabel:
            messagebox.showerror(_TITLE, text(lang, "error.invalid_label", label=label), parent=self.root)
            return
        except NoCredential:
            messagebox.showerror(_TITLE, text(lang, "error.no_credential"), parent=self.root)
            return
        except BindingsUnreadable as e:
            messagebox.showerror(_TITLE, text(lang, "error.bindings_unreadable", path=e.path), parent=self.root)
            return
        warnings = [add_warning(lang, w, "menu") for w in sorted(result.warnings, key=lambda w: w.value)]
        self._report(text(lang, "account.added", label=label), warnings)

    def import_credential_file(self):
        if self.switching:
            return
        lang = self._lang
        source = filedialog.askopenfilename(parent=self.root, title=text(lang, "dialog.import_title"),
                                            filetypes=(("JSON", "*.json"), (text(lang, "dialog.all_files"), "*.*")))
        if not source:
            return
        label = simpledialog.askstring(_TITLE, text(lang, "dialog.label_prompt"),
                                       initialvalue=Path(source).stem, parent=self.root)
        if label is None:
            return
        # 標籤就是檔名，Windows 的檔名不分大小寫
        taken = {account_label(key).casefold() for key in self._board.watched_accounts} if self._board else set()
        if label.casefold() in taken and not messagebox.askyesno(
                _TITLE, text(lang, "dialog.confirm_replace", label=label), parent=self.root):
            return
        try:
            result = self._core.import_snapshot(Path(source), label)
        except InvalidLabel:
            messagebox.showerror(_TITLE, text(lang, "error.invalid_label", label=label), parent=self.root)
            return
        except NoCredential:
            messagebox.showerror(_TITLE, text(lang, "error.not_a_credential_file"), parent=self.root)
            return
        except BindingsUnreadable as e:
            messagebox.showerror(_TITLE, text(lang, "error.bindings_unreadable", path=e.path), parent=self.root)
            return
        warnings = [add_warning(lang, w, "import") for w in sorted(result.warnings, key=lambda w: w.value)]
        self._report(text(lang, "account.imported", label=label), warnings)

    def _report(self, done: str, warnings):
        self.refresh()  # 新帳號立刻出現在看板上，不必等下一輪
        messagebox.showinfo(_TITLE, "\n\n".join([done, *warnings]), parent=self.root)

    def open_managed_dir(self):
        self._open_dir(self._paths.managed_dir, "dialog.managed_dir_missing")

    def open_settings_dir(self):
        self._open_dir(self._paths.settings_file.parent, "dialog.settings_dir_missing")

    def _open_dir(self, directory: Path, missing_key: str):
        if not directory.is_dir():
            messagebox.showinfo(_TITLE, text(self._lang, missing_key, directory=directory), parent=self.root)
            return
        if sys.platform == "win32":
            os.startfile(directory)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(directory)])

    def close(self):
        if self._after is not None:
            self.root.after_cancel(self._after)
            self._after = None
        if self._switch_after is not None:
            self.root.after_cancel(self._switch_after)
            self._switch_after = None
        self._save_position()
        self._overlay.destroy()
        if self.layout is not None:
            self.layout.destroy()
        self.root.destroy()

    def _restore_position(self, on_screen: Callable[[int, int], bool]):
        saved = self._managed.read_window_position()  # 讀不到或讀不懂都回到預設位置
        position = saved if saved and on_screen(saved[0] + _GRIP, saved[1] + _GRIP) else DEFAULT_POSITION
        self.root.geometry("+%d+%d" % position)
        self._position = position

    def _save_position(self):
        """位置變了才寫。這次沒記住（還沒 poll 成功過、寫不成）就不更新，下次移動或結束時再記。"""
        self.root.update_idletasks()
        position = (self.root.winfo_x(), self.root.winfo_y())
        if position != self._position and self._managed.write_window_position(*position):
            self._position = position

    def _press(self, event):
        self._dx = event.x_root - self.root.winfo_x()
        self._dy = event.y_root - self.root.winfo_y()

    def _drag(self, event):
        self.root.geometry(f"+{event.x_root - self._dx}+{event.y_root - self._dy}")
