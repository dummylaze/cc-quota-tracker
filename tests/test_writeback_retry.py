"""寫回失敗重試（ADR-0011）：憑證同步寫回憑證快照失敗時，該帳號暫時是僅監看帳號；之後每輪重試一次，
總共寫 3 次，都失敗就停止重試、提示重新納管。當前憑證的指紋改變時重新計數（使用者 2026-10-06 確認）。"""
import io
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

from cc_quota_tracker import atomic
from cc_quota_tracker.__main__ import main
from cc_quota_tracker.board import Role, WatchOnlyReason
from cc_quota_tracker.canvas_text import notes
from tests.test_credential_sync import HOME, WORK, SyncTestCase

RETRYING, STOPPED = WatchOnlyReason.WRITEBACK_RETRYING, WatchOnlyReason.WRITEBACK_STOPPED
STOPPED_NOTE = "僅監看帳號（寫回快照失敗，已停止重試）：在 Claude Code 登入這個帳號後重新納管"


class WritebackTestCase(SyncTestCase):
    def setUp(self):
        super().setUp()
        self.manage("home", "rt-h", "acct-h", HOME)
        self.manage("work", "rt-w", "acct-w", WORK)
        self.core.poll()
        self.attempts = 0

    def failing(self, name="work.json"):
        """寫 name 這個憑證快照一律失敗（其他檔案照常寫），並數寫了幾次。"""
        real = atomic.write_atomic

        def write(path, *args, **kwargs):
            if Path(path).name == name:
                self.attempts += 1
                raise OSError("disk full")
            return real(path, *args, **kwargs)
        return mock.patch.object(atomic, "write_atomic", write)

    def failed_polls(self, rounds):
        with self.failing():
            for _ in range(rounds):
                cards = self.cards()
        return cards

    def work(self, cards):
        card = cards["claude:work"]
        return card.watch_only_reason, card.writeback_failures, card.switchable


class WritebackRetryTest(WritebackTestCase):
    def test_failed_write_makes_the_account_watch_only_and_counts_it(self):
        self.refresh("rt-w2", WORK)
        self.assertEqual(self.work(self.failed_polls(1)), (RETRYING, 1, False))

    def test_each_round_retries_once_and_three_failures_stop_it(self):
        self.refresh("rt-w2", WORK)
        self.assertEqual(self.work(self.failed_polls(2)), (RETRYING, 2, False))
        self.assertEqual(self.attempts, 2)
        self.assertEqual(self.work(self.failed_polls(1))[0], STOPPED)
        self.failed_polls(3)
        self.assertEqual(self.attempts, 3)  # 停止之後不再寫

    def test_successful_retry_makes_it_managed_again(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(2)
        self.assertEqual(self.work(self.cards()), (None, None, True))
        self.assertEqual(self.snapshot("work").read_bytes(), self.current().read_bytes())

    def test_count_survives_a_restart(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(2)
        self.start()
        self.assertEqual(self.work(self.failed_polls(1))[0], STOPPED)

    def test_stopped_until_restart_too(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(3)
        self.start()
        self.assertEqual(self.work(self.failed_polls(1))[0], STOPPED)
        self.assertEqual(self.attempts, 3)

    def test_new_refresh_starts_counting_again(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(3)
        self.refresh("rt-w3", WORK)
        self.assertEqual(self.work(self.failed_polls(1)), (RETRYING, 1, False))
        self.assertEqual(self.attempts, 4)

    def test_new_refresh_after_stopping_can_succeed(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(3)
        self.refresh("rt-w3", WORK)
        self.assertEqual(self.work(self.cards()), (None, None, True))

    def test_locked_bindings_file_counts_as_a_failed_write(self):
        self.refresh("rt-w2", WORK)
        with self.locked("bindings.json"):
            self.assertEqual(self.work(self.cards()), (RETRYING, 1, False))

    def test_switching_away_while_retrying_stops_it(self):
        """當前憑證已經不是那次登入，沒有東西可以重試：直接改成已停止重試。"""
        self.refresh("rt-w2", WORK)
        self.failed_polls(1)
        self.log_in_at("rt-h", "acct-h", HOME)
        cards = self.failed_polls(1)
        self.assertEqual((cards["claude:work"].role, self.work(cards)[0]), (Role.STANDBY, STOPPED))
        self.assertEqual(cards["claude:home"].watch_only_reason, None)

    def test_managing_again_clears_it(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(3)
        self.core.add("work")
        self.assertEqual(self.work(self.cards()), (None, None, True))

    def test_rest_of_the_board_is_unaffected(self):
        self.refresh("rt-w2", WORK)
        cards = self.failed_polls(1)
        self.assertEqual(cards["claude:work"].role, Role.ACTIVE)
        home = cards["claude:home"]
        self.assertEqual((home.switchable, home.watch_only_reason), (True, None))

    def test_expired_and_invalid_come_before_write_back(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(1)
        self.clock.now = WORK + timedelta(days=1)
        self.assertEqual(self.work(self.failed_polls(1))[0], WatchOnlyReason.EXPIRED)

    def test_write_back_comes_before_no_account_info(self):
        (self.home / ".claude-multi" / ".state" / "account-info" / "work.json").unlink()
        self.refresh("rt-w2", WORK)
        self.assertEqual(self.work(self.failed_polls(1))[0], RETRYING)


class WritebackListTest(WritebackTestCase):
    """命令列不重試，但 list 的原因反映看板記下的重試中與已停止重試。"""
    def run_list(self, lang="zh-TW"):
        out = io.StringIO()
        with self.cli_environment(lang), redirect_stdout(out), redirect_stderr(io.StringIO()), \
                mock.patch("cc_quota_tracker.usage_query.find_command", return_value=None), \
                mock.patch("cc_quota_tracker.__main__.datetime") as clock:
            clock.now.return_value = self.clock.now  # 命令列讀真實時鐘：換成測試的時間，免得假資料都算過期
            main(["list"])
        return out.getvalue()

    def test_list_shows_retrying_without_the_remedy(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(2)
        out = self.run_list()
        self.assertIn("僅監看帳號：寫回失敗（重試中 2/3）", out)
        self.assertNotIn("重新納管", out)

    def test_list_shows_stopped_with_the_remedy(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(3)
        out = self.run_list()
        self.assertIn("僅監看帳號：寫回失敗（已停止重試）", out)
        self.assertIn("重新納管：在 Claude Code 登入這個帳號後，執行", out)

    def test_list_in_english(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(1)
        self.assertIn("Watch-only account: write-back failed (retrying 1/3)", self.run_list("en"))

    def test_list_does_not_retry(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(1)
        with self.failing():
            self.run_list()
        self.assertEqual(self.attempts, 1)


class WritebackCardNotesTest(WritebackTestCase):
    def note(self, lang="zh-TW"):
        board = self.core.poll()
        card = next(c for c in board.cards if c.account_key == "claude:work")
        return [n for n in notes(card, board, lang) if "寫回" in n[0] or "write" in n[0].lower()]

    def test_retrying_note_replaces_the_watch_only_note(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(1)
        with self.failing():
            self.assertEqual(self.note(), [("寫回快照失敗，自動重試 2/3", "warning", "fg")])

    def test_retrying_note_in_english(self):
        self.refresh("rt-w2", WORK)
        with self.failing():
            self.assertEqual(self.note("en"), [("Couldn't write back the credential snapshot, retrying automatically 1/3",
                                                "warning", "fg")])

    def test_stopped_note_tells_to_manage_again(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(3)
        self.assertEqual(self.note(), [(STOPPED_NOTE, "critical", "critical")])

    def test_stopped_note_in_english(self):
        self.refresh("rt-w2", WORK)
        self.failed_polls(3)
        self.assertEqual([n[0] for n in self.note("en")],
                         ["Watch-only account (couldn't write back the credential snapshot, stopped retrying): "
                          "sign in to this account in Claude Code, then manage it again"])

