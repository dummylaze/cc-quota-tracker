"""縫 ②：版面 A 精簡模式。同一個 widget 連續渲染看板，Canvas 的 item 數不能累積。"""
import tkinter as tk
import unittest
from datetime import timedelta

from cc_quota_tracker.board import Board, Card, Limit, ReadingState, Role, Severity
from cc_quota_tracker.layout_a import LayoutA
from tests.fakehome import NOW


def window(kind, percent, severity=Severity.NORMAL, resets_at=NOW + timedelta(hours=2), reset=False):
    return Limit(kind, percent, severity, resets_at, reset=reset)


def board(card):
    return Board(cards=(card,), as_of=NOW)


ACTIVE = Card("claude:work", Role.ACTIVE, ReadingState.HAS_READING, reading_age=timedelta(minutes=3),
              limits=(window("session", 42), window("weekly_all", 88, Severity.CRITICAL)),
              snapshot_expires_at=NOW + timedelta(days=25))
# 每一種會讓畫面長得不一樣的看板：item 數在它們之間來回也不能變
BOARDS = [
    board(ACTIVE),
    board(Card("claude:work", Role.ACTIVE, ReadingState.PENDING, snapshot_expires_at=NOW + timedelta(days=3),
               snapshot_expiring=True)),
    board(Card(None, Role.UNMANAGED, ReadingState.NO_READING)),
    board(Card("claude:work", Role.ACTIVE, ReadingState.HAS_READING, reading_age=timedelta(hours=2),
               limits=(window("session", None, resets_at=None), window("weekly_all", None, resets_at=None, reset=True)),
               snapshot_invalid=True, snapshot_expires_at=NOW - timedelta(days=1), snapshot_expiring=True)),
    board(Card("claude:work", Role.ACTIVE, ReadingState.HAS_READING, reading_age=timedelta(0),
               limits=(window("weekly_all", 0, Severity.WARNING),))),
]


class LayoutACompactTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # 沒有顯示環境
            self.skipTest(f"Tk 無法啟動：{e}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.canvas = tk.Canvas(self.root)
        self.layout = LayoutA(self.canvas)

    def items(self):
        return len(self.canvas.find_all())

    def test_repeated_renders_do_not_add_items(self):
        self.layout.render(BOARDS[0], "light")
        first = self.items()
        for _ in range(20):
            self.layout.render(BOARDS[0], "light")
        self.assertEqual(self.items(), first)

    def test_item_count_returns_to_same_value_across_board_states_and_themes(self):
        counts = {}
        for i in range(30):
            b, theme = BOARDS[i % len(BOARDS)], ("light", "dark")[i % 2]
            self.layout.render(b, theme)
            counts.setdefault((i % len(BOARDS), theme), set()).add(self.items())
        for key, seen in counts.items():
            self.assertEqual(len(seen), 1, key)

    def test_theme_switch_only_changes_attributes(self):
        self.layout.render(BOARDS[0], "light")
        before = self.canvas.find_all()
        self.layout.render(BOARDS[0], "dark")
        self.assertEqual(self.canvas.find_all(), before)  # 同一批 item，沒有重建

    def test_no_open_window_is_not_shown_as_zero_percent(self):
        self.layout.render(BOARDS[3], "light")
        shown = self.visible_texts()
        self.assertIn("無計時中窗口", shown)
        self.assertIn("已重置，下次重置時間未知", shown)
        self.assertNotIn("0%", shown)

    def test_only_the_active_card_is_rendered(self):
        standby = Card("claude:personal", Role.STANDBY, ReadingState.HAS_READING, reading_age=timedelta(days=3),
                       limits=(window("session", 7),))
        self.layout.render(Board(cards=(ACTIVE, standby), as_of=NOW), "light")
        shown = self.visible_texts()
        self.assertIn("work", shown)
        self.assertNotIn("personal", shown)

    def test_bar_color_follows_severity(self):
        self.layout.render(BOARDS[0], "light")
        fills = {self.canvas.itemcget(i, "fill") for i in self.canvas.find_withtag("bar-fill")
                 if self.canvas.itemcget(i, "state") != "hidden"}
        from cc_quota_tracker.tokens import THEMES
        self.assertEqual(fills, {THEMES["light"]["normal"], THEMES["light"]["critical"]})

    def test_destroy_removes_every_item(self):
        self.layout.render(BOARDS[0], "light")
        self.layout.destroy()
        self.assertEqual(self.items(), 0)

    def visible_texts(self):
        return [self.canvas.itemcget(i, "text") for i in self.canvas.find_all()
                if self.canvas.type(i) == "text" and self.canvas.itemcget(i, "state") != "hidden"]


if __name__ == "__main__":
    unittest.main()
