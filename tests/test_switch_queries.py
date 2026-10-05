"""切換前後的額度查詢（ADR-0010 修訂段）：寫入前替舊帳號查一次、寫入後替新帳號查一次兼作驗證。
全部從核心的 switch 打進去，查詢由假 claude 執行，斷言結果值、假 home 的檔案與看板。"""
import json
import os
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from cc_quota_tracker import atomic
from cc_quota_tracker.board import QueryFailure, ReadingState, Role, SwitchOutcome, SwitchRefusal
from tests.fakehome import NOW
from tests.test_credential_sync import HOME, WORK
from tests.test_switch import SwitchTestCase, fetched
from tests.test_usage_query import claude


class QueriedSwitchTestCase(SwitchTestCase):
    """當前憑證帳號是 work（讀數是 3 小時前的），切到 home。"""

    def talk(self, at):
        """對話紀錄的修改時間：比讀數的觀測時間晚，讀數就落後。"""
        path = self.paths.claude_dir / "projects" / "proj" / "s1.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"type":"user"}\n', encoding="utf-8")
        os.utime(path, (at.timestamp(), at.timestamp()))

    def work_reads(self, oauth="acct-w", reading_of="acct-w"):
        """額度快取是 3 小時前的讀數，歸屬 reading_of；看板先 poll 一輪，讀數存成 work 的待命讀數。"""
        self.write_cache(oauth=oauth, account_uuid=reading_of, fetched_at=NOW - timedelta(hours=3))
        self.core.poll()

    def lagging_work(self):
        self.work_reads()
        self.talk(NOW - timedelta(hours=2))
        self.clock.advance(minutes=2)  # 沒落後的判斷最多快取 60 秒：過了才會重掃對話紀錄
        self.assertTrue(self.core.poll().cards[0].lagging)

    def wait_for_query(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            board = self.core.poll()
            if not board.usage_query.in_progress:
                return board
            time.sleep(0.05)
        self.fail("查詢沒有結束")


class OldAccountQueryTest(QueriedSwitchTestCase):
    def test_lagging_old_account_is_queried_before_the_write(self):
        self.lagging_work()
        result = self.core.switch("home")
        self.assertEqual((result.outcome, result.old_account_query_failed), (SwitchOutcome.SWITCHED, False))
        self.assertEqual(self.starts(), 2)
        self.assertEqual(self.credential_at_start(0), self.snapshot("work").read_bytes())  # 舊帳號的憑證查的
        self.assertEqual(self.credential_at_start(1), self.snapshot("home").read_bytes())  # 寫入之後才查新帳號

    def test_the_old_accounts_fresh_reading_is_what_it_leaves_behind(self):
        self.lagging_work()
        self.core.switch("home")
        work = self.cards()["claude:work"]
        self.assertEqual((work.role, work.reading_state), (Role.STANDBY, ReadingState.HAS_READING))
        self.assertEqual((work.reading_age, work.lagging), (self.clock.now - fetched(0), False))

    def test_a_reading_that_belongs_to_another_account_is_queried_too(self):
        self.work_reads(reading_of="acct-x")  # 額度快取是別的帳號的：讀數待更新
        self.assertIs(self.core.poll().cards[0].reading_state, ReadingState.PENDING)
        self.core.switch("home")
        self.assertEqual(self.starts(), 2)
        self.assertEqual(self.cards()["claude:work"].reading_age, self.clock.now - fetched(0))

    def test_a_reading_that_is_not_lagging_skips_the_query(self):
        self.work_reads()
        self.assertFalse(self.core.poll().cards[0].lagging)
        result = self.core.switch("home")
        self.assertEqual((result.outcome, result.old_account_query_failed), (SwitchOutcome.SWITCHED, False))
        self.assertEqual(self.starts(), 1)  # 只有新帳號那一次
        self.assertEqual(self.credential_at_start(0), self.snapshot("home").read_bytes())

    def test_no_reading_at_all_skips_the_query(self):
        self.assertIs(self.core.poll().cards[0].reading_state, ReadingState.NO_READING)
        self.core.switch("home")
        self.assertEqual(self.starts(), 1)

    def test_an_unwatched_old_account_skips_the_query(self):
        self.log_in_at("rt-x", "acct-x", NOW + timedelta(days=10))
        self.write_cache(oauth="acct-x", account_uuid="acct-x", fetched_at=NOW - timedelta(hours=3))
        self.talk(NOW - timedelta(hours=2))
        card = self.core.poll().cards[0]
        self.assertEqual((card.role, card.lagging), (Role.UNWATCHED, True))
        self.core.switch("home")
        self.assertEqual(self.starts(), 1)

    def test_an_old_account_without_a_binding_skips_the_query(self):
        """沒有綁定就沒有待命讀數可以更新：讀數待更新也不查。"""
        self.write_credentials(refresh="rt-d", refresh_expires_at=NOW + timedelta(days=5))
        self.core.import_snapshot(self.current(), "dropped")
        self.work_reads(reading_of="acct-x")
        card = self.core.poll().cards[0]
        self.assertEqual((card.account_key, card.reading_state), ("claude:dropped", ReadingState.PENDING))
        self.assertIs(self.core.switch("home").outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(self.starts(), 1)

    def test_failure_does_not_stop_the_switch_and_is_marked_on_the_result(self):
        self.lagging_work()
        self.script_queries({0: {"usage": "error", "message": "boom"}})
        result = self.core.switch("home")
        self.assertEqual((result.outcome, result.old_account_query_failed), (SwitchOutcome.SWITCHED, True))
        self.assertEqual(self.current().read_bytes(), self.snapshot("home").read_bytes())
        self.assertEqual(self.starts(), 2)

    def test_failure_is_not_shown_on_the_board(self):
        self.lagging_work()
        self.script_queries({0: {"usage": "silent"}})
        self.core.switch("home")
        self.assertIsNone(self.core.poll().usage_query.last_failure)

    def test_the_flag_survives_a_refusal_that_comes_after_the_query(self):
        """查詢之後寫不進當前憑證而拒絕：結果值仍標出舊帳號查詢失敗，也不做新帳號的驗證查詢。"""
        self.lagging_work()
        self.script_queries({0: {"usage": "silent"}})
        real = atomic.write_atomic

        def write(path, *args, **kwargs):
            if Path(path).name == ".credentials.json":
                raise PermissionError("locked")
            return real(path, *args, **kwargs)
        with mock.patch.object(atomic, "write_atomic", write):
            result = self.core.switch("home")
        self.assertEqual((result.outcome, result.refusal, result.old_account_query_failed),
                         (SwitchOutcome.REFUSED, SwitchRefusal.UNWRITABLE, True))
        self.assertEqual(self.starts(), 1)

    def test_old_account_query_that_refreshes_the_credential_is_synced_and_saved(self):
        """查詢時 Claude Code 可能順便刷新當前憑證：切走前的同步與切換前憑證都要拿查詢之後的版本。"""
        self.lagging_work()
        original = self.current().read_bytes()
        self.refresh("rt-w2", WORK)
        rotated = self.current().read_text(encoding="utf-8")
        self.current().write_bytes(original)
        self.script_queries({0: {"credential_text": rotated}})
        self.assertIs(self.core.switch("home").outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(self.credential_at_start(0), original)
        self.assertEqual(self.snapshot("work").read_text(encoding="utf-8"), rotated)
        saved = json.loads(self.pre_switch().read_text(encoding="utf-8"))
        self.assertEqual(saved["credentials"], rotated)

    def test_refresh_during_the_query_that_cannot_be_synced_refuses_before_writing(self):
        self.lagging_work()
        original = self.current().read_bytes()
        self.refresh("rt-w2", WORK)
        rotated = self.current().read_text(encoding="utf-8")
        self.current().write_bytes(original)
        self.script_queries({0: {"credential_text": rotated, "usage": "silent"}})
        real = atomic.write_atomic

        def write(path, *args, **kwargs):
            if Path(path).name == "work.json" and self.starts() > 0:  # 查詢之後的那次同步寫不成
                raise OSError("disk full")
            return real(path, *args, **kwargs)
        with mock.patch.object(atomic, "write_atomic", write):
            result = self.core.switch("home")
        self.assertEqual((result.outcome, result.refusal, result.old_account_query_failed),
                         (SwitchOutcome.REFUSED, SwitchRefusal.SYNC_FAILED, True))
        self.assertEqual(self.current().read_text(encoding="utf-8"), rotated)  # 切換沒有動它
        self.assertFalse(self.pre_switch().exists())


class NewAccountQueryTest(QueriedSwitchTestCase):
    def test_new_account_reading_shows_up_at_once(self):
        result = self.core.switch("home")
        self.assertEqual((result.outcome, result.verify_failure), (SwitchOutcome.SWITCHED, None))
        board = self.core.poll()
        self.assertEqual((board.cards[0].account_key, board.cards[0].reading_state),
                         ("claude:home", ReadingState.HAS_READING))
        self.assertEqual(board.last_reading_at, fetched(0))

    def test_failed_verification_is_reported_but_everything_stays_written(self):
        self.script_queries({0: {"usage": "silent"}})
        before = len(self.switch_log())
        result = self.core.switch("home")
        self.assertEqual((result.outcome, result.refusal, result.old_account_query_failed),
                         (SwitchOutcome.VERIFY_FAILED, None, False))
        self.assertEqual(result.verify_failure.failure, QueryFailure.NOT_WRITTEN)
        self.assertEqual(self.current().read_bytes(), self.snapshot("home").read_bytes())
        self.assertEqual(self.oauth_account()["accountUuid"], "acct-h")
        self.assertEqual(len(self.switch_log()), before + 1)
        self.assertTrue(self.pre_switch().exists())

    def test_claude_code_reporting_an_error_fails_verification_with_its_message(self):
        self.script_queries({0: {"usage": "error", "message": "Not logged in"}})
        result = self.core.switch("home")
        self.assertEqual((result.outcome, result.verify_failure.failure, result.verify_failure.message),
                         (SwitchOutcome.VERIFY_FAILED, QueryFailure.REPORTED_ERROR, "Not logged in"))

    def test_claude_not_found_fails_verification(self):
        self.write_settings(providers=claude(claudeCommand=str(self.home / "nowhere" / "claude.cmd")))
        result = self.core.switch("home")
        self.assertEqual((result.outcome, result.verify_failure.failure),
                         (SwitchOutcome.VERIFY_FAILED, QueryFailure.COMMAND_NOT_FOUND))
        self.assertEqual(self.current().read_bytes(), self.snapshot("home").read_bytes())

    def test_both_queries_failing_reports_both(self):
        self.lagging_work()
        self.script_queries({0: {"usage": "silent"}, 1: {"usage": "silent"}})
        result = self.core.switch("home")
        self.assertEqual((result.outcome, result.old_account_query_failed), (SwitchOutcome.VERIFY_FAILED, True))

    def test_a_half_written_switch_is_not_verified(self):
        """憑證寫了、帳號資訊沒寫成：兩者錯配，這時替新帳號查詢沒有意義。"""
        real = atomic.write_atomic

        def write(path, *args, **kwargs):
            if Path(path) == self.paths.claude_json:
                raise PermissionError("locked")
            return real(path, *args, **kwargs)
        with mock.patch.object(atomic, "write_atomic", write):
            result = self.core.switch("home")
        self.assertIs(result.outcome, SwitchOutcome.WRITE_FAILED)
        self.assertEqual(self.starts(), 0)


class RefusalStartsNoQueryTest(QueriedSwitchTestCase):
    def assert_nothing_touched_and_no_query(self, label):
        before = self.untouched()
        result = self.core.switch(label)
        self.assertIs(result.outcome, SwitchOutcome.REFUSED)
        self.assertEqual(self.untouched(), before)
        self.assertEqual(self.starts(), 0)

    def test_watch_only_target(self):
        self.lagging_work()
        self.clock.now = HOME + timedelta(seconds=1)
        self.assert_nothing_touched_and_no_query("home")

    def test_already_the_current_account(self):
        self.lagging_work()
        self.assert_nothing_touched_and_no_query("work")

    def test_unknown_label(self):
        self.lagging_work()
        self.assert_nothing_touched_and_no_query("nobody")

    def test_failed_sync_before_the_switch(self):
        self.lagging_work()
        self.refresh("rt-w2", WORK)
        real = atomic.write_atomic

        def write(path, *args, **kwargs):
            if Path(path).name == "work.json":
                raise OSError("disk full")
            return real(path, *args, **kwargs)
        with mock.patch.object(atomic, "write_atomic", write):
            self.assert_nothing_touched_and_no_query("home")


class QueryBookkeepingTest(QueriedSwitchTestCase):
    def test_the_switch_queries_do_not_start_the_manual_cooldown(self):
        self.lagging_work()
        self.core.switch("home")
        self.assertFalse(self.core.poll().usage_query.cooling_down)
        self.assertTrue(self.core.start_query())  # 切換之後立刻手動查詢
        self.wait_for_query()
        self.assertEqual(self.starts(), 3)

    def test_a_successful_switch_query_clears_the_last_failure_like_any_other_success(self):
        self.script_queries({0: {"usage": "silent"}})
        self.assertTrue(self.core.start_query())  # 手動查詢失敗：看板記下最後一次失敗
        self.assertIsNotNone(self.wait_for_query().usage_query.last_failure)
        self.core.switch("home")  # 切換只查新帳號那一次（第 1 次被啟動），成功
        self.assertIsNone(self.core.poll().usage_query.last_failure)

    def test_failed_switch_queries_do_not_start_the_manual_cooldown_either(self):
        self.lagging_work()
        self.script_queries({0: {"usage": "silent"}, 1: {"usage": "silent"}})
        self.core.switch("home")
        board = self.core.poll()
        self.assertEqual((board.usage_query.cooling_down, board.usage_query.last_failure), (False, None))
        self.assertTrue(self.core.start_query())
        self.wait_for_query()

    def test_the_switch_queries_count_toward_the_auto_query_interval(self):
        """自動查詢間隔 15 分鐘：新帳號的讀數落後了，但離切換觸發的查詢不到一個間隔，不再自動查。"""
        self.write_settings(providers=claude(claudeCommand=str(self.fake_dir / "claude.cmd"), autoUsageQuery=True))
        self.core.switch("home")
        self.assertEqual(self.starts(), 1)
        self.talk(NOW - timedelta(minutes=10))  # 新帳號的讀數（觀測時間 fetched(0)）之後又有對話：落後
        self.clock.advance(minutes=14, seconds=59)
        board = self.core.poll()
        self.assertTrue(board.cards[0].lagging)
        self.assertFalse(board.usage_query.in_progress)
        self.assertEqual(self.starts(), 1)
        self.clock.advance(seconds=1)
        self.assertTrue(self.core.poll().usage_query.in_progress)
        self.wait_for_query()
        self.assertEqual(self.starts(), 2)

    def test_a_successful_switch_query_resumes_a_paused_auto_query(self):
        """自動查詢連續失敗三次就暫停；一次成功的查詢（含切換觸發的）才恢復。"""
        self.write_settings(providers=claude(claudeCommand=str(self.fake_dir / "claude.cmd"), autoUsageQuery=True))
        self.script_queries({n: {"usage": "silent"} for n in range(3)})
        self.write_cache(oauth="acct-w", account_uuid="acct-x", fetched_at=NOW - timedelta(hours=3))
        for _ in range(3):  # 讀數待更新：每滿一個間隔自動查一次，三次都沒寫回
            self.clock.advance(minutes=15)
            self.core.poll()
            self.wait_for_query()
        self.assertTrue(self.core.poll().usage_query.auto_paused)
        self.core.switch("home")  # 第 4 次被啟動：寫回成功
        self.assertFalse(self.core.poll().usage_query.auto_paused)


if __name__ == "__main__":
    unittest.main()
