"""縫 ②：版面 A。同一個 widget 連續渲染看板、在精簡與展開之間來回切換，Canvas 的 item 數不能累積。"""
import tkinter as tk
import unittest
from datetime import timedelta

from cc_quota_tracker import COMMAND
from cc_quota_tracker.board import (Board, BreakdownRow, Card, ExtraUsage, Limit, Money, ReadingState, Role, Severity,
                                    Spend, WeeklyBreakdown)
from cc_quota_tracker.fmt import absolute
from cc_quota_tracker.layout_a import EXPANDED_TAG, LayoutA
from cc_quota_tracker.tokens import THEMES
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

    def test_unmanaged_card_explains_how_to_manage(self):
        self.layout.render(BOARDS[2], "light")
        shown = "\n".join(self.visible_texts())
        self.assertIn(f"{COMMAND} add <帳號標籤>", shown)
        self.assertIn("「納管目前登入的帳號…」", shown)

    def visible_texts(self):
        return visible_texts(self.canvas)


def visible_texts(canvas):
    return [canvas.itemcget(i, "text") for i in canvas.find_all()
            if canvas.type(i) == "text" and canvas.itemcget(i, "state") != "hidden"]


FULL = Card("claude:work", Role.ACTIVE, ReadingState.HAS_READING, reading_age=timedelta(minutes=3), lagging=True,
            limits=(window("session", 42), window("weekly_all", 88, Severity.CRITICAL)),
            scoped_limits=(Limit("weekly_scoped", 30, Severity.NORMAL, NOW + timedelta(days=2), scope="Opus"),),
            other_limits=(Limit("nimbus_quill", 12, Severity.NORMAL, NOW + timedelta(hours=5)),
                          Limit("cobalt_x", None, Severity.NORMAL, None)),
            locked_reason="weekly_limit_reached",
            weekly_breakdown=WeeklyBreakdown(NOW - timedelta(days=3), NOW + timedelta(days=4),
                                             (BreakdownRow("claude_code", "Claude Code", 70),
                                              BreakdownRow("chat", "對話", 30))),
            extra_usage=ExtraUsage(Money(1250, "USD", 2), Money(5000, "USD", 2), 25),
            spend=Spend(Money(300, "USD", 2), Money(10000, "USD", 2), 3, Severity.NORMAL),
            snapshot_expires_at=NOW + timedelta(days=3), snapshot_expiring=True)
PERSONAL = Card("claude:personal", Role.STANDBY, ReadingState.HAS_READING, reading_age=timedelta(days=3),
                limits=(window("session", None, resets_at=None), window("weekly_all", 15)),
                snapshot_expires_at=NOW + timedelta(days=22))
LAB = Card("claude:lab", Role.STANDBY, ReadingState.NO_READING)
EXPANDED_BOARDS = [
    Board(cards=(FULL, PERSONAL, LAB), as_of=NOW),
    Board(cards=(Card(None, Role.UNMANAGED, ReadingState.NO_READING), PERSONAL), as_of=NOW),
    Board(cards=(ACTIVE, PERSONAL), as_of=NOW, schema_changed=True, last_reading_at=NOW - timedelta(hours=2)),
    Board(cards=(ACTIVE,), as_of=NOW),
] + BOARDS


class LayoutAExpandedTest(unittest.TestCase):
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

    def shown(self, board=EXPANDED_BOARDS[0]):
        self.layout.render(board, "light", expanded=True)
        return visible_texts(self.canvas)

    def item_with_text(self, text):
        return next(i for i in self.canvas.find_all() if self.canvas.type(i) == "text"
                    and text in self.canvas.itemcget(i, "text") and self.canvas.itemcget(i, "state") != "hidden")

    def test_one_card_per_account_with_role_chips(self):
        shown = self.shown()
        for label in ("work", "personal", "lab"):
            self.assertIn(label, shown)
        self.assertEqual(shown.count("使用中"), 1)
        self.assertEqual(shown.count("待命"), 2)

    def test_standby_shows_observed_age_and_no_lagging_note(self):
        shown = self.shown()
        self.assertIn("觀測 3 天前", shown)
        self.assertEqual(sum("有新對話，額度尚未更新" in t for t in shown), 1)  # 只有使用中帳號那一張

    def test_active_card_shows_expanded_only_data(self):
        shown = "\n".join(self.shown())
        for text in ("週限額（Opus）", "已過 42%", "本週用量去向", "Claude Code", "70%", "額外用量",
                     "12.50 USD / 50.00 USD", "花費", "3.00 USD / 100.00 USD"):
            self.assertIn(text, shown)

    def test_standby_card_does_not_get_expanded_only_data(self):
        standby_full = Card("claude:personal", Role.STANDBY, ReadingState.HAS_READING, reading_age=timedelta(days=1),
                            weekly_breakdown=FULL.weekly_breakdown, extra_usage=FULL.extra_usage)
        shown = "\n".join(self.shown(Board(cards=(ACTIVE, standby_full), as_of=NOW)))
        self.assertNotIn("本週用量去向", shown)
        self.assertNotIn("額外用量", shown)

    def test_missing_expanded_data_takes_no_space(self):
        shown = "\n".join(self.shown(EXPANDED_BOARDS[3]))
        for text in ("週限額", "已過", "本週用量去向", "額外用量", "花費", "其他限額"):
            self.assertNotIn(text, shown)

    def test_other_limits_are_folded_and_shown_under_raw_names(self):
        shown = self.shown()
        self.assertIn("▸ 其他限額（2）", shown)
        self.assertNotIn("nimbus_quill", shown)
        self.layout.toggle_other_limits()
        shown = visible_texts(self.canvas)
        self.assertIn("▾ 其他限額（2）", shown)
        self.assertIn("nimbus_quill", shown)
        self.assertIn("cobalt_x", shown)

    def test_locked_reason_is_red(self):
        self.shown()
        self.assertEqual(self.canvas.itemcget(self.item_with_text("weekly_limit_reached"), "fill"),
                         THEMES["light"]["critical"])

    def test_expiry_warning_has_a_dot_and_the_remedy(self):
        self.shown()
        note = self.item_with_text("後到期")
        self.assertIn(f"{COMMAND} add work", self.canvas.itemcget(note, "text"))
        dots = [i for i in self.canvas.find_all() if self.canvas.type(i) == "oval"
                and self.canvas.itemcget(i, "state") != "hidden"
                and self.canvas.itemcget(i, "fill") == THEMES["light"]["warning"]]
        self.assertTrue(dots)

    def test_unmanaged_card_explains_how_to_manage(self):
        shown = "\n".join(self.shown(EXPANDED_BOARDS[1]))
        self.assertIn(f"{COMMAND} add <帳號標籤>", shown)
        self.assertIn("「納管目前登入的帳號…」", shown)

    def test_schema_change_banner_shows_the_last_reading_time(self):
        shown = "\n".join(self.shown(EXPANDED_BOARDS[2]))
        self.assertIn("結構已變更", shown)
        self.assertIn(absolute(NOW - timedelta(hours=2), NOW), shown)

    def test_banner_names_invalid_settings_fields(self):
        shown = "\n".join(self.shown(Board(cards=(ACTIVE,), as_of=NOW, invalid_settings=("mode", "opacity"))))
        self.assertIn("mode、opacity", shown)

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
            if i % 7 == 0:
                self.layout.toggle_other_limits()
                self.layout.toggle_other_limits()  # 摺疊區回到原狀，item 數也要回到原狀
                counts[key].add(self.items())
        for key, seen in counts.items():
            self.assertEqual(len(seen), 1, key)

    def test_destroy_after_expanded_removes_every_item(self):
        self.shown()
        self.layout.toggle_other_limits()
        self.layout.destroy()
        self.assertEqual(self.items(), 0)


if __name__ == "__main__":
    unittest.main()
