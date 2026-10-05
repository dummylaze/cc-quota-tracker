"""僅監看帳號的卡片：三種版面都在提示清單多一條原因與補救，讀數與到期倒數照常；補救只講一次，
既有的快照提示拿掉「請重新納管」，`list` 不再重複印重新登入的行（使用者 2026-10-06 確認）。"""
import tkinter as tk
import unittest
from dataclasses import replace
from datetime import timedelta

from cc_quota_tracker import COMMAND
from cc_quota_tracker.board import Board, Card, ReadingState, Role, Severity, WatchOnlyReason
from cc_quota_tracker.canvas_text import notes
from cc_quota_tracker.fmt import absolute
from cc_quota_tracker.layout_a import LayoutA
from cc_quota_tracker.layout_b import LayoutB
from cc_quota_tracker.layout_c import LayoutC
from cc_quota_tracker.render_text import render
from cc_quota_tracker.tokens import THEMES
from tests.fakehome import NOW
from tests.test_layout_a import ACTIVE, PERSONAL, visible_texts, window

LAYOUTS = (LayoutA, LayoutB, LayoutC)
REASONS_ZH = {WatchOnlyReason.EXPIRED: "已過期", WatchOnlyReason.INVALID: "已失效",
              WatchOnlyReason.NO_ACCOUNT_INFO: "沒有帳號資訊"}  # 寫回失敗的兩種另見 test_writeback_retry
REASONS_EN = {WatchOnlyReason.EXPIRED: "expired", WatchOnlyReason.INVALID: "no longer valid",
              WatchOnlyReason.NO_ACCOUNT_INFO: "no account info"}
EXPIRED_AT = NOW - timedelta(days=1)


def watch_only(reason, role=Role.STANDBY):
    """依原因組出一張和核心產出一致的僅監看帳號卡片（有讀數）。"""
    card = Card("claude:work", role, ReadingState.HAS_READING, reading_age=timedelta(hours=1),
                limits=(window("session", 42), window("weekly_all", 18)),
                snapshot_expires_at=NOW + timedelta(days=20), watch_only_reason=reason)
    if reason is WatchOnlyReason.EXPIRED:
        card = replace(card, snapshot_expires_at=EXPIRED_AT, snapshot_expiring=True)
    if reason is WatchOnlyReason.INVALID:
        card = replace(card, snapshot_invalid=True)
    return card


def zh_note(reason):
    return f"僅監看帳號（{REASONS_ZH[reason]}）：在 Claude Code 登入這個帳號後重新納管"


def en_note(reason):
    return f"Watch-only account ({REASONS_EN[reason]}): sign in to this account in Claude Code, then manage it again"


def board(*cards):
    return Board(cards=cards, as_of=NOW)


class CardNotesTest(unittest.TestCase):
    def texts(self, card, lang="zh-TW", expiry_info=True):
        return [t for t, _, _ in notes(card, board(card), lang, expiry_info)]

    def test_each_reason_has_its_note_in_both_languages(self):
        for reason in REASONS_ZH:
            with self.subTest(reason=reason):
                self.assertIn(zh_note(reason), self.texts(watch_only(reason)))
                self.assertIn(en_note(reason), self.texts(watch_only(reason), "en"))

    def test_expired_and_invalid_are_critical_and_no_account_info_is_neutral(self):
        expected = {WatchOnlyReason.EXPIRED: ("critical", "critical"), WatchOnlyReason.INVALID: ("critical", "critical"),
                    WatchOnlyReason.NO_ACCOUNT_INFO: ("sub", "fg")}
        for reason, colors in expected.items():
            with self.subTest(reason=reason):
                card = watch_only(reason)
                note = next(n for n in notes(card, board(card), "zh-TW") if n[0] == zh_note(reason))
                self.assertEqual(note[1:], colors)

    def test_remedy_is_said_only_once(self):
        for reason in REASONS_ZH:
            for expiring in (False, True):
                with self.subTest(reason=reason, expiring=expiring):
                    card = watch_only(reason)
                    card = replace(card, snapshot_expiring=card.snapshot_expiring or expiring)
                    self.assertEqual(sum("重新納管" in t for t in self.texts(card)), 1)

    def test_expired_card_keeps_the_expiry_time_without_the_remedy(self):
        self.assertIn(f"憑證快照已過期（{absolute(EXPIRED_AT, NOW)}）", self.texts(watch_only(WatchOnlyReason.EXPIRED)))

    def test_invalid_card_drops_the_old_invalid_note_and_keeps_the_countdown(self):
        shown = self.texts(watch_only(WatchOnlyReason.INVALID))
        self.assertNotIn("憑證快照已失效，請重新納管", shown)
        self.assertTrue([t for t in shown if t.startswith("憑證快照 20天0小時後到期")])

    def test_expiring_watch_only_card_shows_the_countdown_as_plain_information(self):
        card = replace(watch_only(WatchOnlyReason.NO_ACCOUNT_INFO), snapshot_expires_at=NOW + timedelta(days=3),
                       snapshot_expiring=True)
        snapshot = next(n for n in notes(card, board(card), "zh-TW") if n[0].startswith("憑證快照"))
        self.assertEqual(snapshot[1:], ("sub", "fg"))

    def test_table_layout_without_expiry_info_shows_only_the_watch_only_note(self):
        for reason in REASONS_ZH:
            with self.subTest(reason=reason):
                shown = self.texts(watch_only(reason), expiry_info=False)
                self.assertIn(zh_note(reason), shown)
                self.assertFalse([t for t in shown if "憑證快照" in t])

    def test_managed_cards_are_unchanged(self):
        expiring = replace(ACTIVE, switchable=True, snapshot_expires_at=NOW + timedelta(days=3), snapshot_expiring=True)
        self.assertTrue([t for t in self.texts(expiring) if t.endswith("請重新納管")])
        self.assertFalse([t for t in self.texts(replace(ACTIVE, switchable=True)) if "僅監看" in t])

    def test_unwatched_card_has_no_watch_only_note(self):
        card = Card(None, Role.UNWATCHED, ReadingState.NO_READING)
        self.assertFalse([t for t in self.texts(card) if "僅監看" in t])


class EveryLayoutTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # 沒有顯示環境
            self.skipTest(f"Tk 無法啟動：{e}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def shown(self, make, card, lang):
        canvas = tk.Canvas(self.root)
        layout = make(canvas)
        layout.render(board(replace(ACTIVE, switchable=True), card), "light", True, lang)
        shown = "\n".join(visible_texts(canvas))
        layout.destroy()
        return shown

    def test_every_layout_shows_the_reason_in_both_languages(self):
        for make in LAYOUTS:
            for reason in REASONS_ZH:
                with self.subTest(layout=make.__name__, reason=reason):
                    self.assertIn(zh_note(reason), self.shown(make, watch_only(reason), "zh-TW"))
                    self.assertIn(en_note(reason), self.shown(make, watch_only(reason), "en"))

    def test_readings_and_expiry_countdown_still_show(self):
        card = watch_only(WatchOnlyReason.NO_ACCOUNT_INFO)
        for make in LAYOUTS:
            with self.subTest(layout=make.__name__):
                shown = self.shown(make, card, "zh-TW")
                self.assertIn("42%", shown)
                self.assertIn("18%", shown)
                self.assertIn("20天0小時", shown)

    def test_compact_layouts_count_the_note_with_its_dot_color(self):
        """表格與環形的精簡模式把提示收成數量，色點取最嚴重的那條；全文展開才看得到。"""
        critical = THEMES["light"]["critical"]
        for make in (LayoutB, LayoutC):
            for reason, has_critical in ((WatchOnlyReason.INVALID, True), (WatchOnlyReason.NO_ACCOUNT_INFO, False)):
                with self.subTest(layout=make.__name__, reason=reason):
                    canvas = tk.Canvas(self.root)
                    layout = make(canvas)
                    layout.render(board(watch_only(reason, Role.ACTIVE)), "light", False, "zh-TW")
                    shown = "\n".join(visible_texts(canvas))
                    self.assertIn("則提示", shown)
                    self.assertNotIn("僅監看帳號", shown)
                    fills = [i for i in canvas.find_all() if canvas.type(i) != "text"
                             and canvas.itemcget(i, "state") != "hidden" and canvas.itemcget(i, "fill") == critical]
                    self.assertEqual(bool(fills), has_critical)
                    layout.destroy()

    def test_managed_standby_card_shows_no_watch_only_note(self):
        for make in LAYOUTS:
            with self.subTest(layout=make.__name__):
                self.assertNotIn("僅監看", self.shown(make, replace(PERSONAL, switchable=True), "zh-TW"))


class ListDedupTest(unittest.TestCase):
    def test_expired_watch_only_account_prints_the_remedy_once_and_keeps_the_expiry_line(self):
        text = render(board(watch_only(WatchOnlyReason.EXPIRED)))
        self.assertEqual(text.count(f"{COMMAND} add work"), 1)
        self.assertNotIn("重新登入這個帳號，再執行", text)
        self.assertIn(f"憑證快照已過期（{absolute(EXPIRED_AT, NOW)}）", text)

    def test_invalid_active_watch_only_account_does_not_repeat_the_remedy(self):
        text = render(board(watch_only(WatchOnlyReason.INVALID, Role.ACTIVE)))
        self.assertEqual(text.count(f"{COMMAND} add work"), 1)
        self.assertNotIn("Claude Code 目前登入的就是這個帳號", text)

    def test_managed_expiring_account_still_prints_the_relogin_line(self):
        card = replace(ACTIVE, switchable=True, snapshot_expires_at=NOW + timedelta(days=3), snapshot_expiring=True)
        self.assertIn("重新登入這個帳號，再執行", render(board(card)))


if __name__ == "__main__":
    unittest.main()
