"""縫 ③：版面的語系。三種版面在英文下不留中文、換語系只改既有 item 的文字、兩個語系的 item 結構一致。"""
import re
import tkinter as tk
import unittest
from dataclasses import replace
from datetime import timedelta

from cc_quota_tracker import COMMAND
from cc_quota_tracker.board import BreakdownRow, WeeklyBreakdown
from cc_quota_tracker.canvas_text import LINE_TAG
from cc_quota_tracker.fmt import absolute
from cc_quota_tracker.layout_a import LayoutA
from cc_quota_tracker.layout_b import LayoutB
from cc_quota_tracker.layout_c import LayoutC
from tests.fakehome import NOW
from tests.test_layout_a import BOARDS, EXPANDED_BOARDS, FULL, visible_texts

HAN = re.compile(r"[⺀-鿿＀-￯]")
LAYOUTS = (LayoutA, LayoutB, LayoutC)
# 供應商給的原始值（用量去向的名稱、鎖定原因、限額名稱）不翻譯；測試用的看板把它們換成英文，剩下的中文就一定是漏翻
_ENGLISH_FULL = replace(FULL, weekly_breakdown=WeeklyBreakdown(
    FULL.weekly_breakdown.started_at, FULL.weekly_breakdown.ends_at,
    (BreakdownRow("claude_code", "Claude Code", 70), BreakdownRow("chat", "Chat", 30))))
BOARDS_EN = [replace(b, cards=tuple(_ENGLISH_FULL if c is FULL else c for c in b.cards)) for b in EXPANDED_BOARDS]


class LayoutLanguageTestCase(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # 沒有顯示環境
            self.skipTest(f"Tk 無法啟動：{e}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.canvas = tk.Canvas(self.root)

    def shown(self, layout, board, lang, expanded=False):
        layout.render(board, "light", expanded, lang)
        return visible_texts(self.canvas)

    def fixed_items(self):
        """不是折行文字的 item：它們的數量只由看板與模式決定，換語系不能重建。"""
        return tuple(i for i in self.canvas.find_all() if LINE_TAG not in self.canvas.gettags(i))


class EveryLayoutTest(LayoutLanguageTestCase):
    def test_english_leaves_no_chinese_on_screen(self):
        for make in LAYOUTS:
            for expanded in (False, True):
                for i, board in enumerate(BOARDS_EN):
                    canvas = tk.Canvas(self.root)
                    layout = make(canvas)
                    layout.render(board, "light", expanded, "en")
                    for shown in visible_texts(canvas):
                        self.assertIsNone(HAN.search(shown), (make.__name__, expanded, i, shown))
                    layout.destroy()

    def test_chinese_still_shows_chinese(self):
        for make in LAYOUTS:
            layout = make(self.canvas)
            shown = "\n".join(self.shown(layout, BOARDS[0], "zh-TW", expanded=True))
            self.assertTrue(HAN.search(shown), make.__name__)
            layout.destroy()

    def test_switching_language_only_changes_text_on_the_existing_items(self):
        for make in LAYOUTS:
            for expanded in (False, True):
                layout = make(self.canvas)
                board = EXPANDED_BOARDS[0]
                before = self.shown(layout, board, "zh-TW", expanded)
                items = self.fixed_items()
                english = self.shown(layout, board, "en", expanded)
                self.assertEqual(self.fixed_items(), items, (make.__name__, expanded))  # 同一批 item，沒有重建
                self.assertNotEqual(english, before)
                self.assertEqual(self.shown(layout, board, "zh-TW", expanded), before)
                self.assertEqual(self.fixed_items(), items, (make.__name__, expanded))
                layout.destroy()

    def test_switching_language_back_and_forth_does_not_accumulate_items(self):
        for make in LAYOUTS:
            layout = make(self.canvas)
            counts = set()
            for i in range(10):
                layout.render(EXPANDED_BOARDS[0], "light", True, ("zh-TW", "en")[i % 2])
                counts.add((i % 2, len(self.canvas.find_all())))
            self.assertEqual(len({lang for lang, _ in counts}), 2)
            for lang in (0, 1):
                self.assertEqual(len({n for l, n in counts if l == lang}), 1, make.__name__)
            layout.destroy()


class LayoutAEnglishTest(LayoutLanguageTestCase):
    def test_a_card_reads_in_english(self):
        layout = LayoutA(self.canvas)
        shown = self.shown(layout, BOARDS[0], "en")
        for text in ("work", "Active", "Reading 3 min ago", "Session window", "Weekly window", "42%", "88%",
                     f"Resets: in 2h 0m ({absolute(NOW + timedelta(hours=2), NOW)})",
                     f"Credential snapshot expires in 25d 0h ({absolute(NOW + timedelta(days=25), NOW)})"):
            self.assertIn(text, shown)

    def test_english_versions_of_the_domain_states(self):
        layout = LayoutA(self.canvas)
        shown = self.shown(layout, BOARDS[3], "en")
        self.assertIn("No open window", shown)
        self.assertIn("Reset, next reset time unknown", shown)
        unmanaged = "\n".join(self.shown(layout, BOARDS[2], "en"))
        self.assertIn(f"{COMMAND} add <label>", unmanaged)
        self.assertIn("\"Manage the signed-in account…\"", unmanaged)  # 與右鍵選單的英文名稱一致

    def test_expanded_extras_read_in_english(self):
        layout = LayoutA(self.canvas)
        shown = "\n".join(self.shown(layout, BOARDS_EN[0], "en", expanded=True))
        for text in ("Weekly limit (Opus)", "Where this week's usage went", "Other limits (2)", "Standby",
                     "Observed 3 d ago"):
            self.assertIn(text, shown)


class LayoutBEnglishTest(LayoutLanguageTestCase):
    def test_strip_uses_the_short_window_names(self):
        layout = LayoutB(self.canvas)
        shown = self.shown(layout, BOARDS[0], "en")
        for text in ("Session", "Week", "42%", "88%", "3 min ago"):
            self.assertIn(text, shown)

    def test_table_headers_and_cells_read_in_english(self):
        layout = LayoutB(self.canvas)
        shown = self.shown(layout, BOARDS_EN[0], "en", expanded=True)
        for text in ("Account", "Session window", "Weekly window", "Reading", "Snapshot expires", "Active", "Standby"):
            self.assertIn(text, shown)


class LayoutCEnglishTest(LayoutLanguageTestCase):
    def test_legend_reads_in_english(self):
        layout = LayoutC(self.canvas)
        shown = self.shown(layout, BOARDS[0], "en")
        for text in ("Session 42%", "Week 88%", "Active", "Reading 3 min ago"):
            self.assertIn(text, shown)

    def test_notes_of_side_by_side_accounts_name_the_account(self):
        layout = LayoutC(self.canvas)
        shown = self.shown(layout, BOARDS_EN[0], "en", expanded=True)  # 三個帳號並列：LAB 的提示冠上標籤
        self.assertIn("lab: No reading yet", shown)


class NoOverlapTest(LayoutLanguageTestCase):
    def overlaps(self, canvas):
        boxes = [(canvas.itemcget(i, "text"), canvas.bbox(i)) for i in canvas.find_all()
                 if canvas.type(i) == "text" and canvas.itemcget(i, "state") != "hidden" and canvas.itemcget(i, "text")]
        return [(a, b) for n, (a, (ax1, ay1, ax2, ay2)) in enumerate(boxes) for b, (bx1, by1, bx2, by2) in boxes[n + 1:]
                if ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2]

    def test_no_two_texts_overlap_in_either_language(self):
        for make in LAYOUTS:
            for lang in ("zh-TW", "en"):
                for expanded in (False, True):
                    for i, board in enumerate(BOARDS_EN):
                        canvas = tk.Canvas(self.root)
                        layout = make(canvas)
                        layout.render(board, "light", expanded, lang)
                        self.assertEqual(self.overlaps(canvas), [], (make.__name__, lang, expanded, i))
                        layout.destroy()


class LayoutALaggingNoteTest(LayoutLanguageTestCase):
    def test_english_lagging_note_stays_on_one_line(self):
        layout = LayoutA(self.canvas)
        shown = self.shown(layout, BOARDS_EN[0], "en")
        self.assertIn("New activity; usage not updated", shown)  # 折成兩行的話，整句不會出現在同一個 item


if __name__ == "__main__":
    unittest.main()
