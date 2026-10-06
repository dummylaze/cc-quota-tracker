"""視窗接線：子選單最後一列的「還原上一次切換」，與切換驗證失敗時附還原選項的提示。視窗接真的核心與假 claude。"""
import threading
import time
import unittest
from dataclasses import replace
from datetime import timedelta
from unittest import mock

from cc_quota_tracker.board import Board, QueryFailure, SwitchOutcome, SwitchResult, SwitchStep, UsageQueryResult
from cc_quota_tracker.fmt import restore_confirmation
from tests.fakehome import NOW
from tests.test_credential_sync import WORK
from tests.test_widget_switch import OVERLAY, PLACEHOLDER, TITLE, WidgetSwitchTestCase

RESTORE = "還原上一次切換"
RESTORE_CONFIRM = "還原上一次切換？"


class RestoreMenuTest(WidgetSwitchTestCase):
    def switch_away(self):
        """從 work 切到 home：切換前憑證是 work 那一次登入。"""
        self.core.switch("home")
        self.widget.refresh()

    def test_the_last_row_is_restore_and_greyed_when_there_is_nothing_to_restore(self):
        self.assertEqual(self.restore_row(), (RESTORE, False))
        self.assertEqual(self.rows(), [("home", True)])

    def test_it_can_be_chosen_once_a_switch_left_a_pre_switch_credential(self):
        self.switch_away()
        self.assertEqual(self.restore_row(), (RESTORE, True))
        self.assertEqual(self.rows(), [("work", True)])

    def test_it_is_greyed_again_once_the_pre_switch_credential_has_expired(self):
        self.switch_away()
        self.clock.now = WORK + timedelta(seconds=1)
        self.widget.refresh()
        self.assertEqual(self.restore_row(), (RESTORE, False))

    def test_it_is_greyed_when_the_pre_switch_credential_is_unusable(self):
        self.switch_away()
        self.pre_switch().write_text("{not json", encoding="utf-8")
        self.widget.refresh()
        self.assertEqual(self.restore_row(), (RESTORE, False))

    def test_it_stays_below_the_placeholder_when_no_account_can_be_chosen(self):
        self.core.remove("home")
        self.widget.refresh()
        self.assertEqual(self.all_rows(), [(PLACEHOLDER, False), (RESTORE, False)])

    def test_it_follows_the_language(self):
        self.switch_away()
        self.widget.set_preference("language", "en")
        self.assertEqual(self.restore_row("Switch account"), ("Restore previous switch", True))

    def test_every_layout_shares_it(self):
        self.switch_away()
        for layout in ("cards", "table", "ring"):
            self.widget.set_preference("layout", layout)
            self.assertEqual(self.restore_row(), (RESTORE, True), layout)

    def test_it_is_greyed_with_the_whole_submenu_while_a_query_is_in_progress(self):
        self.switch_away()
        self.with_query_status(in_progress=True)
        self.assertEqual(self.widget._menu.entrycget(self.menu_index(TITLE), "state"), "disabled")


class RestoreRunTest(WidgetSwitchTestCase):
    def switch_away(self):
        self.core.switch("home")
        self.widget.refresh()

    def message(self, answer=True):
        ask = self.confirm(answer)
        self.choose(RESTORE)
        self.finish()
        ask.assert_called_once()
        self.assertEqual(ask.call_args.args[0], TITLE)
        return ask.call_args.args[1]

    def test_the_confirmation_asks_one_question_and_the_consequence_and_the_pre_switch_expiry(self):
        self.switch_away()
        paragraphs = self.message().split("\n\n")
        self.assertEqual(paragraphs[0], RESTORE_CONFIRM)
        self.assertEqual(paragraphs[1], "會用切換前的憑證與帳號資訊換回去；當前憑證會存成新的切換前憑證，所以還能再還原回來。")
        self.assertRegex(paragraphs[2], r"^切換前憑證 \d+天\d+小時後到期（\d\d-\d\d \d\d:\d\d）$")
        self.assertEqual(len(paragraphs), 3)

    def test_the_confirmation_shows_no_usage_numbers(self):
        self.switch_away()
        self.assertNotRegex(self.message(), r"%|額度|讀數")

    def test_the_confirmation_follows_the_language(self):
        self.switch_away()
        self.widget.set_preference("language", "en")
        ask = self.confirm()
        self.choose("Restore previous switch", "Switch account")
        self.finish()
        self.assertEqual(ask.call_args.args[0], "Switch account")
        self.assertTrue(ask.call_args.args[1].startswith("Restore the previous switch?\n\n"))

    def test_declining_changes_nothing(self):
        self.switch_away()
        before = self.untouched()
        self.message(answer=False)
        self.assertFalse(self.widget.switching)
        self.assertEqual(self.untouched(), before)

    def test_confirming_restores_in_the_background_without_blocking_the_event_loop(self):
        self.switch_away()
        release, real = threading.Event(), self.core.restore_previous
        self.addCleanup(release.set)

        def slow(on_step=None):
            release.wait(10)
            return real()
        self.counting.restore_previous = slow
        self.confirm()
        before = self.untouched()
        self.choose(RESTORE)  # 還原卡住了，選單項照樣返回：事件迴圈沒有被擋住
        self.assertTrue(self.widget.switching)
        self.root.update()
        self.assertEqual(self.untouched(), before)
        release.set()
        self.finish()
        self.assertEqual(self.oauth_account()["accountUuid"], "acct-w")
        self.assertEqual(self.counting.core.poll().cards[0].account_key, "claude:work")
        self.assertEqual(self.rows(), [("home", True)])

    def test_restoring_covers_the_window_and_names_the_pre_switch_credential_in_the_write_step(self):
        self.switch_away()
        self.widget.set_preference("mode", "expanded")
        gate, real = threading.Semaphore(0), self.core.restore_previous

        def gated(on_step=None):
            on_step(SwitchStep.WRITE)
            gate.acquire(timeout=10)
            return real()
        self.counting.restore_previous = gated
        self.addCleanup(gate.release)
        self.confirm()
        self.choose(RESTORE)
        canvas = self.widget.canvas
        self.assertTrue(canvas.find_withtag(OVERLAY))

        def texts():
            return [canvas.itemcget(i, "text") for i in canvas.find_withtag(OVERLAY) if canvas.type(i) == "text"]
        deadline = time.monotonic() + 10
        while "寫入切換前的憑證…" not in texts():
            self.assertLess(time.monotonic(), deadline, "圖層沒有顯示步驟")
            self.root.update()
            time.sleep(0.02)
        gate.release()
        self.finish()
        self.assertEqual(canvas.find_withtag(OVERLAY), ())

    def test_a_refusal_shows_the_reason_and_writes_nothing(self):
        self.switch_away()
        self.confirm()
        errors = self.errors()
        self.pre_switch().write_text("{not json", encoding="utf-8")  # 看板還沒跟上：選單看起來能還原，核心重新判斷時不行
        before = self.untouched()
        self.choose(RESTORE)
        self.finish()
        errors.assert_called_once()
        self.assertEqual(errors.call_args.args[1], "沒有可還原的切換前憑證，沒有切換。")
        self.assertEqual(self.untouched(), before)

    def test_a_restore_that_stopped_halfway_is_reported(self):
        self.switch_away()
        self.confirm()
        errors = self.errors()
        self.counting.restore_previous = lambda on_step=None: SwitchResult(SwitchOutcome.WRITE_FAILED)
        self.choose(RESTORE)
        self.finish()
        self.assertEqual(errors.call_args.args[1],
                         "已寫入切換前的憑證，但沒能改寫 Claude Code 的帳號資訊，兩者目前不一致：請在 Claude Code 重新登入。")

    def test_an_exception_in_the_background_restore_is_reported_and_the_window_recovers(self):
        self.switch_away()
        self.confirm()
        errors = self.errors()

        def boom(on_step=None):
            raise RuntimeError("壞了")
        self.counting.restore_previous = boom
        self.choose(RESTORE)
        self.finish()
        errors.assert_called_once()
        self.assertFalse(self.widget.switching)

    def test_choosing_while_a_query_is_in_progress_does_nothing(self):
        self.switch_away()
        ask = self.confirm()
        self.with_query_status(in_progress=True)
        self.widget.restore_previous()
        self.assertFalse(ask.called or self.widget.switching)

    def test_a_restore_whose_own_verification_fails_is_reported_without_offering_another_restore(self):
        self.switch_away()
        ask = self.confirm()
        errors = self.errors()
        self.queries_write_nothing()
        self.choose(RESTORE)
        self.finish()
        ask.assert_called_once()  # 只有還原前那一次確認：還原本身驗證失敗時再問「要還原嗎」只會繞回剛離開的帳號
        errors.assert_called_once()
        self.assertTrue(errors.call_args.args[1].startswith("已還原上一次切換，但還原後的帳號查詢額度失敗"))


class VerifyFailedPromptTest(WidgetSwitchTestCase):
    def ask(self, *answers):
        """第一次是切換前的確認，之後是驗證失敗的提示；回傳替身。"""
        patcher = mock.patch("cc_quota_tracker.widget.messagebox.askyesno", side_effect=list(answers))
        self.addCleanup(patcher.stop)
        return patcher.start()

    def failing_switch(self, *answers):
        """真的切換、查詢新帳號失敗：切換前憑證已經存好，核心的結果是驗證失敗。"""
        self.queries_write_nothing()
        ask = self.ask(*answers)
        self.errors()
        self.choose("home")
        self.finish()
        return ask

    def test_a_failed_verification_asks_whether_to_restore_with_the_reason(self):
        ask = self.failing_switch(True, False)
        self.assertEqual(ask.call_count, 2)
        title, message = ask.call_args_list[1].args[:2]
        self.assertEqual(title, TITLE)
        head, ask_line = message.rsplit("\n\n", 1)
        self.assertTrue(head.startswith("已切換到「home」，但替它查詢額度失敗，沒能確認切換有生效："), head)
        self.assertEqual(ask_line, "要還原上一次切換嗎？")

    def test_the_prompt_comes_after_the_board_shows_the_new_account(self):
        shown = []
        self.queries_write_nothing()

        def ask(*args, **kw):
            shown.append(self.counting.core.poll().cards[0].account_key if shown else None)
            return False if shown[1:] else True
        patcher = mock.patch("cc_quota_tracker.widget.messagebox.askyesno", side_effect=ask)
        self.addCleanup(patcher.stop)
        patcher.start()
        self.errors()
        self.choose("home")
        self.finish()
        self.assertEqual(shown, [None, "claude:home"])

    def test_declining_keeps_the_new_account(self):
        self.failing_switch(True, False)
        self.assertEqual(self.oauth_account()["accountUuid"], "acct-h")
        self.assertFalse(self.widget.switching)

    def test_accepting_restores_straight_away_without_another_confirmation(self):
        before = self.untouched()[0]
        ask = self.failing_switch(True, True)
        self.assertEqual(ask.call_count, 2)  # 切換前一次、驗證失敗提示一次；按下「是」之後不再跳確認
        self.assertEqual(self.oauth_account()["accountUuid"], "acct-w")
        self.assertEqual(self.current().read_bytes(), before)
        self.assertFalse(self.widget.switching)

    def test_accepting_while_a_query_has_started_meanwhile_says_nothing_was_restored(self):
        """提示開著時 Tk 的排程照跑，自動查詢可能已啟動：還原被擋下要說出來，不能讓按了「是」的人以為已經還原。"""
        self.queries_write_nothing()
        calls = []

        def ask(*args, **kw):
            calls.append(args)
            if len(calls) == 2:  # 驗證失敗提示開著的這段時間，看板變成查詢進行中
                board = self.widget._board
                self.widget._board = replace(board, usage_query=replace(board.usage_query, in_progress=True))
            return True
        patcher = mock.patch("cc_quota_tracker.widget.messagebox.askyesno", side_effect=ask)
        self.addCleanup(patcher.stop)
        patcher.start()
        errors = self.errors()
        self.choose("home")
        self.finish()
        errors.assert_called_once()
        self.assertEqual(errors.call_args.args[1], "正在查詢額度，沒有還原；查完之後再從選單選「還原上一次切換」。")
        self.assertFalse(self.widget.switching)
        self.assertEqual(self.oauth_account()["accountUuid"], "acct-h")  # 還是在新帳號上

    def test_accepting_covers_the_window_like_any_switch(self):
        self.widget.set_preference("mode", "expanded")
        self.queries_write_nothing()
        release, real = threading.Event(), self.core.restore_previous
        self.addCleanup(release.set)

        def held(on_step=None):
            release.wait(10)
            return real(on_step)
        self.counting.restore_previous = held
        self.ask(True, True)
        self.errors()
        self.choose("home")  # 切換、驗證失敗、按「是」：還原卡在核心裡
        deadline = time.monotonic() + 10
        while not self.widget.canvas.find_withtag(OVERLAY):
            self.assertLess(time.monotonic(), deadline, "還原沒有開始")
            self.root.update()
            time.sleep(0.02)
        self.assertTrue(self.widget.switching)
        release.set()
        self.finish()
        self.assertEqual(self.widget.canvas.find_withtag(OVERLAY), ())

    def test_the_prompt_follows_the_language(self):
        self.widget.set_preference("language", "en")
        self.queries_write_nothing()
        ask = self.ask(True, False)
        self.errors()
        self.choose("home", "Switch account")
        self.finish()
        title, message = ask.call_args_list[1].args[:2]
        self.assertEqual(title, "Switch account")
        self.assertTrue(message.startswith("Switched to \"home\", but the usage query for it failed"), message)
        self.assertTrue(message.endswith("\n\nRestore the previous switch?"), message)

    def test_without_a_usable_pre_switch_credential_it_is_just_reported(self):
        """沒有可還原的東西時問「要還原嗎」只會得到一個拒絕：直接說明，不附問題。"""
        ask = self.ask(True)
        errors = self.errors()
        self.counting.switch = lambda label, on_step=None: SwitchResult(
            SwitchOutcome.VERIFY_FAILED, verify_failure=UsageQueryResult(QueryFailure.TIMEOUT))
        self.choose("home")
        self.finish()
        self.assertEqual(ask.call_count, 1)
        errors.assert_called_once()
        self.assertTrue(errors.call_args.args[1].startswith("已切換到「home」，但替它查詢額度失敗"))
        self.assertNotIn("要還原上一次切換嗎？", errors.call_args.args[1])

    def test_a_failed_query_of_the_old_account_alone_prompts_nothing(self):
        ask = self.ask(True)
        errors = self.errors()
        self.counting.switch = lambda label, on_step=None: SwitchResult(SwitchOutcome.SWITCHED,
                                                                        old_account_query_failed=True)
        self.choose("home")
        self.finish()
        self.assertEqual(ask.call_count, 1)
        self.assertFalse(errors.called)


class RestoreConfirmationTextTest(unittest.TestCase):
    def test_without_a_known_expiry_the_countdown_paragraph_is_left_out(self):
        board = Board(cards=(), as_of=NOW, previous_expires_at=None)
        self.assertEqual(len(restore_confirmation(board, "zh-TW").split("\n\n")), 2)
        board = Board(cards=(), as_of=NOW, previous_expires_at=NOW + timedelta(hours=3, minutes=5))
        self.assertIn("切換前憑證 3小時5分後到期", restore_confirmation(board, "zh-TW"))
