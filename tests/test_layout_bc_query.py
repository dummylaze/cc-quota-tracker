"""縫 ②：版面 B（單行條、表格）與 C（精簡一格、展開多格）的「更新」入口與查詢狀態，與版面 A 一致：
入口只在落後或讀數待更新的使用中帳號出現，進行中與冷卻中不可點；查詢狀態與失敗原因、自動查詢已暫停跟在入口同一處；
所有新增的 Canvas item 與既有文字外框不重疊，入口旁的提示維持單行。兩個語系、兩種模式。"""
import re
import tkinter as tk
import tkinter.font as tkfont
import unittest
from dataclasses import replace

from cc_quota_tracker.board import QueryFailure, UsageQueryResult
from cc_quota_tracker.entry import CLICKABLE_TAG
from cc_quota_tracker.layout_b import LayoutB
from cc_quota_tracker.layout_c import LayoutC
from cc_quota_tracker.tokens import THEMES
from tests.test_layout_a import ACTIVE, FULL, LAB, PERSONAL, visible_lines, visible_texts
from tests.test_layout_a_query import (ENTRY_TEXTS, FAILURES, HAN, LAGGING, PENDING, _boxes, _overlap, board_of)

MODES = (False, True)  # 精簡、展開
COUNT = re.compile(r"^(\d+ 則提示|Notes: \d+)$")


class BCQueryMixin:
    """兩個版面共用的情境；子類給 make（版面類別）。"""
    make = None

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # 沒有顯示環境
            self.skipTest(f"Tk 無法啟動：{e}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.canvas = tk.Canvas(self.root)
        self.calls = []
        self.layout = self.make(self.canvas, on_query=lambda: self.calls.append("query"))

    def render(self, board, lang="zh-TW", expanded=False):
        self.layout.render(board, "light", expanded, lang)
        return visible_texts(self.canvas)

    def entries(self):
        return [i for i in self.canvas.find_all() if self.canvas.type(i) == "text"
                and self.canvas.itemcget(i, "state") != "hidden" and self.canvas.itemcget(i, "text") in ENTRY_TEXTS]

    def entry(self):
        (item,) = self.entries()
        return item

    def clickable(self, item):
        return CLICKABLE_TAG in self.canvas.gettags(item)

    def click(self, item):
        # Canvas 只在視窗真的顯示時才會依游標位置挑出「目前的 item」：把視窗搬到螢幕外再顯示
        if not self.root.winfo_viewable():
            self.root.geometry("+-3000+-3000")
            self.root.deiconify()
            self.canvas.pack()
            self.addCleanup(self.root.update)  # 銷毀前先處理完待辦事件，不然 ttk 的主題事件會對已銷毀的視窗報錯
        self.root.update()
        x1, y1, x2, y2 = self.canvas.bbox(item)
        x, y = int((x1 + x2) / 2), int((y1 + y2) / 2)
        self.canvas.event_generate("<Motion>", x=x, y=y)
        self.canvas.event_generate("<Button-1>", x=x, y=y)

    def line_of(self, pattern):
        """畫面上文字符合 pattern 的那一段（單行 item 或接回的多行文字）。"""
        (hit,) = [t for t in visible_texts(self.canvas) if re.search(pattern, t)]
        return hit

    # --- 入口出現條件 ---

    def test_a_lagging_or_pending_active_card_offers_an_update_entry_in_both_languages(self):
        for expanded in MODES:
            for card in (LAGGING, PENDING):
                self.render(board_of(card), "zh-TW", expanded)
                self.assertEqual(self.canvas.itemcget(self.entry(), "text"), "更新", (expanded, card.reading_state))
                self.render(board_of(card), "en", expanded)
                self.assertEqual(self.canvas.itemcget(self.entry(), "text"), "Update", (expanded, card.reading_state))

    def test_no_entry_when_the_reading_is_neither_lagging_nor_pending(self):
        for expanded in MODES:
            for card in (ACTIVE, LAB):
                self.render(board_of(card), expanded=expanded)
                self.assertEqual(self.entries(), [], (expanded, card))

    def test_standby_cards_never_get_an_entry(self):
        standby = replace(PERSONAL, lagging=True)
        self.render(board_of(LAGGING, standby, replace(LAB, reading_state=PENDING.reading_state)), expanded=True)
        self.assertEqual(len(self.entries()), 1)

    def test_a_pending_card_never_shows_the_long_hint_beside_the_entry(self):
        for expanded in MODES:
            shown = self.render(board_of(PENDING), expanded=expanded)
            self.assertFalse([t for t in shown if "Claude Code 更新額度快取後就會出現" in t], expanded)

    # --- 可點狀態 ---

    def test_idle_entry_is_clickable_and_underlined(self):
        for expanded in MODES:
            self.render(board_of(LAGGING), expanded=expanded)
            item = self.entry()
            self.assertTrue(self.clickable(item), expanded)
            self.assertTrue(tkfont.nametofont(self.canvas.itemcget(item, "font")).actual("underline"), expanded)
            self.assertEqual(self.canvas.itemcget(item, "fill"), THEMES["light"]["fg"], expanded)

    def test_in_progress_shows_a_busy_label_that_cannot_be_clicked(self):
        for expanded in MODES:
            for card in (LAGGING, PENDING):
                self.render(board_of(card, in_progress=True), expanded=expanded)
                item = self.entry()
                self.assertEqual(self.canvas.itemcget(item, "text"), "查詢中…", (expanded, card.reading_state))
                self.assertFalse(self.clickable(item), (expanded, card.reading_state))
            self.render(board_of(LAGGING, in_progress=True), "en", expanded)
            self.assertEqual(self.canvas.itemcget(self.entry(), "text"), "Updating…")

    def test_cooldown_keeps_the_label_but_greys_it_out_and_cannot_be_clicked(self):
        for expanded in MODES:
            self.render(board_of(LAGGING, cooling_down=True), expanded=expanded)
            item = self.entry()
            self.assertEqual(self.canvas.itemcget(item, "text"), "更新", expanded)
            self.assertFalse(self.clickable(item), expanded)
            self.assertFalse(tkfont.nametofont(self.canvas.itemcget(item, "font")).actual("underline"), expanded)
            self.assertEqual(self.canvas.itemcget(item, "fill"), THEMES["light"]["sub"], expanded)

    def test_the_entry_becomes_clickable_again_by_rendering_an_idle_board(self):
        for expanded in MODES:
            self.render(board_of(LAGGING, cooling_down=True), expanded=expanded)
            self.render(board_of(LAGGING), expanded=expanded)
            self.assertTrue(self.clickable(self.entry()), expanded)

    def test_clicking_an_idle_entry_calls_back_once(self):
        for expanded in MODES:
            self.calls.clear()
            self.render(board_of(LAGGING), expanded=expanded)
            self.click(self.entry())
            self.root.update()
            self.assertEqual(self.calls, ["query"], expanded)

    def test_clicking_a_busy_or_cooling_entry_does_nothing(self):
        for expanded in MODES:
            for status in ({"in_progress": True}, {"cooling_down": True}):
                self.render(board_of(LAGGING, **status), expanded=expanded)
                self.click(self.entry())
        self.assertEqual(self.calls, [])

    def test_the_entry_is_the_only_new_clickable_item(self):
        for expanded in MODES:
            self.render(board_of(FULL), expanded=expanded)
            clickable = [i for i in self.canvas.find_withtag(CLICKABLE_TAG) if self.canvas.itemcget(i, "state") != "hidden"]
            self.assertEqual([self.canvas.itemcget(i, "text") for i in clickable], ["更新"], expanded)

    # --- 查詢狀態與失敗原因：跟在入口同一處 ---

    def test_each_failure_reason_reads_differently_and_points_to_usage(self):
        for expanded in MODES:
            for lang, tail in (("zh-TW", "在 Claude Code 執行 /usage"), ("en", "Try /usage in Claude Code instead")):
                seen = {}
                for failure, result in FAILURES.items():
                    shown = self.render(board_of(LAGGING, last_failure=result), lang, expanded)
                    (line,) = [t for t in shown if re.search("查詢失敗|Update failed", t)]
                    self.assertIn(tail, line)
                    seen[failure] = line
                self.assertEqual(len(set(seen.values())), 4, (lang, expanded))
                self.assertIn("Not logged in", seen[QueryFailure.REPORTED_ERROR])

    def test_a_paused_auto_query_replaces_the_failure_line_and_keeps_the_reason(self):
        for expanded in MODES:
            for lang, paused, failed in (("zh-TW", "自動查詢已暫停：", "查詢失敗"), ("en", "Auto-query paused: ", "Update failed")):
                seen = {}
                for failure, result in FAILURES.items():
                    shown = self.render(board_of(LAGGING, last_failure=result, auto_enabled=True, auto_paused=True), lang, expanded)
                    (line,) = [t for t in shown if paused in t]
                    self.assertFalse([t for t in shown if failed in t], (lang, expanded, failure))  # 不重複顯示
                    seen[failure] = line
                self.assertEqual(len(set(seen.values())), 4, (lang, expanded))

    def test_the_status_shows_on_a_card_that_has_no_entry_too(self):
        failure = FAILURES[QueryFailure.TIMEOUT]
        for expanded in MODES:
            shown = self.render(board_of(ACTIVE, last_failure=failure, auto_enabled=True, auto_paused=True), expanded=expanded)
            self.assertTrue([t for t in shown if "自動查詢已暫停：" in t], expanded)
            self.assertEqual(self.entries(), [], expanded)
            shown = self.render(board_of(ACTIVE, last_failure=failure), expanded=expanded)
            self.assertTrue([t for t in shown if "查詢失敗" in t], expanded)
            self.assertIn("查詢中…", self.render(board_of(ACTIVE, in_progress=True), expanded=expanded))
            self.assertNotIn("查詢中…", self.render(board_of(ACTIVE, cooling_down=True), expanded=expanded))
            self.assertNotIn("查詢中…", self.render(board_of(ACTIVE), expanded=expanded))

    def test_only_the_non_standby_card_carries_the_status(self):
        shown = self.render(board_of(LAGGING, PERSONAL, last_failure=FAILURES[QueryFailure.TIMEOUT]), expanded=True)
        self.assertEqual(len([t for t in shown if "查詢失敗" in t]), 1)

    def test_a_long_raw_message_is_cut_at_sixty_characters(self):
        for expanded in MODES:
            shown = self.render(board_of(LAGGING, last_failure=UsageQueryResult(QueryFailure.REPORTED_ERROR, message="x" * 61)),
                                expanded=expanded)
            line = next(t for t in shown if "查詢失敗" in t)
            self.assertIn("x" * 60 + "…", line)
            self.assertNotIn("x" * 61, line)

    def test_the_failure_does_not_clear_the_existing_reading(self):
        for expanded in MODES:
            shown = self.render(board_of(LAGGING, last_failure=FAILURES[QueryFailure.TIMEOUT]), expanded=expanded)
            for text in ("work", "42%", "88%"):
                self.assertTrue([t for t in shown if text in t], (expanded, text))  # 版面 C 的窗口說明是「週 88%」一段

    def test_english_leaves_no_chinese_on_screen(self):
        for expanded in MODES:
            for card in (LAGGING, PENDING, ACTIVE):
                for status in ({}, {"in_progress": True}, {"cooling_down": True},
                               {"auto_enabled": True, "auto_paused": True}, {"auto_enabled": True, "interval_below_floor": True}):
                    for failure in (None, *FAILURES.values()):
                        for shown in self.render(board_of(card, last_failure=failure, **status), "en", expanded):
                            self.assertIsNone(HAN.search(shown), (expanded, card.reading_state, status, failure, shown))

    # --- 版面 ---

    def states(self):
        failure = FAILURES[QueryFailure.REPORTED_ERROR]
        long_failure = UsageQueryResult(QueryFailure.REPORTED_ERROR, message="a very long message " * 5)
        for card in (LAGGING, PENDING, ACTIVE, FULL):
            for status in ({}, {"in_progress": True}, {"cooling_down": True}, {"last_failure": failure},
                           {"in_progress": True, "last_failure": long_failure},
                           {"last_failure": failure, "auto_enabled": True, "auto_paused": True},
                           {"last_failure": long_failure, "auto_enabled": True, "auto_paused": True, "cooling_down": True},
                           {"auto_enabled": True, "interval_below_floor": True}):
                yield card, status

    def test_no_text_overlaps_another_in_either_language_and_mode(self):
        for lang in ("zh-TW", "en"):
            for expanded in MODES:
                for card, status in self.states():
                    self.render(board_of(card, PERSONAL, LAB, **status), lang, expanded)
                    boxes = _boxes(self.canvas)
                    for n, (i, a) in enumerate(boxes):
                        for j, b in boxes[n + 1:]:
                            self.assertFalse(_overlap(a, b), (lang, expanded, card.reading_state, status,
                                                              self.canvas.itemcget(i, "text"), self.canvas.itemcget(j, "text")))

    def test_the_entry_stays_inside_the_card(self):
        for lang in ("zh-TW", "en"):
            for expanded in MODES:
                for card, status in self.states():
                    self.render(board_of(card, PERSONAL, **status), lang, expanded)
                    width = int(float(self.canvas.cget("width")))
                    for item in self.entries():
                        x1, _, x2, _ = self.canvas.bbox(item)
                        self.assertTrue(0 < x1 and x2 < width, (lang, expanded, card.reading_state, status, x1, x2, width))

    def test_item_count_does_not_depend_on_the_language(self):
        fixed = {}
        for lang in ("zh-TW", "en"):
            for k, (card, status) in enumerate(self.states()):
                for expanded in MODES:
                    self.render(board_of(card, PERSONAL, **status), lang, expanded)
                    fixed.setdefault((k, expanded), set()).add(len([i for i in self.canvas.find_all()
                                                                     if "wrapped-line" not in self.canvas.gettags(i)]))
        for key, seen in fixed.items():
            self.assertEqual(len(seen), 1, key)  # 折行文字的行數隨語系而變，其餘 item 不變

    def test_item_count_comes_back_after_visiting_other_states(self):
        counts = {}
        states = list(self.states())
        for n in range(60):
            card, status = states[(n * 7) % len(states)]
            for expanded in MODES:
                self.render(board_of(card, PERSONAL, **status), expanded=expanded)
                counts.setdefault(((n * 7) % len(states), expanded), set()).add(
                    len([i for i in self.canvas.find_all() if "wrapped-line" not in self.canvas.gettags(i)]))
        for key, seen in counts.items():
            self.assertEqual(len(seen), 1, key)

    def test_destroy_removes_the_entry_and_status_items(self):
        for expanded in MODES:
            self.render(board_of(LAGGING, last_failure=FAILURES[QueryFailure.TIMEOUT]), expanded=expanded)
            self.layout.destroy()
            self.assertEqual(len(self.canvas.find_all()), 0, expanded)
            self.layout = self.make(self.canvas)

    def test_the_entry_without_on_query_is_just_drawn(self):
        layout = self.make(self.canvas)
        layout.render(board_of(LAGGING), "light", False, "zh-TW")
        self.click(self.entry())  # 沒有接線：不丟例外

    def test_switching_language_only_changes_text_on_the_existing_items(self):
        board = board_of(LAGGING, last_failure=FAILURES[QueryFailure.TIMEOUT], cooling_down=True)
        for expanded in MODES:
            self.render(board, expanded=expanded)
            items = tuple(i for i in self.canvas.find_all() if "wrapped-line" not in self.canvas.gettags(i))
            self.render(board, "en", expanded)
            self.assertEqual(tuple(i for i in self.canvas.find_all() if "wrapped-line" not in self.canvas.gettags(i)), items)


class ExpandedHostLineMixin:
    """展開模式：入口與落後（或待更新）那條提示同一行靠右，提示維持單行，狀態接在它底下。"""

    HINTS = {"zh-TW": ("有新對話，額度尚未更新", "讀數待更新"), "en": ("New activity; usage not updated", "Reading pending")}

    def test_the_hint_next_to_the_entry_stays_on_one_line(self):
        for lang, (lagging, pending) in self.HINTS.items():
            for card, hint in ((LAGGING, lagging), (PENDING, pending)):
                for status in ({}, {"in_progress": True}, {"cooling_down": True}):
                    self.render(board_of(card, PERSONAL, **status), lang, True)
                    blocks = [lines for lines in visible_lines(self.canvas) if hint in "".join(t for _, t, _ in lines)]
                    self.assertEqual(len(blocks), 1, (lang, hint, status))
                    self.assertEqual(len(blocks[0]), 1, (lang, hint, status))

    def test_the_entry_sits_on_the_hints_line_to_the_right_of_it(self):
        for card, hint in ((LAGGING, "有新對話，額度尚未更新"), (PENDING, "讀數待更新")):
            self.render(board_of(card), expanded=True)
            entry = self.canvas.bbox(self.entry())
            (line,) = [i for i in self.canvas.find_withtag("wrapped-line") if hint in self.canvas.itemcget(i, "text")]
            hint_box = self.canvas.bbox(line)
            self.assertGreater(entry[0], hint_box[2])
            self.assertLess(abs((entry[1] + entry[3]) / 2 - (hint_box[1] + hint_box[3]) / 2), 2)

    def test_a_pending_card_uses_the_short_hint_beside_the_entry(self):
        self.assertTrue([t for t in self.render(board_of(PENDING), expanded=True) if "讀數待更新" in t])

    def test_the_status_lines_come_after_the_hint(self):
        self.render(board_of(LAGGING, last_failure=FAILURES[QueryFailure.TIMEOUT]), expanded=True)
        hint = next(i for i in self.canvas.find_withtag("wrapped-line") if "有新對話" in self.canvas.itemcget(i, "text"))
        status = next(i for i in self.canvas.find_withtag("wrapped-line") if "查詢失敗" in self.canvas.itemcget(i, "text"))
        self.assertLess(self.canvas.bbox(hint)[3], self.canvas.bbox(status)[1] + 1)


class LayoutBQueryTest(ExpandedHostLineMixin, BCQueryMixin, unittest.TestCase):
    make = LayoutB

    def test_the_compact_strip_puts_the_entry_at_the_end_of_the_line_with_the_note_count(self):
        self.render(board_of(LAGGING))
        entry = self.canvas.bbox(self.entry())
        (count,) = [i for i in self.canvas.find_all() if self.canvas.type(i) == "text" and self.canvas.itemcget(i, "state") != "hidden"
                    and COUNT.match(self.canvas.itemcget(i, "text"))]
        box = self.canvas.bbox(count)
        self.assertGreater(entry[0], box[2])
        self.assertLess(abs((entry[1] + entry[3]) / 2 - (box[1] + box[3]) / 2), 2)

    def test_the_compact_status_is_not_counted_among_the_notes(self):
        plain = self.render(board_of(LAGGING))
        failed = self.render(board_of(LAGGING, last_failure=FAILURES[QueryFailure.TIMEOUT]))
        self.assertEqual([t for t in plain if COUNT.match(t)], [t for t in failed if COUNT.match(t)])

    def test_the_compact_strip_is_at_least_as_wide_as_a_card_when_it_carries_a_status_line(self):
        self.render(board_of(PENDING))
        narrow = int(float(self.canvas.cget("width")))
        self.render(board_of(PENDING, last_failure=FAILURES[QueryFailure.TIMEOUT]))
        self.assertGreater(int(float(self.canvas.cget("width"))), narrow)
        self.assertGreaterEqual(int(float(self.canvas.cget("width"))), self.layout._p.px("card_width"))


class LayoutCQueryTest(ExpandedHostLineMixin, BCQueryMixin, unittest.TestCase):
    make = LayoutC

    def test_the_compact_cell_puts_the_entry_on_the_note_count_line(self):
        self.render(board_of(LAGGING))
        entry = self.canvas.bbox(self.entry())
        (count,) = [i for i in self.canvas.find_withtag("wrapped-line") if COUNT.match(self.canvas.itemcget(i, "text").strip())]
        box = self.canvas.bbox(count)
        self.assertGreater(entry[0], box[2])
        self.assertLess(abs((entry[1] + entry[3]) / 2 - (box[1] + box[3]) / 2), 2)

    def test_the_compact_status_is_not_counted_among_the_notes(self):
        plain = self.render(board_of(LAGGING))
        failed = self.render(board_of(LAGGING, last_failure=FAILURES[QueryFailure.TIMEOUT]))
        self.assertEqual([t for t in plain if COUNT.match(t.strip())], [t for t in failed if COUNT.match(t.strip())])

    def test_the_status_lines_are_named_by_account_when_several_cells_share_a_row(self):
        shown = self.render(board_of(LAGGING, PERSONAL, last_failure=FAILURES[QueryFailure.TIMEOUT]), expanded=True)
        (line,) = [t for t in shown if "查詢失敗" in t]
        self.assertTrue(line.startswith("work："), line)


if __name__ == "__main__":
    unittest.main()
