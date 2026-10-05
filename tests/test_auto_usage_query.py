"""縫 ①：自動查詢。只看核心的 poll 回傳的看板，以及假 claude 被啟動了幾次（starts.log）。
假 claude 不寫對話紀錄，所以查詢本身不會讓讀數再次落後。"""
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from cc_quota_tracker.board import QueryFailure, ReadingState
from tests.fakehome import NOW, claude_json, usage_cache
from tests.test_cli import CliTestCase
from tests.test_usage_query import LATER, claude, install_fake_claude
from tests.test_usage_query_async import AsyncQueryTestCase

INTERVAL = timedelta(minutes=15)


class AutoQueryTestCase(AsyncQueryTestCase):
    """當前憑證帳號是未監看帳號、額度快取的觀測時間是 NOW、時鐘停在 NOW；自動查詢預設開啟，間隔 15 分鐘。"""

    def setUp(self):
        super().setUp()
        self.configure()

    def configure(self, **fields):
        self.write_settings(providers=claude(claudeCommand=str(self.command), **{"autoUsageQuery": True, **fields}))

    def starts(self):
        log = self.fake_dir / "starts.log"
        return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0

    def talk(self, at=None, name="s1"):
        """對話紀錄的修改時間：預設是時鐘現在。"""
        path = self.paths.claude_dir / "projects" / "proj" / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"type":"user"}\n', encoding="utf-8")
        stamp = (at or self.clock.now).timestamp()
        os.utime(path, (stamp, stamp))

    def poll(self):
        """poll 可能啟動查詢，子行程吃的是真實的環境變數：與 trigger 一樣換成測試給定的。"""
        env = dict(self.env, SYSTEMROOT=os.environ.get("SYSTEMROOT", ""), COMSPEC=os.environ.get("COMSPEC", ""),
                   PATH=str(self.home / "empty-path"))
        with mock.patch.dict(os.environ, env, clear=True):
            return self.core.poll()

    def lagging_since(self, minutes=1):
        """觀測時間之後有新對話，讀數落後。"""
        self.talk(NOW + timedelta(minutes=minutes))

    def at(self, **offset):
        """時鐘走到觀測時間之後的某一刻。"""
        self.clock.now = NOW + timedelta(**offset)


class TriggerTest(AutoQueryTestCase):
    def test_off_by_default_it_never_queries(self):
        self.configure(autoUsageQuery=False)
        self.script()
        self.lagging_since()
        self.at(days=1)
        self.assertFalse(self.poll().usage_query.in_progress)
        self.assertEqual(self.starts(), 0)

    def test_a_missing_switch_means_off_too(self):
        self.write_settings(providers=claude(claudeCommand=str(self.command)))
        self.script()
        self.lagging_since()
        self.at(days=1)
        self.assertFalse(self.poll().usage_query.in_progress)
        self.assertEqual(self.starts(), 0)

    def test_a_lagging_reading_is_queried_once_the_interval_has_passed(self):
        self.script()
        self.lagging_since()
        self.at(minutes=15)
        board = self.poll()
        self.assertTrue(board.cards[0].lagging)
        self.assertTrue(board.usage_query.in_progress)
        board = self.finish()
        self.assertEqual((board.last_reading_at, board.cards[0].lagging), (LATER, False))
        self.assertEqual(self.starts(), 1)

    def test_not_before_the_interval_has_passed(self):
        self.script()
        self.lagging_since()
        self.at(minutes=14, seconds=59)
        self.assertFalse(self.poll().usage_query.in_progress)
        self.clock.advance(seconds=1)
        self.assertTrue(self.poll().usage_query.in_progress)
        self.finish()

    def test_a_pending_reading_is_queried_too(self):
        new = json.dumps(claude_json(usage_cache(fetched_at=LATER, account_uuid="acct-2"), oauth="acct-2"))
        self.script(cache_text=new)
        self.write_cache(fetched_at=NOW, oauth="acct-2", account_uuid="acct-1")  # 切到 acct-2，額度快取還是 acct-1 的
        self.at(minutes=15)
        board = self.poll()
        self.assertEqual(board.cards[0].reading_state, ReadingState.PENDING)
        self.assertTrue(board.usage_query.in_progress)
        self.assertEqual(self.finish().cards[0].reading_state, ReadingState.HAS_READING)

    def test_an_idle_account_is_never_queried(self):
        self.script()
        for days in (1, 2, 30):  # 沒有新的對話紀錄：讀數再舊也不落後
            self.at(days=days)
            board = self.poll()
            self.assertFalse(board.cards[0].lagging)
            self.assertFalse(board.usage_query.in_progress)
        self.assertEqual(self.starts(), 0)

    def test_a_fresh_reading_with_a_running_session_is_not_queried(self):
        self.script()
        self.talk(NOW - timedelta(minutes=1))  # 對話在觀測之前：還沒落後
        self.at(hours=3)
        self.assertFalse(self.poll().usage_query.in_progress)

    def test_many_sessions_still_cost_one_query(self):
        self.script()
        for name in ("s1", "s2", "s3"):
            self.talk(NOW + timedelta(minutes=1), name)
        self.at(minutes=15)
        self.assertTrue(self.poll().usage_query.in_progress)
        self.poll()
        self.finish()
        for minutes in (16, 17, 40):
            self.at(minutes=minutes)
            self.poll()
        self.assertEqual(self.starts(), 1)

    def test_the_query_leaves_no_transcript_so_it_does_not_trigger_the_next_one(self):
        self.script()
        self.lagging_since()
        self.at(minutes=15)
        self.poll()
        self.finish()
        for hours in (1, 5, 24):
            self.at(hours=hours)
            board = self.poll()
            self.assertFalse(board.cards[0].lagging)
            self.assertFalse(board.usage_query.in_progress)
        self.assertEqual(self.starts(), 1)

    def test_changing_the_switch_takes_effect_on_the_next_round(self):
        self.script()
        self.lagging_since()
        self.at(minutes=20)
        self.configure(autoUsageQuery=False)
        self.assertFalse(self.poll().usage_query.in_progress)
        self.configure(autoUsageQuery=True)
        self.assertTrue(self.poll().usage_query.in_progress)
        self.finish()

    def test_a_configured_interval_replaces_fifteen_minutes(self):
        self.configure(autoUsageQueryMinutes=30)
        self.script()
        self.lagging_since()
        self.at(minutes=29, seconds=59)
        self.assertFalse(self.poll().usage_query.in_progress)
        self.clock.advance(seconds=1)
        self.assertTrue(self.poll().usage_query.in_progress)
        self.finish()


class IntervalTest(AutoQueryTestCase):
    def test_the_interval_counts_from_the_later_of_the_last_query_and_the_reading(self):
        # 上一次查詢的開始比讀數的觀測時間晚（查詢失敗，讀數沒換）：從查詢開始起算
        self.script(usage="silent")
        self.lagging_since()
        self.at(minutes=20)
        self.poll()
        self.finish()  # 在 NOW+20 開始，失敗
        self.at(minutes=34, seconds=59)
        self.assertFalse(self.poll().usage_query.in_progress)
        self.clock.advance(seconds=1)
        self.assertTrue(self.poll().usage_query.in_progress)
        self.finish()
        self.assertEqual(self.starts(), 2)

    def test_a_usage_run_by_the_user_counts_as_a_query(self):
        # 讀數的觀測時間比工具上一次查詢晚（使用者自己打了 /usage）：從觀測時間起算
        self.write_cache(fetched_at=NOW + timedelta(minutes=20))
        self.talk(NOW + timedelta(minutes=21))
        self.script()
        self.at(minutes=34, seconds=59)
        self.assertFalse(self.poll().usage_query.in_progress)
        self.clock.advance(seconds=1)
        self.assertTrue(self.poll().usage_query.in_progress)
        self.finish()

    def test_a_manual_query_counts_too(self):
        self.script(usage="silent")
        self.lagging_since()
        self.at(minutes=1)
        self.assertTrue(self.trigger())
        self.finish()
        self.at(minutes=15, seconds=59)  # 距離觀測時間 15 分鐘，但距離手動查詢的開始只有 14 分 59 秒
        self.assertFalse(self.poll().usage_query.in_progress)
        self.clock.advance(seconds=1)
        self.assertTrue(self.poll().usage_query.in_progress)
        self.finish()

    def test_an_interval_below_the_floor_runs_at_the_floor(self):
        self.configure(autoUsageQueryMinutes=1)
        self.script()
        self.lagging_since()
        self.at(minutes=4, seconds=59)
        board = self.poll()
        self.assertFalse(board.usage_query.in_progress)
        self.assertTrue(board.usage_query.interval_below_floor)
        self.clock.advance(seconds=1)
        self.assertTrue(self.poll().usage_query.in_progress)
        self.finish()


class PauseTest(AutoQueryTestCase):
    def cycle(self, usage="silent"):
        """過一個間隔、有新對話、自動查詢跑一次（劇本指定結果），回傳查完的看板。"""
        self.clock.advance(minutes=15)
        self.talk()
        self.rearm(usage=usage, fetched_at=self.clock.now)
        self.assertTrue(self.poll().usage_query.in_progress)
        return self.finish()

    def setUp(self):
        super().setUp()
        self.lagging_since()
        self.at(minutes=0)

    def test_three_failures_in_a_row_pause_it_and_show_the_last_reason(self):
        for _ in range(2):
            self.assertFalse(self.cycle().usage_query.auto_paused)
        board = self.cycle()
        self.assertTrue(board.usage_query.auto_paused)
        self.assertEqual(board.usage_query.last_failure.failure, QueryFailure.NOT_WRITTEN)
        for hours in (1, 6):  # 暫停後不再查
            self.clock.advance(hours=hours)
            self.assertFalse(self.poll().usage_query.in_progress)
        self.assertEqual(self.starts(), 3)

    def test_a_single_failure_waits_a_full_interval_and_does_not_pause(self):
        board = self.cycle()
        self.assertFalse(board.usage_query.auto_paused)
        self.assertIsNotNone(board.usage_query.last_failure)
        self.clock.advance(minutes=14, seconds=59)
        self.assertFalse(self.poll().usage_query.in_progress)

    def test_a_success_in_between_resets_the_count(self):
        for usage in ("silent", "silent", "write", "silent", "silent"):
            board = self.cycle(usage)
        self.assertFalse(board.usage_query.auto_paused)
        self.assertTrue(self.cycle().usage_query.auto_paused)

    def test_a_successful_manual_query_resumes_it(self):
        for _ in range(3):
            board = self.cycle()
        self.assertTrue(board.usage_query.auto_paused)
        self.clock.advance(minutes=1)
        self.rearm(fetched_at=self.clock.now)
        self.assertTrue(self.trigger())
        board = self.finish()
        self.assertEqual((board.usage_query.auto_paused, board.usage_query.last_failure), (False, None))
        for _ in range(2):  # 次數歸零：再連續失敗 2 次不暫停，第 3 次才暫停
            self.assertFalse(self.cycle().usage_query.auto_paused)
        self.assertTrue(self.cycle().usage_query.auto_paused)

    def test_failed_manual_queries_neither_count_nor_reset_the_failures(self):
        self.cycle()
        self.cycle()
        for _ in range(3):  # 手動失敗不累計：兩次自動失敗加三次手動失敗，仍沒暫停
            self.clock.advance(minutes=1)
            self.rearm(usage="error", message="rate limited")
            self.assertTrue(self.trigger())
            board = self.finish()
            self.assertFalse(board.usage_query.auto_paused)
            self.assertEqual(board.usage_query.last_failure.failure, QueryFailure.REPORTED_ERROR)  # 原因照常顯示
        self.assertTrue(self.cycle().usage_query.auto_paused)  # 手動失敗也沒歸零：第三次自動失敗就暫停

    def test_a_manual_command_not_found_does_not_count_either(self):
        self.cycle()
        self.cycle()
        self.write_settings(providers=claude(claudeCommand=str(self.home / "nowhere" / "claude.cmd"), autoUsageQuery=True))
        self.clock.advance(minutes=1)
        self.assertTrue(self.trigger())
        board = self.poll()
        self.assertEqual(board.usage_query.last_failure.failure, QueryFailure.COMMAND_NOT_FOUND)
        self.assertFalse(board.usage_query.auto_paused)

    def test_an_automatic_launch_failure_counts(self):
        self.cycle()
        self.cycle()
        self.write_settings(providers=claude(claudeCommand=str(self.home / "nowhere" / "claude.cmd"), autoUsageQuery=True))
        self.clock.advance(minutes=15)
        self.talk()
        board = self.poll()  # 自動查詢開不起來：找不到 claude，算第三次失敗
        self.assertEqual(board.usage_query.last_failure.failure, QueryFailure.COMMAND_NOT_FOUND)
        self.assertTrue(board.usage_query.auto_paused)

    def test_a_failed_manual_query_does_not_resume_it(self):
        for _ in range(3):
            self.cycle()
        self.clock.advance(minutes=1)
        self.rearm(usage="error", message="rate limited")
        self.assertTrue(self.trigger())
        self.assertTrue(self.finish().usage_query.auto_paused)

    def test_pause_is_only_reported_while_auto_query_is_on(self):
        for _ in range(3):
            self.cycle()
        self.configure(autoUsageQuery=False)
        self.assertFalse(self.poll().usage_query.auto_paused)
        self.configure(autoUsageQuery=True)
        self.assertTrue(self.poll().usage_query.auto_paused)  # 重新開啟不會解除暫停

    def test_pause_does_not_survive_a_restart(self):
        for _ in range(3):
            self.cycle()
        self.start()
        self.assertFalse(self.poll().usage_query.auto_paused)
        self.finish()  # 重新啟動後從頭開始，自動查詢照常起跑；讓假 claude 收尾


class ManualCooldownTest(AutoQueryTestCase):
    def test_an_automatic_query_does_not_start_the_manual_cooldown(self):
        self.script()
        self.lagging_since()
        self.at(minutes=15)
        self.poll()
        board = self.finish()
        self.assertFalse(board.usage_query.cooling_down)
        self.rearm(fetched_at=LATER + timedelta(minutes=5))
        self.assertTrue(self.trigger())
        self.finish()


class AutoQueryFromTheCommandLineTest(CliTestCase):
    """命令列的 list 與其他子指令用同一個核心，但不會因為設定檔開了自動查詢就啟動查詢。"""

    def test_list_never_starts_an_automatic_query(self):
        self.env.update(SYSTEMROOT=os.environ.get("SYSTEMROOT", ""), COMSPEC=os.environ.get("COMSPEC", ""),
                        PATH=str(self.home / "empty-path"))
        fake_dir = self.home / "fake-bin"
        command = install_fake_claude(fake_dir)
        self.write_settings(providers=claude(claudeCommand=str(command), autoUsageQuery=True))
        self.write_cache(fetched_at=datetime.now(timezone.utc) - timedelta(hours=1))
        talk = self.paths.claude_dir / "projects" / "proj" / "s1.jsonl"
        talk.parent.mkdir(parents=True)
        talk.write_text('{"type":"user"}\n', encoding="utf-8")
        with mock.patch("cc_quota_tracker.usage_query.UsageQuery.start") as start:
            code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("query", out)  # 確實落後（有 query 的說明），間隔也早就過了
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
