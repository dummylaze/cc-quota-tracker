import json
import os
import time
import unittest
from datetime import timedelta
from unittest import mock

from cc_quota_tracker.board import QueryFailure, ReadingState, Role
from tests.fakehome import NOW, claude_json, usage_cache
from tests.test_usage_query import LATER, UsageQueryTestCase, claude


class AsyncQueryTestCase(UsageQueryTestCase):
    """假 claude 停在閘門前：測試決定查詢何時完成。"""

    def setUp(self):
        super().setUp()
        self.gate = self.fake_dir / "gate"

    def script(self, cache_text=None, **fields):
        super().script(gate=str(self.gate), **fields)
        if cache_text is not None:  # 換掉假 claude 寫回的整份內容
            path = self.fake_dir / "script.json"
            path.write_text(json.dumps(dict(json.loads(path.read_text(encoding="utf-8")), cache_text=cache_text)),
                            encoding="utf-8")

    def trigger(self):
        """觸發查詢用的是真實的環境變數：與同步查詢的測試一樣，換成測試給定的。"""
        env = dict(self.env, SYSTEMROOT=os.environ.get("SYSTEMROOT", ""), COMSPEC=os.environ.get("COMSPEC", ""),
                   PATH=str(self.home / "empty-path"))
        with mock.patch.dict(os.environ, env, clear=True):
            return self.core.start_query()

    def poll_until_done(self):
        """反覆 poll 到查詢結束（真實時間最多 10 秒）。"""
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            board = self.core.poll()
            if not board.usage_query.in_progress:
                return board
            time.sleep(0.05)
        self.fail("查詢沒有結束")

    def finish(self):
        """放行假 claude，再 poll 到查詢結束。"""
        self.gate.write_text("", encoding="utf-8")
        return self.poll_until_done()

    def rearm(self, **fields):
        """為下一次查詢重新布置劇本，閘門關上。"""
        self.gate.unlink(missing_ok=True)
        self.script(**fields)


class InProgressTest(AsyncQueryTestCase):
    def test_trigger_returns_at_once_and_poll_does_not_wait_for_the_subprocess(self):
        self.script()
        started = time.monotonic()
        self.assertTrue(self.trigger())
        board = self.core.poll()
        self.assertLess(time.monotonic() - started, 2)  # 子行程還卡在閘門前，等它的話會一路等到逾時
        self.assertTrue(board.usage_query.in_progress)
        self.assertEqual(board.last_reading_at, NOW)
        self.finish()

    def test_finishing_shows_the_new_reading_and_clears_lagging(self):
        self.log_in(refresh="rt-w", account_uuid="acct-1")
        self.core.add("work")
        talk = self.paths.claude_dir / "projects" / "proj" / "s1.jsonl"
        talk.parent.mkdir(parents=True)
        talk.write_text('{"type":"user"}\n', encoding="utf-8")
        at = (NOW + timedelta(minutes=10)).timestamp()
        os.utime(talk, (at, at))
        self.write_cache(fetched_at=NOW)
        self.clock.advance(minutes=20)
        self.assertTrue(self.core.poll().cards[0].lagging)
        self.script()
        self.assertTrue(self.trigger())
        self.assertTrue(self.core.poll().usage_query.in_progress)
        board = self.finish()
        self.assertEqual(board.last_reading_at, LATER)
        self.assertFalse(board.cards[0].lagging)
        self.assertIsNone(board.usage_query.last_failure)

    def test_cannot_start_a_second_query_while_one_is_running(self):
        self.script()
        self.assertTrue(self.trigger())
        self.assertFalse(self.trigger())
        self.finish()


class CooldownTest(AsyncQueryTestCase):
    def test_trigger_is_refused_during_the_cooldown_and_allowed_after_it(self):
        self.script()
        self.assertTrue(self.trigger())
        self.assertTrue(self.finish().usage_query.cooling_down)
        self.assertFalse(self.trigger())
        self.clock.advance(seconds=29)
        self.assertFalse(self.trigger())
        self.assertTrue(self.core.poll().usage_query.cooling_down)
        self.clock.advance(seconds=1)
        self.assertFalse(self.core.poll().usage_query.cooling_down)
        again = LATER + timedelta(minutes=5)
        self.rearm(fetched_at=again)
        self.assertTrue(self.trigger())
        self.assertEqual(self.finish().last_reading_at, again)

    def test_a_failed_query_cools_down_too(self):
        self.script(usage="silent")
        self.assertTrue(self.trigger())
        self.assertTrue(self.finish().usage_query.cooling_down)
        self.assertFalse(self.trigger())

    def test_no_status_before_any_query(self):
        board = self.core.poll()
        self.assertFalse(board.usage_query.in_progress)
        self.assertFalse(board.usage_query.cooling_down)
        self.assertIsNone(board.usage_query.last_failure)


class FailureTest(AsyncQueryTestCase):
    def test_failure_is_on_the_board_and_the_reading_stays(self):
        self.script(usage="error", message="Not logged in · Please run /login")
        self.assertTrue(self.trigger())
        board = self.finish()
        failure = board.usage_query.last_failure
        self.assertEqual((failure.failure, failure.message),
                         (QueryFailure.REPORTED_ERROR, "Not logged in · Please run /login"))
        self.assertEqual(board.last_reading_at, NOW)
        self.assertEqual(board.cards[0].reading_state, ReadingState.HAS_READING)

    def test_command_not_found_fails_at_once(self):
        self.write_settings(providers=claude(claudeCommand=str(self.home / "nowhere" / "claude.cmd")))
        self.assertTrue(self.trigger())
        board = self.core.poll()
        self.assertFalse(board.usage_query.in_progress)
        self.assertEqual(board.usage_query.last_failure.failure, QueryFailure.COMMAND_NOT_FOUND)
        self.assertTrue(board.usage_query.cooling_down)

    def test_timeout_is_measured_on_the_core_clock(self):
        self.script(usage="hang")
        self.assertTrue(self.trigger())
        self.assertTrue(self.core.poll().usage_query.in_progress)
        self.clock.advance(seconds=20)
        board = self.finish()
        self.assertEqual(board.usage_query.last_failure.failure, QueryFailure.TIMEOUT)

    def test_failure_stays_through_a_retry_and_is_cleared_by_a_success(self):
        self.script(usage="silent")
        self.trigger()
        self.finish()
        self.clock.advance(seconds=30)
        self.rearm()
        self.assertTrue(self.trigger())
        retrying = self.core.poll().usage_query
        self.assertTrue(retrying.in_progress)
        self.assertEqual(retrying.last_failure.failure, QueryFailure.NOT_WRITTEN)  # 進行中仍帶著上一次的原因
        self.assertIsNone(self.finish().usage_query.last_failure)

    def test_a_new_failure_replaces_the_old_one(self):
        self.script(usage="silent")
        self.trigger()
        self.finish()
        self.clock.advance(seconds=30)
        self.rearm(usage="error", message="boom")
        self.trigger()
        failure = self.finish().usage_query.last_failure
        self.assertEqual((failure.failure, failure.message), (QueryFailure.REPORTED_ERROR, "boom"))


class SwitchDuringQueryTest(AsyncQueryTestCase):
    def test_reading_belongs_to_the_account_id_in_the_usage_cache(self):
        self.log_in(refresh="rt-w", account_uuid="acct-1")
        self.core.add("work")
        self.log_in(refresh="rt-p", account_uuid="acct-2")
        self.core.add("play")
        self.log_in(refresh="rt-w", account_uuid="acct-1")
        self.write_cache(fetched_at=NOW)
        self.core.poll()
        # 查詢是以 acct-1 的身分發出的；進行中使用者切到 acct-2，查詢寫回的讀數仍是 acct-1 的
        cache = claude_json(usage_cache(fetched_at=LATER, account_uuid="acct-1"), oauth="acct-2")
        self.script(cache_text=json.dumps(cache))
        self.assertTrue(self.trigger())
        self.log_in(refresh="rt-p", account_uuid="acct-2")
        self.assertTrue(self.core.poll().usage_query.in_progress)
        cards = {c.account_key: c for c in self.finish().cards}
        self.assertEqual(cards["claude:play"].role, Role.ACTIVE)
        self.assertEqual(cards["claude:play"].reading_state, ReadingState.PENDING)  # 新讀數不算到 acct-2 身上
        self.assertEqual(cards["claude:work"].reading_state, ReadingState.HAS_READING)
        self.assertEqual(cards["claude:work"].reading_age, NOW - LATER)  # 算到 acct-1


class RestartTest(AsyncQueryTestCase):
    def test_query_status_starts_over_after_restart(self):
        self.script(usage="silent")
        self.trigger()
        board = self.finish()
        self.assertIsNotNone(board.usage_query.last_failure)
        self.assertTrue(board.usage_query.cooling_down)
        self.start()
        status = self.core.poll().usage_query
        self.assertEqual((status.in_progress, status.cooling_down, status.last_failure), (False, False, None))


if __name__ == "__main__":
    unittest.main()
