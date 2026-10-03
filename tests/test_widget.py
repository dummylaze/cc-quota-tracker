"""視窗骨架：每輪 poll 一次交給版面渲染，after() 不重複註冊；偏好來自看板，GUI 的改動合併寫回設定檔；視窗位置存在工具狀態。"""
import json
import shutil
import tkinter as tk
import tkinter.font as tkfont
import unittest
from unittest import mock

from cc_quota_tracker.board import Preferences
from cc_quota_tracker.tokens import THEMES
from cc_quota_tracker.widget import DEFAULT_POSITION, Widget
from tests.fakehome import HomeTestCase
from tests.test_layout_a import BOARDS, visible_texts


class CountingCore:
    """真的核心，另外數 poll 的次數。"""

    def __init__(self, core):
        self.core, self.polls = core, 0

    def poll(self):
        self.polls += 1
        return self.core.poll()

    def __getattr__(self, name):
        return getattr(self.core, name)


class FakeAutostart:
    """登錄的替身：狀態只存在這裡；fail 設成例外就讓寫入失敗。"""

    def __init__(self):
        self.enabled, self.fail = False, None

    def is_enabled(self):
        return self.enabled

    def enable(self):
        if self.fail:
            raise self.fail
        self.enabled = True

    def disable(self):
        if self.fail:
            raise self.fail
        self.enabled = False


class WidgetTestCase(HomeTestCase):
    def setUp(self):
        super().setUp()
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # 沒有顯示環境
            self.skipTest(f"Tk 無法啟動：{e}")
        self.root.withdraw()
        self.addCleanup(self.destroy_root)
        self.on_screen = lambda x, y: True
        self.system_theme = "light"
        self.system_language = "zh-TW"
        self.open_widget()

    def open_widget(self):
        self.counting = CountingCore(self.core)
        self.autostart = FakeAutostart()
        self.widget = Widget(self.root, self.counting, self.paths, on_screen=lambda x, y: self.on_screen(x, y),
                             system_theme=lambda: self.system_theme, autostart=self.autostart,
                             system_language=lambda: self.system_language, clock=self.clock)

    def destroy_root(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass  # 已被 close() 銷毀

    def pending_after(self):
        return self.root.tk.splitlist(self.root.tk.call("after", "info"))

    def settings(self):
        return json.loads(self.settings_file().read_text(encoding="utf-8"))


class LifecycleTest(WidgetTestCase):
    def test_polls_once_on_start(self):
        self.assertEqual(self.counting.polls, 1)
        self.assertEqual(len(self.pending_after()), 1)

    def test_refresh_keeps_a_single_pending_after_and_no_new_tcl_variables(self):
        self.widget.refresh()
        items, variables = len(self.widget.canvas.find_all()), len(self.root.tk.call("info", "globals"))
        for _ in range(10):
            self.widget.refresh()
        self.assertEqual(self.counting.polls, 12)
        self.assertEqual(len(self.pending_after()), 1)
        self.assertEqual(len(self.widget.canvas.find_all()), items)
        self.assertEqual(len(self.root.tk.call("info", "globals")), variables)

    def test_boards_that_change_every_round_keep_a_single_pending_after(self):
        boards = iter(BOARDS * 3)
        self.counting.poll = lambda: next(boards)
        for _ in range(len(BOARDS) * 3 - 1):
            self.widget.refresh()
        self.assertEqual(len(self.pending_after()), 1)

    def test_close_cancels_the_pending_after(self):
        self.widget.close()
        self.assertEqual(self.pending_after(), ())

    def test_window_is_borderless_and_topmost_by_default(self):
        self.assertTrue(self.root.overrideredirect())
        self.assertTrue(self.root.attributes("-topmost"))


class PreferenceTest(WidgetTestCase):
    def test_gui_change_applies_at_once_and_is_written_to_the_settings_file(self):
        self.widget.set_preference("alwaysOnTop", False)
        self.widget.set_preference("opacity", 70)
        self.assertFalse(self.root.attributes("-topmost"))
        self.assertAlmostEqual(float(self.root.attributes("-alpha")), 0.7, places=2)
        self.assertEqual((self.settings()["alwaysOnTop"], self.settings()["opacity"]), (False, 70))
        self.widget.refresh()  # 下一輪從設定檔讀回同樣的值
        self.assertFalse(self.root.attributes("-topmost"))

    def test_hand_edit_applies_on_next_round(self):
        self.write_settings(alwaysOnTop=False, opacity=85)
        self.widget.refresh()
        self.assertFalse(self.root.attributes("-topmost"))
        self.assertAlmostEqual(float(self.root.attributes("-alpha")), 0.85, places=2)

    def test_toggle_mode_redraws_without_polling_and_remembers_the_mode(self):
        compact = len(self.widget.canvas.find_all())
        self.widget.toggle_mode()
        self.assertEqual(self.settings()["mode"], "expanded")
        for _ in range(9):
            self.widget.toggle_mode()
        self.assertEqual(self.counting.polls, 1)
        self.assertEqual(len(self.pending_after()), 1)
        self.assertEqual(self.settings()["mode"], "compact")
        self.assertEqual(len(self.widget.canvas.find_all()), compact)

    def test_unreadable_settings_file_keeps_gui_changes_in_memory_only(self):
        self.write_settings_text("{broken")
        self.widget.refresh()
        self.widget.set_preference("opacity", 70)
        self.widget.refresh()
        self.assertAlmostEqual(float(self.root.attributes("-alpha")), 0.7, places=2)
        self.assertEqual(self.settings_file().read_text(encoding="utf-8"), "{broken")
        self.write_settings(opacity=85)  # 使用者修好了：以設定檔為準
        self.widget.refresh()
        self.assertAlmostEqual(float(self.root.attributes("-alpha")), 0.85, places=2)

    def test_change_that_could_not_be_written_is_retried_instead_of_lost(self):
        # 防毒短暫鎖住設定檔：這次寫不進去，下一輪不能因為設定檔讀得懂就把改動丟掉
        with mock.patch("cc_quota_tracker.widget.write_preference", side_effect=PermissionError):
            self.widget.set_preference("opacity", 70)
            self.widget.refresh()
            self.assertAlmostEqual(float(self.root.attributes("-alpha")), 0.7, places=2)
        self.widget.refresh()
        self.assertEqual(self.settings()["opacity"], 70)
        self.assertAlmostEqual(float(self.root.attributes("-alpha")), 0.7, places=2)

    def test_menu_shows_the_current_preferences(self):
        self.write_settings(alwaysOnTop=False, mode="expanded", theme="dark", opacity=70)
        self.widget.refresh()
        self.assertEqual(self.widget.menu_state(),
                         Preferences(always_on_top=False, mode="expanded", theme="dark", opacity=70))
        self.write_settings(layout="table")
        self.widget.refresh()
        self.assertEqual(self.widget.menu_state().layout, "table")

    def test_menu_offers_settings_and_actions(self):
        self.assertEqual(self.widget.menu_labels(),
                         ["版面", "置頂", "模式", "語系", "主題", "透明度", "開機自動啟動", "查詢額度", "自動查詢額度", "納管目前登入的帳號…", "匯入憑證檔…", "開啟資料夾", "結束"])


class AutostartTest(WidgetTestCase):
    def click_autostart(self):
        self.widget.sync_autostart()  # 使用者按右鍵時選單會先對一次登錄
        menu = self.widget._menu
        labels = [menu.entrycget(i, "label") if menu.type(i) != "separator" else None for i in range(menu.index("end") + 1)]
        menu.invoke(labels.index("開機自動啟動"))

    def test_off_by_default_and_toggling_writes_the_registry(self):
        self.assertFalse(self.widget.autostart_shown())
        self.click_autostart()
        self.assertTrue(self.autostart.enabled)
        self.assertTrue(self.widget.autostart_shown())
        self.click_autostart()
        self.assertFalse(self.autostart.enabled)
        self.assertFalse(self.widget.autostart_shown())

    def test_shown_state_follows_the_registry_not_a_stored_copy(self):
        self.autostart.enabled = True  # 上一次執行時開的，或別的工具寫的
        self.widget.sync_autostart()
        self.assertTrue(self.widget.autostart_shown())
        self.autostart.enabled = False  # 使用者在登錄編輯器裡自己刪掉
        self.widget.sync_autostart()
        self.assertFalse(self.widget.autostart_shown())

    def test_is_not_stored_in_the_settings_file(self):
        self.click_autostart()
        self.assertNotIn("autostart", json.dumps(self.settings()).lower())

    def test_failed_write_tells_the_user_and_shows_the_real_state(self):
        self.autostart.fail = PermissionError("登錄被鎖住")
        with mock.patch("cc_quota_tracker.widget.messagebox.showerror") as showerror:
            self.click_autostart()
        showerror.assert_called_once()
        self.assertIn("登錄被鎖住", showerror.call_args.args[1])
        self.assertFalse(self.widget.autostart_shown())  # 沒寫成功，勾選不能停在「開」

    def test_no_menu_entry_when_the_platform_has_no_autostart(self):
        window = tk.Toplevel(self.root)  # 不另開一個 Tk：多個 Tk 直譯器同時銷毀時 ttk 會吐一堆錯誤訊息
        window.withdraw()
        widget = Widget(window, self.core, self.paths, on_screen=lambda x, y: True, autostart=None,
                        system_language=lambda: "zh-TW")
        self.assertNotIn("開機自動啟動", widget.menu_labels())
        widget.close()


class LayoutSwitchTest(WidgetTestCase):
    def layout_items(self, tag):
        return self.widget.canvas.find_withtag(tag)

    def test_cards_by_default_and_switching_to_table_is_remembered(self):
        self.assertTrue(self.layout_items("layout-a"))
        self.widget.set_preference("layout", "table")
        self.assertEqual(self.settings()["layout"], "table")
        self.assertEqual(self.widget.menu_state().layout, "table")
        self.assertEqual(self.layout_items("layout-a"), ())  # 舊版面整批銷毀
        self.assertTrue(self.layout_items("layout-b"))
        self.widget.refresh()  # 下一輪從設定檔讀回同樣的版面
        self.assertTrue(self.layout_items("layout-b"))

    def test_hand_edited_layout_applies_on_next_round(self):
        self.write_settings(layout="table")
        self.widget.refresh()
        self.assertEqual(self.layout_items("layout-a"), ())
        self.assertTrue(self.layout_items("layout-b"))

    def test_switching_to_ring_is_remembered(self):
        self.widget.set_preference("layout", "ring")
        self.assertEqual(self.settings()["layout"], "ring")
        self.assertEqual(self.widget.menu_state().layout, "ring")
        self.assertEqual(self.layout_items("layout-a"), ())
        self.assertTrue(self.layout_items("layout-c"))
        self.widget.set_preference("layout", "table")
        self.assertEqual(self.layout_items("layout-c"), ())  # 舊版面整批銷毀

    def test_switching_layouts_back_and_forth_returns_to_the_same_item_count(self):
        layouts = ("cards", "table", "ring")
        counts = {}
        for i in range(36):
            layout, mode = layouts[i % 3], ("compact", "expanded")[i // 3 % 2]
            theme = ("light", "dark")[i // 6 % 2]
            self.widget.set_preference("theme", theme)
            self.widget.set_preference("mode", mode)
            self.widget.set_preference("layout", layout)
            counts.setdefault((layout, mode, theme), set()).add(len(self.widget.canvas.find_all()))
        for key, seen in counts.items():
            self.assertEqual(len(seen), 1, key)
        self.assertEqual(len(self.pending_after()), 1)

    def test_menu_offers_the_three_layouts(self):
        layouts = self.widget._menu.nametowidget(self.widget._menu.entrycget(0, "menu"))
        self.assertEqual([layouts.entrycget(i, "label") for i in range(3)], ["卡片列表", "密集表格／單行條", "環形儀表"])

    def test_close_destroys_the_current_layout(self):
        self.widget.set_preference("layout", "table")
        with mock.patch.object(self.widget.layout, "destroy", wraps=self.widget.layout.destroy) as destroy:
            self.widget.close()
        destroy.assert_called_once_with()


class FontTest(WidgetTestCase):
    MISSING = "NoSuchFontFamilyXYZ"

    def system_family(self):
        return tkfont.Font(self.root, name="TkDefaultFont", exists=True).actual("family").casefold()

    def families_in_use(self):
        canvas = self.widget.canvas
        return {tkfont.Font(self.root, font=canvas.itemcget(i, "font")).actual("family").casefold()
                for i in canvas.find_all() if canvas.type(i) == "text" and canvas.itemcget(i, "state") != "hidden"}

    def other_installed_family(self):
        others = [f for f in sorted(tkfont.families(self.root))
                  if f.casefold() != self.system_family() and not f.startswith("@")]
        if not others:
            self.skipTest("沒有第二個字型可換")
        return others[0]

    def shown(self):
        return "\n".join(visible_texts(self.widget.canvas))

    def test_hand_edited_font_applies_on_next_round_and_null_goes_back(self):
        family = self.other_installed_family()
        self.write_settings(font=family)
        self.widget.refresh()
        self.assertEqual(self.families_in_use(), {family.casefold()})
        self.write_settings(font=None)
        self.widget.refresh()
        self.assertNotIn(family.casefold(), self.families_in_use())

    def test_font_survives_a_layout_switch(self):
        family = self.other_installed_family()
        self.write_settings(font=family)
        self.widget.refresh()
        for layout in ("table", "ring", "cards"):
            self.widget.set_preference("layout", layout)
            self.assertEqual(self.families_in_use(), {family.casefold()}, layout)

    def test_font_is_read_from_the_settings_file_at_startup(self):
        family = self.other_installed_family()
        self.write_settings(font=family)
        self.root.update()
        self.widget.close()
        self.root = tk.Tk()
        self.root.withdraw()
        self.open_widget()
        self.assertEqual(self.families_in_use(), {family.casefold()})

    def test_a_missing_font_is_hinted_on_the_board_and_the_hint_goes_away_with_it(self):
        self.write_settings(font=self.MISSING)
        self.widget.refresh()
        self.assertIn(self.MISSING, self.shown())
        self.assertEqual(self.families_in_use(), {self.system_family()})
        self.write_settings(font=None)
        self.widget.refresh()
        self.assertNotIn(self.MISSING, self.shown())

    def test_a_font_that_is_not_a_string_is_named_as_an_invalid_setting(self):
        self.write_settings(font=12)
        self.widget.refresh()
        self.assertIn("font", self.shown())

    def test_font_is_not_in_the_context_menu_and_gui_changes_keep_it(self):
        self.assertFalse([label for label in self.widget.menu_labels() if "字型" in label])
        family = self.other_installed_family()
        self.write_settings(font=family)
        self.widget.refresh()
        self.widget.set_preference("opacity", 70)
        self.assertEqual(self.settings()["font"], family)


class LanguageTest(WidgetTestCase):
    def submenu(self, index):
        menu = self.widget._menu
        return menu.nametowidget(menu.entrycget(index, "menu"))

    def folders_menu(self, label):
        return self.submenu(self.widget._menu.index(label))

    def submenu_labels(self, index):
        menu = self.submenu(index)
        return [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]

    def texts(self):
        return visible_texts(self.widget.canvas)

    def test_follows_the_system_by_default_and_rechecks_every_round(self):
        self.assertEqual(self.widget.menu_state().language, "system")
        self.assertIn("未納管帳號", self.texts())
        self.assertEqual(self.widget.menu_labels()[0], "版面")
        self.system_language = "en-US"  # 使用者換了作業系統的介面語言
        self.widget.refresh()
        self.assertIn("Unmanaged account", self.texts())
        self.assertEqual(self.widget.menu_labels()[0], "Layout")
        self.system_language = "zh-TW"
        self.widget.refresh()
        self.assertIn("未納管帳號", self.texts())

    def test_an_unsupported_system_language_falls_back_to_english(self):
        for tag in ("ja-JP", "zh-CN", "fr-FR", None):
            self.system_language = tag
            self.widget.refresh()
            self.assertIn("Unmanaged account", self.texts(), tag)
            self.assertEqual(self.widget.menu_labels()[0], "Layout", tag)

    def test_a_chosen_language_ignores_the_system(self):
        self.system_language = "ja-JP"
        self.widget.set_preference("language", "zh-TW")
        self.widget.refresh()
        self.assertIn("未納管帳號", self.texts())
        self.system_language = "zh-TW"
        self.widget.set_preference("language", "en")
        self.widget.refresh()
        self.assertIn("Unmanaged account", self.texts())
        self.assertEqual(self.settings()["language"], "en")

    def test_gui_change_applies_at_once_and_is_remembered(self):
        self.widget.set_preference("language", "en")
        self.assertIn("Unmanaged account", self.texts())  # 不必等下一輪
        self.assertEqual(self.counting.polls, 1)
        self.assertEqual(self.settings()["language"], "en")
        self.assertEqual(self.widget.menu_state().language, "en")

    def test_hand_edit_applies_on_next_round(self):
        self.write_settings(language="en")
        self.widget.refresh()
        self.assertIn("Unmanaged account", self.texts())
        self.assertEqual(self.widget.menu_labels()[0], "Layout")

    def test_menu_offers_follow_system_and_the_two_languages_each_in_its_own_name(self):
        index = self.widget.menu_labels().index("語系")
        self.assertEqual(self.submenu_labels(index), ["跟隨系統", "正體中文", "English"])
        self.widget.set_preference("language", "en")
        index = self.widget.menu_labels().index("Language")
        self.assertEqual(self.submenu_labels(index), ["Follow system", "正體中文", "English"])

    def test_every_menu_entry_and_submenu_follows_the_language(self):
        self.widget.set_preference("language", "en")
        self.assertEqual(self.widget.menu_labels(),
                         ["Layout", "Always on top", "Mode", "Language", "Theme", "Opacity", "Start at login",
                          "Query usage", "Auto-query usage", "Manage the signed-in account…", "Import credential file…", "Open folder", "Quit"])
        self.assertEqual(self.submenu_labels(0), ["Card list", "Dense table / one-line strip", "Ring gauge"])
        self.assertEqual(self.submenu_labels(2), ["Compact", "Expanded"])
        self.assertEqual(self.submenu_labels(4), ["Follow system", "Light", "Dark"])

    def test_switching_language_updates_the_existing_widgets_instead_of_rebuilding(self):
        menu, submenu = self.widget._menu, self.submenu(0)
        entries = menu.index("end")
        variables = len(self.root.tk.call("info", "globals"))
        items = tuple(i for i in self.widget.canvas.find_all() if "wrapped-line" not in self.widget.canvas.gettags(i))
        for language in ("en", "zh-TW", "system") * 4:
            self.widget.set_preference("language", language)
        self.widget.set_preference("language", "en")
        self.assertIs(self.widget._menu, menu)
        self.assertIs(self.submenu(0), submenu)
        self.assertEqual(menu.index("end"), entries)
        self.assertEqual(len(self.root.tk.call("info", "globals")), variables)
        self.assertEqual(tuple(i for i in self.widget.canvas.find_all()
                               if "wrapped-line" not in self.widget.canvas.gettags(i)), items)
        self.assertEqual(len(self.pending_after()), 1)

    def test_language_survives_layout_and_mode_switches(self):
        self.widget.set_preference("language", "en")
        for layout in ("table", "ring", "cards"):
            for mode in ("expanded", "compact"):
                self.widget.set_preference("layout", layout)
                self.widget.set_preference("mode", mode)
                self.assertIn("Unmanaged account", self.texts(), (layout, mode))

    def test_invalid_language_in_the_settings_file_is_named_and_the_system_language_is_used(self):
        self.write_settings(language="klingon")
        self.widget.refresh()
        self.assertEqual(self.widget.menu_state().language, "system")
        self.assertIn("language", "".join(self.texts()))
        self.assertIn("未納管帳號", self.texts())

    def test_dialogs_speak_the_chosen_language(self):
        self.widget.set_preference("language", "en")
        with mock.patch("cc_quota_tracker.widget.messagebox") as box, \
                mock.patch("cc_quota_tracker.widget.simpledialog") as ask:
            ask.askstring.return_value = "work"
            self.widget.add_current_account()  # 沒有登入：讀不到憑證
        self.assertIn("Account label", ask.askstring.call_args.args[1])
        self.assertIn("Couldn't read the current sign-in credential", box.showerror.call_args.args[1])
        shutil.rmtree(self.paths.managed_dir, ignore_errors=True)  # 目錄不存在才會跳訊息，而不是真的開啟檔案總管
        with mock.patch("cc_quota_tracker.widget.messagebox") as box:
            self.widget.open_managed_dir()
        self.assertIn("doesn't exist yet", box.showinfo.call_args.args[1])
        self.widget.set_preference("language", "zh-TW")
        with mock.patch("cc_quota_tracker.widget.messagebox") as box:
            self.widget.open_managed_dir()
        self.assertIn("納管目錄還不存在", box.showinfo.call_args.args[1])

    def test_open_folder_submenu_offers_both_directories_in_both_languages(self):
        folders = self.folders_menu("開啟資料夾")
        self.assertEqual([folders.entrycget(i, "label") for i in (0, 1)], ["納管目錄", "設定目錄"])
        self.widget.set_preference("language", "en")
        folders = self.folders_menu("Open folder")
        self.assertEqual([folders.entrycget(i, "label") for i in (0, 1)], ["Managed directory", "Settings directory"])

    def test_each_folder_entry_opens_its_own_directory(self):
        folders = self.folders_menu("開啟資料夾")
        self.paths.settings_file.parent.mkdir(parents=True, exist_ok=True)
        self.paths.managed_dir.mkdir(parents=True, exist_ok=True)
        with mock.patch("cc_quota_tracker.widget.os.startfile", create=True) as start, \
                mock.patch("cc_quota_tracker.widget.sys.platform", "win32"):
            folders.invoke(0)
            folders.invoke(1)
        self.assertEqual([c.args[0] for c in start.call_args_list],
                         [self.paths.managed_dir, self.paths.settings_file.parent])

    def test_a_missing_settings_directory_says_so_instead_of_opening(self):
        shutil.rmtree(self.paths.settings_file.parent, ignore_errors=True)
        with mock.patch("cc_quota_tracker.widget.messagebox") as box:
            self.widget.open_settings_dir()
        self.assertIn("設定目錄還不存在", box.showinfo.call_args.args[1])
        self.widget.set_preference("language", "en")
        shutil.rmtree(self.paths.settings_file.parent, ignore_errors=True)  # 改偏好會把設定檔寫回來
        with mock.patch("cc_quota_tracker.widget.messagebox") as box:
            self.widget.open_settings_dir()
        self.assertIn("settings directory doesn't exist yet", box.showinfo.call_args.args[1])

    def test_managing_an_account_reports_in_the_chosen_language(self):
        self.log_in()
        self.widget.set_preference("language", "en")
        with mock.patch("cc_quota_tracker.widget.messagebox") as box, \
                mock.patch("cc_quota_tracker.widget.simpledialog") as ask:
            ask.askstring.return_value = "someone@example.com"
            self.widget.add_current_account()
        message = box.showinfo.call_args.args[1]
        self.assertIn("Managed \"someone@example.com\"", message)
        self.assertIn("looks like an email address", message)


    def test_managing_an_account_where_permissions_cannot_be_tightened_lists_the_warning_in_the_same_box(self):
        self.log_in()
        with mock.patch("cc_quota_tracker.widget.messagebox") as box, \
                mock.patch("cc_quota_tracker.widget.simpledialog") as ask, \
                mock.patch("cc_quota_tracker.managed_directory.make_private"), \
                mock.patch("cc_quota_tracker.managed_directory.is_private", return_value=False):
            ask.askstring.return_value = "work"
            self.widget.add_current_account()
        box.showerror.assert_not_called()
        self.assertIn("納管目錄的權限無法收緊", box.showinfo.call_args.args[1])


class ManageAccountsTest(WidgetTestCase):
    def setUp(self):
        super().setUp()
        self.log_in()
        self.core.add("work")

    def assertLockedBindingsError(self, box):
        message = box.showerror.call_args.args[1]
        self.assertIn("鎖住", message)
        self.assertIn(str(self.home / ".claude-multi" / ".state" / "bindings.json"), message)
        box.showinfo.assert_not_called()

    def test_adding_with_a_locked_bindings_file_shows_an_error_with_its_path(self):
        with self.locked("bindings.json"), mock.patch("cc_quota_tracker.widget.messagebox") as box, \
                mock.patch("cc_quota_tracker.widget.simpledialog") as ask:
            ask.askstring.return_value = "home"
            self.widget.add_current_account()
        self.assertLockedBindingsError(box)

    def test_importing_with_a_locked_bindings_file_shows_an_error_with_its_path(self):
        source = self.home / "home.json"
        source.write_bytes(self.write_credentials(refresh="rt-2").read_bytes())
        with self.locked("bindings.json"), mock.patch("cc_quota_tracker.widget.messagebox") as box, \
                mock.patch("cc_quota_tracker.widget.simpledialog") as ask, \
                mock.patch("cc_quota_tracker.widget.filedialog") as files:
            files.askopenfilename.return_value = str(source)
            ask.askstring.return_value = "home"
            self.widget.import_credential_file()
        self.assertLockedBindingsError(box)


class ThemeTest(WidgetTestCase):
    def fills(self):
        return {self.widget.canvas.itemcget(i, "fill") for i in self.widget.canvas.find_all()}

    def assertShows(self, theme):
        other = "dark" if theme == "light" else "light"
        self.assertIn(THEMES[theme]["panel"], self.fills())
        self.assertNotIn(THEMES[other]["panel"], self.fills())

    def test_follows_system_by_default_and_rechecks_every_round(self):
        self.assertEqual(self.widget.menu_state().theme, "system")
        self.assertShows("light")
        self.system_theme = "dark"  # Windows 切換了應用程式深淺色
        self.widget.refresh()
        self.assertShows("dark")
        self.system_theme = "light"
        self.widget.refresh()
        self.assertShows("light")

    def test_chosen_theme_ignores_the_system(self):
        self.system_theme = "dark"
        self.widget.set_preference("theme", "light")
        self.widget.refresh()
        self.assertShows("light")
        self.assertEqual(self.settings()["theme"], "light")

    def test_switching_back_and_forth_keeps_the_same_items(self):
        before = self.widget.canvas.find_all()
        for theme in ("dark", "light", "system", "dark") * 5:
            self.widget.set_preference("theme", theme)
        self.widget.set_preference("theme", "light")
        self.assertEqual(self.widget.canvas.find_all(), before)  # 同一批 item，只改了屬性


class PositionTest(WidgetTestCase):
    def state_file(self):
        return self.home / ".claude-multi" / ".state" / "window.json"

    def reopen(self):
        self.root.update()  # 先跑完排隊中的 idle 事件，否則重建 Tk 時 ttk 會對已銷毀的直譯器發事件而印出雜訊
        self.widget.close()
        self.root = tk.Tk()
        self.root.withdraw()
        self.open_widget()
        self.root.update_idletasks()

    def test_position_is_remembered_in_tool_state_not_in_settings_file(self):
        self.root.geometry("+321+123")
        self.root.update_idletasks()
        self.reopen()
        self.assertEqual((self.root.winfo_x(), self.root.winfo_y()), (321, 123))
        self.assertEqual(json.loads(self.state_file().read_text(encoding="utf-8")), {"x": 321, "y": 123})
        self.assertNotIn("x", self.settings())

    def test_position_off_every_screen_moves_back_to_primary(self):
        self.root.geometry("+5000+4000")
        self.root.update_idletasks()
        self.on_screen = lambda x, y: x < 3000
        self.reopen()
        self.assertEqual((self.root.winfo_x(), self.root.winfo_y()), DEFAULT_POSITION)

    def test_unreadable_position_uses_default(self):
        self.root.update()
        self.widget.close()
        self.state_file().write_text("nonsense", encoding="utf-8")
        self.root = tk.Tk()
        self.root.withdraw()
        self.open_widget()
        self.root.update_idletasks()
        self.assertEqual((self.root.winfo_x(), self.root.winfo_y()), DEFAULT_POSITION)

    def test_position_is_not_remembered_before_the_tool_state_directory_exists(self):
        shutil.rmtree(self.state_file().parent)
        self.root.geometry("+321+123")
        self.root.update_idletasks()
        self.widget._save_position()
        self.assertFalse(self.state_file().parent.exists())

    def test_permissions_that_cannot_be_tightened_still_remember_the_position(self):
        self.root.geometry("+321+123")
        self.root.update_idletasks()
        with mock.patch("cc_quota_tracker.managed_directory.make_private"), \
                mock.patch("cc_quota_tracker.managed_directory.is_private", return_value=False):
            self.widget._save_position()
        self.assertEqual(json.loads(self.state_file().read_text(encoding="utf-8")), {"x": 321, "y": 123})


class DismissUntightenedTest(WidgetTestCase):
    """看板的「權限無法收緊」橫幅可以從右鍵選單關掉（ADR-0008）。"""

    def untightenable(self):
        from tests.test_untightened import untightenable
        return untightenable()

    def banner_shown(self):
        return any("納管目錄的權限無法收緊" in t for t in visible_texts(self.widget.canvas))

    def test_the_menu_entry_appears_only_while_the_warning_is_lit(self):
        self.assertNotIn("不再提醒權限未收緊", self.widget.menu_labels())
        with self.untightenable():
            self.widget.refresh()
        labels = self.widget.menu_labels()
        self.assertEqual(labels[labels.index("開啟資料夾") + 1], "不再提醒權限未收緊")
        self.assertTrue(self.banner_shown())

    def test_dismissing_hides_the_banner_and_the_entry(self):
        with self.untightenable():
            self.widget.refresh()
            self.widget.dismiss_untightened_warning()
        self.assertFalse(self.banner_shown())
        self.assertNotIn("不再提醒權限未收緊", self.widget.menu_labels())

    def test_the_entry_and_the_entries_after_it_follow_the_language(self):
        with self.untightenable():
            self.widget.refresh()
            self.widget.set_preference("language", "en")
            self.assertEqual(self.widget.menu_labels()[-3:],
                             ["Open folder", "Stop warning about unrestricted permissions", "Quit"])
            self.widget.dismiss_untightened_warning()
        self.widget.set_preference("language", "zh-TW")
        self.assertEqual(self.widget.menu_labels()[-2:], ["開啟資料夾", "結束"])


if __name__ == "__main__":
    unittest.main()
