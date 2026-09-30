"""縫 ②：版面 C（環形儀表）。同一個 widget 連續渲染看板、在精簡與展開、淺色與深色之間來回切換，item 數不能累積。"""
import tkinter as tk
import unittest
from datetime import timedelta

from cc_quota_tracker.board import Board, Card, ReadingState, Role
from cc_quota_tracker.layout_c import EXPANDED_TAG, WEEK_TAG, SESSION_TAG, LayoutC
from cc_quota_tracker.tokens import THEMES
from tests.fakehome import NOW
from tests.test_layout_a import ACTIVE, BOARDS, EXPANDED_BOARDS, FULL, LAB, PERSONAL, visible_texts, window

RESET_PREFIX = "重置："  # 窄格裡倒數會折成兩行，只比對開頭

FOURTH = Card("claude:extra", Role.STANDBY, ReadingState.HAS_READING, reading_age=timedelta(days=1),
              limits=(window("session", 5), window("weekly_all", 60)))


class LayoutCTestCase(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # 沒有顯示環境
            self.skipTest(f"Tk 無法啟動：{e}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.canvas = tk.Canvas(self.root)
        self.layout = LayoutC(self.canvas)

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

    def arcs(self, tag):
        return [i for i in self.canvas.find_withtag(tag) if self.visible(i)]

    def center(self, item):
        x1, y1, x2, y2 = self.canvas.bbox(item) if self.canvas.type(item) == "text" else self.canvas.coords(item)
        return (x1 + x2) / 2, (y1 + y2) / 2

    def accent_frames(self, theme="light"):
        """使用中帳號那一格的外框：只有輪廓、沒有填色，輪廓是 accent。"""
        return [i for i in self.canvas.find_all() if self.visible(i) and self.canvas.type(i) == "polygon"
                and self.canvas.itemcget(i, "outline") == THEMES[theme]["accent"]]

    def fills(self, color):
        return [i for i in self.canvas.find_all() if self.visible(i) and self.canvas.type(i) != "text"
                and self.canvas.itemcget(i, "fill") == color]


class LayoutCRingTest(LayoutCTestCase):
    def test_outer_ring_is_the_week_and_inner_ring_is_the_session(self):
        self.shown(BOARDS[0])
        (week,), (session,) = self.arcs(WEEK_TAG), self.arcs(SESSION_TAG)
        w, s = self.canvas.coords(week), self.canvas.coords(session)  # 弧的座標是整個圓的外框，不是畫出來的那一段
        self.assertTrue(w[0] < s[0] and w[1] < s[1] and s[2] < w[2] and s[3] < w[3])  # 內圈整個在外圈裡面
        self.assertEqual(self.center(week), self.center(session))  # 同心

    def test_arcs_are_filled_clockwise_from_the_top_by_percent_and_colored_by_severity(self):
        self.shown(BOARDS[0])
        c = THEMES["light"]
        week, session = self.arcs(WEEK_TAG)[0], self.arcs(SESSION_TAG)[0]
        for arc, percent, color in ((week, 88, c["critical"]), (session, 42, c["normal"])):
            self.assertEqual(float(self.canvas.itemcget(arc, "start")), 90)
            self.assertAlmostEqual(float(self.canvas.itemcget(arc, "extent")), -3.6 * percent)
            self.assertEqual(self.canvas.itemcget(arc, "outline"), color)

    def test_a_full_ring_is_still_drawn(self):
        full = Card("claude:work", Role.ACTIVE, ReadingState.HAS_READING, reading_age=timedelta(0),
                    limits=(window("session", 100), window("weekly_all", 100)))
        self.shown(Board(cards=(full,), as_of=NOW))
        for tag in (WEEK_TAG, SESSION_TAG):
            self.assertLess(float(self.canvas.itemcget(self.arcs(tag)[0], "extent")), -359)

    def test_center_shows_the_session_percent(self):
        shown = self.shown(BOARDS[0])
        self.assertIn("42%", shown)
        text, ring = self.center(self.text_item("42%")), self.center(self.arcs(SESSION_TAG)[0])
        self.assertAlmostEqual(text[0], ring[0], delta=2)
        self.assertAlmostEqual(text[1], ring[1], delta=2)

    def test_legend_names_both_windows_with_their_percent(self):
        shown = self.shown(BOARDS[0])
        self.assertIn("工作階段 42%", shown)
        self.assertIn("週 88%", shown)

    def test_no_open_window_is_not_shown_as_zero_percent(self):
        shown = self.shown(BOARDS[3])
        self.assertIn("工作階段 無計時中窗口", shown)
        self.assertIn("週 已重置，下次重置時間未知", shown)
        self.assertNotIn("0%", shown)
        self.assertIn("—", shown)  # 中央不畫成 0%
        self.assertEqual(self.arcs(WEEK_TAG) + self.arcs(SESSION_TAG), [])  # 沒有計時中窗口就沒有填色的弧

    def test_zero_percent_of_an_open_window_is_shown(self):
        shown = self.shown(BOARDS[4])  # 只有週窗口，用量 0%
        self.assertIn("週 0%", shown)
        self.assertIn("工作階段 —", shown)
        self.assertEqual(self.arcs(WEEK_TAG), [])  # 0% 沒有東西可填
        self.assertEqual(self.arcs(SESSION_TAG), [])

    def test_no_reading_shows_only_empty_rings_and_the_note(self):
        shown = self.shown(BOARDS[2])
        self.assertEqual(self.arcs(WEEK_TAG) + self.arcs(SESSION_TAG), [])
        self.assertTrue([t for t in shown if "尚無讀數" in t])
        self.assertNotIn("0%", shown)


class LayoutCCompactTest(LayoutCTestCase):
    def test_shows_only_the_active_account(self):
        shown = self.shown(Board(cards=(FULL, PERSONAL), as_of=NOW))
        self.assertIn("work", shown)
        self.assertIn("使用中", shown)
        self.assertIn("讀數 3 分鐘前", shown)
        self.assertNotIn("personal", shown)

    def test_notes_collapse_into_a_count_with_the_most_severe_dot(self):
        shown = "\n".join(self.shown(Board(cards=(FULL, PERSONAL), as_of=NOW)))
        self.assertIn("3 則提示", shown)
        for text in ("有新對話，額度尚未更新", "額度已鎖定：weekly_limit_reached", "後到期"):
            self.assertNotIn(text, shown)  # 完整文字展開才顯示
        self.assertTrue(self.fills(THEMES["light"]["critical"]))  # 色點取最嚴重那條（鎖定）

    def test_no_note_count_when_there_is_nothing_to_note(self):
        self.assertNotIn("則提示", "".join(self.shown(BOARDS[0])))  # 只有到期時間的告知：不列提示

    def test_compact_does_not_show_reset_countdowns(self):
        shown = self.shown(BOARDS[0])
        self.assertFalse([t for t in shown if "重置：" in t])
        self.assertIn("工作階段 42%", shown)

    def test_unmanaged_account_explains_how_to_manage(self):
        shown = "\n".join(self.shown(BOARDS[2]))
        self.assertIn("未納管帳號", shown)
        self.assertIn("「納管目前登入的帳號…」", shown)

    def test_banner_is_shown(self):
        shown = "\n".join(self.shown(EXPANDED_BOARDS[2]))
        self.assertIn("結構已變更", shown)

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

    def test_creates_no_expanded_items(self):
        self.layout.render(EXPANDED_BOARDS[0], "light")
        self.assertEqual(self.canvas.find_withtag(EXPANDED_TAG), ())

    def test_destroy_removes_every_item(self):
        self.shown(BOARDS[0])
        self.layout.destroy()
        self.assertEqual(self.items(), 0)


class LayoutCExpandedTest(LayoutCTestCase):
    FOUR = Board(cards=(ACTIVE, PERSONAL, LAB, FOURTH), as_of=NOW)

    def row_y(self, label):
        return self.canvas.coords(self.text_item(label))[1]

    def test_three_accounts_per_row(self):
        self.shown(self.FOUR, expanded=True)
        first, second, third, fourth = (self.row_y(x) for x in ("work", "personal", "lab", "extra"))
        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertGreater(fourth, third)
        xs = [self.canvas.coords(self.text_item(x))[0] for x in ("work", "personal", "lab")]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(len(set(xs)), 3)

    def test_every_account_gets_its_own_pair_of_rings(self):
        self.shown(self.FOUR, expanded=True)
        # 有窗口資料的帳號畫出弧：work、personal（只有週窗口）、extra；lab 沒有讀數
        self.assertEqual(len(self.arcs(WEEK_TAG)), 3)
        self.assertEqual(len(self.arcs(SESSION_TAG)), 2)

    def test_only_the_active_account_is_highlighted(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                self.shown(EXPANDED_BOARDS[0], expanded=True, theme=theme)
                (frame,) = self.accent_frames(theme)
                x1, _, x2, _ = self.canvas.bbox(frame)
                work_x = self.canvas.coords(self.text_item("work"))[0]
                personal_x = self.canvas.coords(self.text_item("personal"))[0]
                self.assertTrue(x1 < work_x < x2)
                self.assertGreater(personal_x, x2)
                self.assertEqual(len(self.fills(THEMES[theme]["accent"])), 1)  # 使用中標籤

    def test_chips_tell_active_from_standby(self):
        shown = self.shown(EXPANDED_BOARDS[0], expanded=True)
        self.assertEqual(shown.count("使用中"), 1)
        self.assertEqual(shown.count("待命"), 2)

    def test_notes_name_their_account_and_sit_below_the_cells(self):
        shown = self.shown(EXPANDED_BOARDS[0], expanded=True)
        for text in ("work：有新對話，額度尚未更新", "work：額度已鎖定：weekly_limit_reached", "lab：尚無讀數"):
            self.assertIn(text, shown)
        ring_bottom = max(self.canvas.coords(i)[3] for i in self.arcs(WEEK_TAG))
        for text in ("work：有新對話，額度尚未更新", "lab：尚無讀數"):
            first = next(i for i in self.canvas.find_all() if self.canvas.type(i) == "text" and self.visible(i)
                         and self.canvas.itemcget(i, "text").startswith(text[:5]))
            self.assertGreater(self.canvas.coords(first)[1], ring_bottom, text)

    def test_unmanaged_account_is_highlighted_and_explains_how_to_manage(self):
        shown = "\n".join(self.shown(EXPANDED_BOARDS[1], expanded=True))
        self.assertIn("未納管帳號", shown)
        self.assertIn("「納管目前登入的帳號…」", shown)
        self.assertEqual(len(self.accent_frames()), 1)

    def test_no_open_window_is_not_shown_as_zero_percent(self):
        shown = self.shown(Board(cards=(BOARDS[3].cards[0], PERSONAL), as_of=NOW), expanded=True)
        self.assertIn("週 已重置，下次重置時間未知", shown)
        self.assertIn("工作階段 無計時中窗口", shown)
        self.assertNotIn("0%", shown)

    def test_expanded_legend_shows_each_window_reset_countdown_on_its_own_line(self):
        shown = "\n".join(self.shown(Board(cards=(ACTIVE, PERSONAL), as_of=NOW), expanded=True))
        self.assertEqual(shown.count(RESET_PREFIX), 3)  # work 兩個窗口，personal 只有週窗口
        self.assertIn("工作階段 42%", shown)
        self.assertIn("週 88%", shown)

    def test_credential_expiry_warning_is_a_note(self):
        shown = self.shown(EXPANDED_BOARDS[0], expanded=True)
        self.assertTrue([t for t in shown if "後到期" in t and t.endswith("請重新納管")])
        self.assertTrue(self.fills(THEMES["light"]["warning"]))

    def test_expanded_items_exist_only_in_expanded_mode(self):
        self.layout.render(EXPANDED_BOARDS[0], "light")
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

    def test_destroy_after_expanded_removes_every_item(self):
        self.shown(EXPANDED_BOARDS[0], expanded=True)
        self.layout.destroy()
        self.assertEqual(self.items(), 0)


if __name__ == "__main__":
    unittest.main()
