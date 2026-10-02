"""縫 ②：版面 A 的「更新」入口與查詢狀態。入口、查詢中、冷卻、失敗原因的 Canvas item 與既有文字的外框不重疊，
提示維持單行；入口只在落後或讀數待更新的使用中帳號卡片出現，進行中與冷卻中不可點。"""
import re
import tkinter as tk
import tkinter.font as tkfont
import unittest
from dataclasses import replace

from cc_quota_tracker.board import (Board, Card, QueryFailure, QueryStatus, ReadingState, Role, UsageQueryResult)
from cc_quota_tracker.layout_a import CLICKABLE_TAG, LayoutA
from cc_quota_tracker.tokens import THEMES
from tests.fakehome import NOW
from tests.test_layout_a import ACTIVE, EXPANDED_BOARDS, FULL, LAB, PERSONAL, visible_lines, visible_texts

HAN = re.compile(r"[⺀-鿿＀-￯]")
LAGGING = replace(ACTIVE, lagging=True)
PENDING = Card("claude:work", Role.ACTIVE, ReadingState.PENDING)
FAILURES = {
    QueryFailure.COMMAND_NOT_FOUND: UsageQueryResult(QueryFailure.COMMAND_NOT_FOUND),
    QueryFailure.TIMEOUT: UsageQueryResult(QueryFailure.TIMEOUT),
    QueryFailure.REPORTED_ERROR: UsageQueryResult(QueryFailure.REPORTED_ERROR, message="Not logged in"),
    QueryFailure.NOT_WRITTEN: UsageQueryResult(QueryFailure.NOT_WRITTEN),
}
ENTRY_TEXTS = {"更新", "查詢中…", "Update", "Updating…"}


def board_of(*cards, **status):
    return Board(cards=cards, as_of=NOW, usage_query=QueryStatus(**status))


class QueryLayoutTestCase(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # 沒有顯示環境
            self.skipTest(f"Tk 無法啟動：{e}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.canvas = tk.Canvas(self.root)
        self.calls = []
        self.layout = LayoutA(self.canvas, on_query=lambda: self.calls.append("query"))

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


class EntryTest(QueryLayoutTestCase):
    def test_a_lagging_active_card_offers_an_update_entry_in_both_languages(self):
        self.assertIn("更新", self.render(board_of(LAGGING)))
        self.assertEqual(self.canvas.itemcget(self.entry(), "text"), "更新")
        self.assertIn("有新對話，額度尚未更新", visible_texts(self.canvas))  # 提示本身不變
        self.render(board_of(LAGGING), "en")
        self.assertEqual(self.canvas.itemcget(self.entry(), "text"), "Update")

    def test_a_pending_active_card_offers_it_with_a_short_hint(self):
        shown = self.render(board_of(PENDING))
        self.assertEqual(self.canvas.itemcget(self.entry(), "text"), "更新")
        self.assertIn("讀數待更新", shown)
        self.assertFalse([t for t in shown if "Claude Code 更新額度快取後就會出現" in t])
        shown = self.render(board_of(PENDING), "en")
        self.assertIn("Reading pending", shown)

    def test_no_entry_when_the_reading_is_neither_lagging_nor_pending(self):
        for card in (ACTIVE, LAB, Card(None, Role.UNMANAGED, ReadingState.NO_READING)):
            self.render(board_of(card))
            self.assertEqual(self.entries(), [], card)

    def test_standby_cards_never_get_an_entry(self):
        standby = replace(PERSONAL, lagging=True)
        self.render(board_of(LAGGING, standby, replace(LAB, reading_state=ReadingState.PENDING)), expanded=True)
        self.assertEqual(len(self.entries()), 1)

    def test_idle_entry_is_clickable_and_underlined(self):
        self.render(board_of(LAGGING))
        item = self.entry()
        self.assertTrue(self.clickable(item))
        self.assertTrue(tkfont.nametofont(self.canvas.itemcget(item, "font")).actual("underline"))
        self.assertEqual(self.canvas.itemcget(item, "fill"), THEMES["light"]["fg"])

    def test_in_progress_shows_a_busy_label_that_cannot_be_clicked(self):
        for card in (LAGGING, PENDING):
            self.render(board_of(card, in_progress=True))
            item = self.entry()
            self.assertEqual(self.canvas.itemcget(item, "text"), "查詢中…")
            self.assertFalse(self.clickable(item))
        self.render(board_of(LAGGING, in_progress=True), "en")
        self.assertEqual(self.canvas.itemcget(self.entry(), "text"), "Updating…")

    def test_cooldown_keeps_the_label_but_greys_it_out_and_cannot_be_clicked(self):
        self.render(board_of(LAGGING, cooling_down=True))
        item = self.entry()
        self.assertEqual(self.canvas.itemcget(item, "text"), "更新")
        self.assertFalse(self.clickable(item))
        self.assertFalse(tkfont.nametofont(self.canvas.itemcget(item, "font")).actual("underline"))
        self.assertEqual(self.canvas.itemcget(item, "fill"), THEMES["light"]["sub"])

    def test_the_entry_becomes_clickable_again_by_rendering_an_idle_board(self):
        self.render(board_of(LAGGING, cooling_down=True))
        self.render(board_of(LAGGING))
        self.assertTrue(self.clickable(self.entry()))

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

    def test_clicking_an_idle_entry_calls_back_once(self):
        self.render(board_of(LAGGING))
        self.click(self.entry())
        self.root.update()
        self.assertEqual(self.calls, ["query"])

    def test_clicking_a_busy_or_cooling_entry_does_nothing(self):
        for status in ({"in_progress": True}, {"cooling_down": True}):
            self.render(board_of(LAGGING, **status))
            self.click(self.entry())
        self.assertEqual(self.calls, [])

    def test_the_entry_is_the_only_new_clickable_item(self):
        self.render(board_of(FULL), expanded=True)
        clickable = [i for i in self.canvas.find_withtag(CLICKABLE_TAG) if self.canvas.itemcget(i, "state") != "hidden"]
        texts = sorted(self.canvas.itemcget(i, "text") for i in clickable)
        self.assertEqual(len(texts), 2, texts)  # 「其他限額」摺疊標題與「更新」
        self.assertIn("更新", texts)


class StatusTest(QueryLayoutTestCase):
    def test_each_failure_reason_reads_differently_and_points_to_usage(self):
        for lang, tail in (("zh-TW", "在 Claude Code 執行 /usage"), ("en", "Try /usage in Claude Code instead")):
            seen = {}
            for failure, result in FAILURES.items():
                shown = self.render(board_of(LAGGING, last_failure=result), lang)
                (line,) = [t for t in shown if t.startswith(("查詢失敗", "Update failed"))]
                self.assertIn(tail, line)
                seen[failure] = line
            self.assertEqual(len(set(seen.values())), 4, lang)
            self.assertIn("claude", seen[QueryFailure.COMMAND_NOT_FOUND])
            self.assertIn("Not logged in", seen[QueryFailure.REPORTED_ERROR])

    def test_the_zh_fallback_has_no_leading_could_word(self):
        shown = "\n".join(self.render(board_of(LAGGING, last_failure=FAILURES[QueryFailure.TIMEOUT])))
        self.assertIn("在 Claude Code 執行 /usage", shown)
        self.assertNotIn("可改", shown)

    def test_a_long_raw_message_is_cut_at_sixty_characters(self):
        message = "x" * 61
        shown = self.render(board_of(LAGGING, last_failure=UsageQueryResult(QueryFailure.REPORTED_ERROR, message=message)))
        line = next(t for t in shown if "查詢失敗" in t)
        self.assertIn("x" * 60 + "…", line)
        self.assertNotIn("x" * 61, line)
        shown = self.render(board_of(LAGGING, last_failure=UsageQueryResult(QueryFailure.REPORTED_ERROR, message="y" * 60)))
        self.assertIn("y" * 60 + "」", next(t for t in shown if "查詢失敗" in t))  # 剛好 60 字不截斷

    def test_a_multiline_raw_message_is_folded_into_one_line(self):
        result = UsageQueryResult(QueryFailure.REPORTED_ERROR, message="first\n  second")
        line = next(t for t in self.render(board_of(LAGGING, last_failure=result)) if "查詢失敗" in t)
        self.assertIn("first second", line)

    def test_a_reported_error_without_a_message_still_reads_as_a_reported_error(self):
        result = UsageQueryResult(QueryFailure.REPORTED_ERROR)
        line = next(t for t in self.render(board_of(LAGGING, last_failure=result)) if "查詢失敗" in t)
        self.assertIn("Claude Code 回報錯誤", line)

    def test_the_failure_shows_on_a_card_that_is_not_lagging_too(self):
        shown = self.render(board_of(ACTIVE, last_failure=FAILURES[QueryFailure.TIMEOUT]))
        self.assertTrue([t for t in shown if "查詢失敗" in t])
        self.assertEqual(self.entries(), [])  # 沒落後就沒有入口，失敗原因仍然看得到

    def test_the_failure_stays_while_the_next_query_runs_or_cools_down(self):
        for status in ({"in_progress": True}, {"cooling_down": True}):
            shown = self.render(board_of(LAGGING, last_failure=FAILURES[QueryFailure.TIMEOUT], **status))
            self.assertTrue([t for t in shown if "查詢失敗" in t], status)

    def test_no_failure_line_without_a_failure_and_the_reading_still_shows(self):
        shown = self.render(board_of(LAGGING))
        self.assertFalse([t for t in shown if "查詢失敗" in t])
        failed = self.render(board_of(LAGGING, last_failure=FAILURES[QueryFailure.TIMEOUT]))
        for text in ("work", "工作階段窗口", "週窗口", "42%", "88%"):
            self.assertIn(text, failed)  # 失敗不清空原本的讀數

    def test_a_query_with_nothing_lagging_shows_a_busy_line_instead_of_an_entry(self):
        shown = self.render(board_of(ACTIVE, in_progress=True))
        self.assertIn("查詢中…", shown)
        self.assertNotIn("更新", shown)  # 這一行是提示，不是入口
        self.assertFalse([i for i in self.canvas.find_withtag(CLICKABLE_TAG) if self.canvas.itemcget(i, "state") != "hidden"])
        self.assertNotIn("查詢中…", self.render(board_of(ACTIVE, cooling_down=True)))
        self.assertNotIn("查詢中…", self.render(board_of(ACTIVE)))

    def test_only_the_non_standby_card_carries_the_status(self):
        shown = self.render(board_of(LAGGING, PERSONAL, last_failure=FAILURES[QueryFailure.TIMEOUT]), expanded=True)
        self.assertEqual(len([t for t in shown if "查詢失敗" in t]), 1)

    def test_english_leaves_no_chinese_on_screen(self):
        for card in (LAGGING, PENDING, ACTIVE):
            for status in ({}, {"in_progress": True}, {"cooling_down": True}):
                for failure in (None, *FAILURES.values()):
                    for shown in self.render(board_of(card, last_failure=failure, **status), "en"):
                        self.assertIsNone(HAN.search(shown), (card.reading_state, status, failure, shown))

    def test_switching_language_only_changes_text_on_the_existing_items(self):
        board = board_of(LAGGING, last_failure=FAILURES[QueryFailure.TIMEOUT], cooling_down=True)
        self.render(board)
        items = tuple(i for i in self.canvas.find_all() if "wrapped-line" not in self.canvas.gettags(i))
        self.render(board, "en")
        self.assertEqual(tuple(i for i in self.canvas.find_all() if "wrapped-line" not in self.canvas.gettags(i)), items)


def _boxes(canvas):
    """畫面上每個文字 item 的外框（含逐行文字的每一行）。"""
    return [(i, canvas.bbox(i)) for i in canvas.find_all()
            if canvas.type(i) == "text" and canvas.itemcget(i, "state") != "hidden"]


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class GeometryTest(QueryLayoutTestCase):
    def states(self):
        failure = FAILURES[QueryFailure.REPORTED_ERROR]
        long_failure = UsageQueryResult(QueryFailure.REPORTED_ERROR, message="a very long message " * 5)
        for card in (LAGGING, PENDING, ACTIVE, FULL):
            for status in ({}, {"in_progress": True}, {"cooling_down": True}, {"last_failure": failure},
                           {"in_progress": True, "last_failure": long_failure}):
                yield card, status

    def test_no_text_overlaps_another_in_either_language_and_mode(self):
        for lang in ("zh-TW", "en"):
            for expanded in (False, True):
                for card, status in self.states():
                    self.render(board_of(card, PERSONAL, **status), lang, expanded)
                    boxes = _boxes(self.canvas)
                    for n, (i, a) in enumerate(boxes):
                        for j, b in boxes[n + 1:]:
                            self.assertFalse(_overlap(a, b), (lang, expanded, card.reading_state, status,
                                                              self.canvas.itemcget(i, "text"), self.canvas.itemcget(j, "text")))

    def test_the_hint_next_to_the_entry_stays_on_one_line(self):
        hints = {"zh-TW": ("有新對話，額度尚未更新", "讀數待更新"), "en": ("New activity; usage not updated", "Reading pending")}
        for lang, (lagging, pending) in hints.items():
            for card, hint in ((LAGGING, lagging), (PENDING, pending)):
                for status in ({}, {"in_progress": True}, {"cooling_down": True}):
                    self.render(board_of(card, **status), lang)
                    blocks = [lines for lines in visible_lines(self.canvas) if lines[0][1].strip() == hint]
                    self.assertEqual(len(blocks), 1, (lang, hint, status))
                    self.assertEqual(len(blocks[0]), 1, (lang, hint, status))

    def test_the_entry_sits_on_the_hints_line_at_the_right_edge_of_the_card(self):
        self.render(board_of(LAGGING))
        entry = self.canvas.bbox(self.entry())
        text_box = {self.canvas.itemcget(i, "text").strip(): self.canvas.bbox(i) for i in self.canvas.find_all()
                    if self.canvas.type(i) == "text" and self.canvas.itemcget(i, "state") != "hidden"}
        hint, age = text_box["有新對話，額度尚未更新"], text_box["讀數 3 分鐘前"]
        self.assertGreater(entry[0], hint[2])
        self.assertLess(abs((entry[1] + entry[3]) / 2 - (hint[1] + hint[3]) / 2), 2)
        self.assertLess(abs(entry[2] - age[2]), 2)  # 右緣與標題列的讀數年齡對齊

    def test_item_count_does_not_depend_on_the_language(self):
        fixed = {}
        for lang in ("zh-TW", "en"):
            for k, (card, status) in enumerate(self.states()):
                self.render(board_of(card, PERSONAL, **status), lang, True)
                fixed.setdefault(k, set()).add(len([i for i in self.canvas.find_all()
                                                    if "wrapped-line" not in self.canvas.gettags(i)]))
        for k, seen in fixed.items():
            self.assertEqual(len(seen), 1, k)  # 折行文字的行數隨語系而變，其餘 item 不變

    def test_destroy_removes_the_entry_and_status_items(self):
        self.render(board_of(LAGGING, last_failure=FAILURES[QueryFailure.TIMEOUT]), expanded=True)
        self.layout.destroy()
        self.assertEqual(len(self.canvas.find_all()), 0)


if __name__ == "__main__":
    unittest.main()
