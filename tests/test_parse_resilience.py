import os
import unittest
from datetime import timedelta
from unittest import mock

from cc_quota_tracker.board import ReadingState
from cc_quota_tracker.render_text import render
from tests.fakehome import NOW, HomeTestCase, usage_cache

OBSERVED = NOW - timedelta(minutes=10)


class ParseResilienceTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self._mtime = 10 ** 18

    def write(self, data):
        self.write_claude_json(data)
        self._touch()

    def write_text(self, text):
        (self.home / ".claude.json").write_text(text, encoding="utf-8")
        self._touch()

    def _touch(self):
        # 每次寫入都給新的修改時間（跨一整秒，NTFS 解析度只有 100 ns）
        self._mtime += 10 ** 9
        os.utime(self.home / ".claude.json", ns=(1, self._mtime))

    def write_good(self, session=33):
        self.write({"cachedUsageUtilization": usage_cache(fetched_at=OBSERVED, session=session)})

    def write_limits_not_a_list(self):
        cache = usage_cache()
        cache["utilization"]["limits"] = {"kind": "session"}
        self.write({"cachedUsageUtilization": cache})

    def test_schema_change_lights_on_third_round_with_last_reading(self):
        self.write_good(session=33)
        self.core.poll()
        self.write_limits_not_a_list()
        boards = [self.core.poll() for _ in range(3)]
        self.assertEqual([b.schema_changed for b in boards], [False, False, True])
        board = boards[-1]
        self.assertEqual(board.last_reading_at, OBSERVED)
        card = board.cards[0]
        self.assertEqual(card.reading_state, ReadingState.HAS_READING)
        self.assertEqual(card.limits[0].percent, 33)

    def test_render_schema_change_banner_with_reading_time(self):
        self.write_good(session=33)
        self.core.poll()
        self.write_limits_not_a_list()
        self.core.poll()
        self.assertNotIn("結構已變更", render(self.core.poll()))
        text = render(self.core.poll())
        self.assertIn("額度快取結構已變更", text)
        self.assertIn(OBSERVED.astimezone().strftime("%Y-%m-%d %H:%M"), text)
        self.assertIn("工作階段窗口  33%", text)

    def test_element_missing_kind_is_schema_mismatch(self):
        self.write_good()
        self.core.poll()
        cache = usage_cache()
        del cache["utilization"]["limits"][0]["kind"]
        self.write({"cachedUsageUtilization": cache})
        self.assertEqual([self.core.poll().schema_changed for _ in range(3)], [False, False, True])

    def test_occasional_mismatch_does_not_light_banner(self):
        self.write_good()
        self.core.poll()
        for _ in range(3):
            self.write_limits_not_a_list()
            self.core.poll()
            self.core.poll()
            self.write_good()
            self.assertFalse(self.core.poll().schema_changed)

    def test_banner_clears_when_structure_recovers(self):
        self.write_good()
        self.write_limits_not_a_list()
        for _ in range(3):
            board = self.core.poll()
        self.assertTrue(board.schema_changed)
        self.write_good(session=44)
        board = self.core.poll()
        self.assertFalse(board.schema_changed)
        self.assertEqual(board.cards[0].limits[0].percent, 44)

    def test_truncated_json_keeps_previous_reading_without_banner(self):
        self.write_good(session=33)
        self.core.poll()
        self.write_text('{"cachedUsageUtilization": {"fetchedAtMs": 1')
        for _ in range(5):
            board = self.core.poll()
            self.assertFalse(board.schema_changed)
            self.assertEqual(board.cards[0].limits[0].percent, 33)
            self.assertEqual(board.last_reading_at, OBSERVED)

    def test_truncated_read_does_not_reset_mismatch_count(self):
        self.write_good()
        self.core.poll()
        self.write_limits_not_a_list()
        self.core.poll()
        self.core.poll()
        self.write_text('{"cachedUsageUtil')
        self.assertFalse(self.core.poll().schema_changed)
        self.write_limits_not_a_list()
        self.assertTrue(self.core.poll().schema_changed)

    def test_truncated_file_is_reread_even_if_modification_time_does_not_change(self):
        # 讀到寫入中的檔案時，寫完的內容可能落在同一個修改時間
        self.write_good(session=33)
        self.core.poll()
        self.write_text('{"cachedUsageUtil')
        self.core.poll()
        mtime = (self.home / ".claude.json").stat().st_mtime_ns
        self.write_claude_json({"cachedUsageUtilization": usage_cache(session=55)})
        os.utime(self.home / ".claude.json", ns=(1, mtime))
        self.assertEqual(self.core.poll().cards[0].limits[0].percent, 55)

    def test_occasional_read_failure_keeps_previous_reading_without_banner(self):
        self.write_good(session=33)
        self.core.poll()
        self.write_good(session=44)
        with mock.patch("pathlib.Path.read_text", side_effect=PermissionError):
            board = self.core.poll()
        self.assertFalse(board.schema_changed)
        self.assertEqual(board.cards[0].limits[0].percent, 33)
        self.assertEqual(self.core.poll().cards[0].limits[0].percent, 44)

    def test_occasional_stat_failure_keeps_previous_reading(self):
        # 檔案暫時被鎖（防毒、索引服務）不等於額度快取不存在
        self.write_good(session=33)
        self.core.poll()
        with mock.patch("os.stat", side_effect=PermissionError):
            board = self.core.poll()
        self.assertEqual(board.cards[0].reading_state, ReadingState.HAS_READING)
        self.assertEqual(board.cards[0].limits[0].percent, 33)

    def test_deleted_file_is_no_reading(self):
        self.write_good()
        self.core.poll()
        (self.home / ".claude.json").unlink()
        self.assertEqual(self.core.poll().cards[0].reading_state, ReadingState.NO_READING)

    def test_removed_usage_cache_is_no_reading_without_banner(self):
        self.write_good()
        self.core.poll()
        self.write_limits_not_a_list()
        self.core.poll()
        self.core.poll()
        self.write({"oauthAccount": {}})
        for _ in range(3):
            board = self.core.poll()
            self.assertFalse(board.schema_changed)
            self.assertEqual(board.cards[0].reading_state, ReadingState.NO_READING)
            self.assertIsNone(board.last_reading_at)
        self.write_limits_not_a_list()
        self.assertFalse(self.core.poll().schema_changed)

    def test_unchanged_file_is_not_parsed_again(self):
        self.write_good(session=33)
        self.core.poll()
        mtime = (self.home / ".claude.json").stat().st_mtime_ns
        self.write_claude_json({"cachedUsageUtilization": usage_cache(session=55)})
        os.utime(self.home / ".claude.json", ns=(1, mtime))
        self.assertEqual(self.core.poll().cards[0].limits[0].percent, 33)


if __name__ == "__main__":
    unittest.main()
