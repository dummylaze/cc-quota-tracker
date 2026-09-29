"""縫 ②：版面 B（密集表格／單行條）。同一個 widget 連續渲染看板、在精簡與展開、淺色與深色之間來回切換，item 數不能累積。"""
import tkinter as tk
import unittest
from datetime import timedelta

from cc_quota_tracker.board import Board
from cc_quota_tracker.fmt import absolute
from cc_quota_tracker.layout_b import EXPANDED_TAG, LayoutB
from cc_quota_tracker.tokens import THEMES
from tests.fakehome import NOW
from tests.test_layout_a import ACTIVE, BOARDS, EXPANDED_BOARDS, FULL, LAB, PERSONAL, visible_texts


class LayoutBTestCase(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # 沒有顯示環境
            self.skipTest(f"Tk 無法啟動：{e}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.canvas = tk.Canvas(self.root)
        self.layout = LayoutB(self.canvas)

    def items(self):
        return len(self.canvas.find_all())

    def shown(self, board, expanded=False, theme="light"):
        self.layout.render(board, theme, expanded)
        return visible_texts(self.canvas)

    def visible(self, item):
        return self.canvas.itemcget(item, "state") != "hidden"

    def text_item(self, text):
        return next(i for i in self.canvas.find_all() if self.canvas.type(i) == "text" and self.visible(i)
                    and self.canvas.itemcget(i, "text") == text)

    def fills(self, color):
        return [i for i in self.canvas.find_all() if self.visible(i) and self.canvas.type(i) != "text"
                and self.canvas.itemcget(i, "fill") == color]


class LayoutBCompactTest(LayoutBTestCase):
    def test_one_line_with_label_both_windows_age_and_note_count(self):
        shown = self.shown(Board(cards=(FULL, PERSONAL), as_of=NOW))
        for text in ("work", "工作階段", "42%", "週", "88%", "3 分鐘前", "3 則提示"):
            self.assertIn(text, shown)
        self.assertNotIn("personal", shown)  # 只有使用中帳號
        # 一行：所有文字的垂直中心都在同一條線上
        centers = {round(sum(self.canvas.bbox(self.text_item(t))[1::2]) / 2) for t in ("work", "42%", "3 分鐘前")}
        self.assertLessEqual(max(centers) - min(centers), 1)

    def test_bars_are_filled_by_severity(self):
        self.shown(BOARDS[0])
        c = THEMES["light"]
        fills = [self.canvas.itemcget(i, "fill") for i in self.canvas.find_withtag("bar-fill") if self.visible(i)]
        self.assertEqual(sorted(fills), sorted([c["normal"], c["critical"]]))

    def test_no_open_window_is_not_shown_as_zero_percent(self):
        shown = self.shown(BOARDS[3])
        self.assertIn("無計時中窗口", shown)
        self.assertIn("已重置，下次重置時間未知", shown)
        self.assertNotIn("0%", shown)

    def test_note_count_dot_takes_the_most_severe_color(self):
        self.shown(BOARDS[3])  # 憑證快照已失效：critical
        self.assertTrue(self.fills(THEMES["light"]["critical"]))
        self.shown(BOARDS[0])  # 只有到期時間的告知：版面不列提示
        self.assertNotIn("則提示", "".join(visible_texts(self.canvas)))

    def test_item_count_returns_to_same_value_across_board_states_and_themes(self):
        counts = {}
        for i in range(30):
            key = (i % len(BOARDS), ("light", "dark")[i % 2])
            self.layout.render(BOARDS[key[0]], key[1])
            counts.setdefault(key, set()).add(self.items())
        for key, seen in counts.items():
            self.assertEqual(len(seen), 1, key)

    def test_theme_switch_only_changes_attributes(self):
        self.layout.render(BOARDS[0], "light")
        before = self.canvas.find_all()
        self.layout.render(BOARDS[0], "dark")
        self.assertEqual(self.canvas.find_all(), before)

    def test_banner_is_shown_in_compact_mode_too(self):
        shown = "\n".join(self.shown(EXPANDED_BOARDS[2]))
        self.assertIn("結構已變更", shown)

    def test_destroy_removes_every_item(self):
        self.shown(BOARDS[0])
        self.layout.destroy()
        self.assertEqual(self.items(), 0)


class LayoutBExpandedTest(LayoutBTestCase):
    def test_one_row_per_account_under_column_headers(self):
        shown = self.shown(EXPANDED_BOARDS[0], expanded=True)
        for header in ("帳號", "工作階段窗口", "週窗口", "讀數", "憑證到期"):
            self.assertIn(header, shown)
        for label in ("work", "personal", "lab"):
            self.assertIn(label, shown)
        self.assertEqual(shown.count("使用中"), 1)
        self.assertEqual(shown.count("待命"), 2)
        self.assertIn("3 天前", shown)

    def test_rows_follow_board_order(self):
        self.shown(EXPANDED_BOARDS[0], expanded=True)
        ys = [self.canvas.coords(self.text_item(label))[1] for label in ("work", "personal", "lab")]
        self.assertEqual(ys, sorted(ys))

    def test_credential_expiry_is_a_countdown_with_absolute_time(self):
        shown = self.shown(Board(cards=(ACTIVE, PERSONAL), as_of=NOW), expanded=True)
        self.assertIn(f"25天0小時後（{absolute(NOW + timedelta(days=25), NOW)}）", shown)
        self.assertIn(f"22天0小時後（{absolute(NOW + timedelta(days=22), NOW)}）", shown)
        self.assertFalse([t for t in shown if "憑證快照" in t])  # 只是告知的到期時間已在欄位裡，不再重複成提示

    def test_notes_sit_under_their_own_row(self):
        self.shown(EXPANDED_BOARDS[0], expanded=True)
        work_y = self.canvas.coords(self.text_item("work"))[1]
        personal_y = self.canvas.coords(self.text_item("personal"))[1]
        for text in ("有新對話，額度尚未更新", "額度已鎖定：weekly_limit_reached"):
            y = self.canvas.coords(self.first_line_of(text))[1]
            self.assertTrue(work_y < y < personal_y, text)
        lab_y = self.canvas.coords(self.text_item("lab"))[1]
        self.assertGreater(self.canvas.coords(self.first_line_of("尚無讀數"))[1], lab_y)

    def first_line_of(self, text):
        return next(i for i in self.canvas.find_all() if self.canvas.type(i) == "text" and self.visible(i)
                    and self.canvas.itemcget(i, "text") and text.startswith(self.canvas.itemcget(i, "text").rstrip()[:6]))

    def test_expiry_warning_keeps_the_remedy_as_a_note(self):
        shown = self.shown(EXPANDED_BOARDS[0], expanded=True)
        self.assertTrue([t for t in shown if "後到期" in t and "add work" in t])
        self.assertTrue(self.fills(THEMES["light"]["warning"]))

    def test_active_row_has_a_tinted_background_and_standby_rows_do_not(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                self.shown(EXPANDED_BOARDS[0], expanded=True, theme=theme)
                bands = self.fills(THEMES[theme]["active_row"])
                self.assertEqual(len(bands), 1)
                top, bottom = self.canvas.bbox(bands[0])[1::2]
                self.assertTrue(top < self.canvas.coords(self.text_item("work"))[1] < bottom)
                self.assertGreater(self.canvas.coords(self.text_item("personal"))[1], bottom)

    def test_unmanaged_active_row_is_tinted_and_explains_how_to_manage(self):
        shown = "\n".join(self.shown(EXPANDED_BOARDS[1], expanded=True))
        self.assertIn("未納管帳號", shown)
        self.assertIn("「納管目前登入的帳號…」", shown)
        self.assertEqual(len(self.fills(THEMES["light"]["active_row"])), 1)

    def test_no_open_window_is_not_shown_as_zero_percent(self):
        shown = self.shown(Board(cards=(BOARDS[3].cards[0], PERSONAL), as_of=NOW), expanded=True)
        self.assertIn("無計時中窗口", shown)
        self.assertIn("已重置", shown)
        self.assertIn("下次重置時間未知", shown)
        self.assertNotIn("0%", shown)

    def test_compact_mode_creates_no_expanded_items(self):
        self.layout.render(EXPANDED_BOARDS[0], "light")
        self.assertEqual(self.canvas.find_withtag(EXPANDED_TAG), ())
        compact = self.items()
        self.layout.render(EXPANDED_BOARDS[0], "light", expanded=True)
        self.assertTrue(self.canvas.find_withtag(EXPANDED_TAG))
        self.layout.render(EXPANDED_BOARDS[0], "light")
        self.assertEqual(self.canvas.find_withtag(EXPANDED_TAG), ())
        self.assertEqual(self.items(), compact)

    def test_item_count_returns_to_same_value_across_modes_boards_and_themes(self):
        n = len(EXPANDED_BOARDS)
        counts = {}
        for i in range(4 * n * 3):
            key = (i % n, bool(i // n % 2), ("light", "dark")[i // (2 * n) % 2])
            self.layout.render(EXPANDED_BOARDS[key[0]], key[2], expanded=key[1])
            counts.setdefault(key, set()).add(self.items())
        for key, seen in counts.items():
            self.assertEqual(len(seen), 1, key)

    def test_accent_only_marks_the_active_account(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                self.shown(Board(cards=(ACTIVE, PERSONAL, LAB), as_of=NOW), expanded=True, theme=theme)
                self.assertEqual(len(self.fills(THEMES[theme]["accent"])), 1)  # 使用中標籤

    def test_destroy_after_expanded_removes_every_item(self):
        self.shown(EXPANDED_BOARDS[0], expanded=True)
        self.layout.destroy()
        self.assertEqual(self.items(), 0)


if __name__ == "__main__":
    unittest.main()
