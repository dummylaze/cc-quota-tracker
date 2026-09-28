import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

from cc_quota_tracker.__main__ import main
from cc_quota_tracker.board import ReadingState, Role
from cc_quota_tracker.render_text import render
from tests.fakehome import HomeTestCase, NOW, usage_cache


class PollTest(HomeTestCase):
    def bump_mtime(self):
        os.utime(self.home / ".claude.json", ns=(1, 2 ** 40))

    def test_no_cache_file_is_no_reading(self):
        card = self.core.poll().cards[0]
        self.assertEqual(card.role, Role.ACTIVE)
        self.assertEqual(card.reading_state, ReadingState.NO_READING)
        self.assertEqual(card.limits, ())

    def test_missing_cached_usage_key_is_no_reading(self):
        self.write_claude_json({"oauthAccount": {}})
        self.assertEqual(self.core.poll().cards[0].reading_state, ReadingState.NO_READING)

    def test_reads_session_and_weekly_windows(self):
        self.write_claude_json({"cachedUsageUtilization": usage_cache(session=12, weekly=75)})
        card = self.core.poll().cards[0]
        self.assertEqual(card.reading_state, ReadingState.HAS_READING)
        self.assertEqual({w.kind: w.percent for w in card.limits}, {"session": 12, "weekly_all": 75})
        self.assertEqual(card.limits[0].resets_at, NOW + timedelta(days=3))

    def test_reset_time_with_z_suffix_is_read_as_utc(self):
        cache = usage_cache()
        for limit in cache["utilization"]["limits"]:
            limit["resets_at"] = "2026-01-04T12:00:00Z"
        self.write_claude_json({"cachedUsageUtilization": cache})
        self.assertEqual(self.core.poll().cards[0].limits[0].resets_at, NOW + timedelta(days=3))

    def test_reading_age_follows_clock(self):
        self.write_claude_json({"cachedUsageUtilization": usage_cache(fetched_at=NOW - timedelta(minutes=15))})
        self.assertEqual(self.core.poll().cards[0].reading_age, timedelta(minutes=15))
        self.clock.advance(minutes=5)
        self.assertEqual(self.core.poll().cards[0].reading_age, timedelta(minutes=20))

    def test_picks_up_changes_between_polls(self):
        self.write_claude_json({"cachedUsageUtilization": usage_cache(session=1)})
        self.core.poll()
        self.write_claude_json({"cachedUsageUtilization": usage_cache(session=2)})
        self.bump_mtime()
        self.assertEqual(self.core.poll().cards[0].limits[0].percent, 2)

    def test_truncated_json_keeps_previous_reading(self):
        self.write_claude_json({"cachedUsageUtilization": usage_cache(session=33)})
        self.core.poll()
        (self.home / ".claude.json").write_text('{"cachedUsageUtil', encoding="utf-8")
        self.bump_mtime()
        card = self.core.poll().cards[0]
        self.assertEqual(card.reading_state, ReadingState.HAS_READING)
        self.assertEqual(card.limits[0].percent, 33)

    def test_poll_does_not_modify_claude_json(self):
        self.write_claude_json({"cachedUsageUtilization": usage_cache()})
        path = self.home / ".claude.json"
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        self.core.poll()
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)


class ListTest(HomeTestCase):
    def test_render_no_reading(self):
        self.assertIn("尚無讀數", render(self.core.poll()))

    def test_render_windows(self):
        self.write_claude_json({"cachedUsageUtilization": usage_cache(session=12, weekly=75)})
        text = render(self.core.poll())
        self.assertIn("工作階段窗口  12%", text)
        self.assertIn("週窗口  75%", text)

    def test_list_command_prints_board(self):
        # list 用真實時鐘：重置時間要落在真實的未來，否則會正確地顯示為無計時中窗口
        later = datetime.now(timezone.utc) + timedelta(days=3)
        self.write_claude_json({"cachedUsageUtilization": usage_cache(weekly=61, resets_at=later)})
        out = io.StringIO()
        with mock.patch("pathlib.Path.home", return_value=self.home), redirect_stdout(out):
            self.assertEqual(main(["list"]), 0)
        self.assertIn("週窗口  61%", out.getvalue())


if __name__ == "__main__":
    unittest.main()
