"""縫 ④：納管目錄 module 的 interface。用暫存目錄建立真實的納管目錄，注入故障，只看回傳值與檔案內容。"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from cc_quota_tracker import claude_provider as provider
from cc_quota_tracker.managed_directory import ManagedDirectory, Observed
from tests.fakehome import HomeTestCase, WindowsAclAssertions, usage_cache

AT = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class ManagedDirectoryTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "managed"
        self.managed = ManagedDirectory(self.path)
        self.observed_file = self.path / ".state" / "observed.json"
        self.switch_log = self.path / ".state" / "switches.jsonl"

    def put(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class ReadObservedTest(ManagedDirectoryTestCase):
    def test_missing_file_reads_as_nothing(self):
        self.assertEqual(self.managed.read_observed(), Observed())

    def test_unparsable_content_reads_as_nothing(self):
        self.put(self.observed_file, "{broken")
        self.assertEqual(self.managed.read_observed(), Observed())

    def test_content_that_is_not_an_object_reads_as_nothing(self):
        self.put(self.observed_file, "[1, 2]")
        self.assertEqual(self.managed.read_observed(), Observed())

    def test_locked_file_reads_as_unknown(self):
        self.put(self.observed_file, json.dumps({"fingerprint": "fp-1"}))
        with HomeTestCase.locked("observed.json"):
            self.assertIsNone(self.managed.read_observed())

    def test_fields_of_the_wrong_type_read_as_nothing(self):
        self.put(self.observed_file, json.dumps({"fingerprint": 5, "invalidSnapshot": ""}))
        self.assertEqual(self.managed.read_observed(), Observed())

    def test_written_observation_reads_back(self):
        self.managed.write_observed(AT, Observed("fp-1", "fp-0"))
        self.assertEqual(self.managed.read_observed(), Observed("fp-1", "fp-0"))
        self.assertEqual(json.loads(self.observed_file.read_text(encoding="utf-8")),
                         {"lastRunAt": AT.isoformat(), "fingerprint": "fp-1", "invalidSnapshot": "fp-0"})

    def test_existing_file_with_the_last_run_time_is_readable(self):
        self.put(self.observed_file, json.dumps({"lastRunAt": "2026-01-01T12:00:00+00:00",
                                                 "fingerprint": "fp-1", "invalidSnapshot": None}, indent=2))
        self.assertEqual(self.managed.read_observed(), Observed("fp-1", None))


class WriteObservedTest(ManagedDirectoryTestCase):
    def test_failed_write_raises_and_keeps_the_previous_observation(self):
        self.managed.write_observed(AT, Observed("fp-1"))
        before = self.observed_file.read_bytes()
        with mock.patch("cc_quota_tracker.atomic.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(OSError):
                self.managed.write_observed(AT, Observed("fp-2"))
        self.assertEqual(self.observed_file.read_bytes(), before)
        self.assertEqual(list(self.observed_file.parent.glob("*.tmp")), [])


class AppendSwitchTest(ManagedDirectoryTestCase):
    def lines(self):
        return [json.loads(line) for line in self.switch_log.read_text(encoding="utf-8").splitlines()]

    def test_creates_the_directories_and_the_first_line(self):
        self.managed.append_switch(AT, "acct-1")
        self.assertEqual(self.lines(), [{"at": AT.isoformat(), "accountId": "acct-1", "source": "observed"}])

    def test_unknown_account_is_recorded_as_null(self):
        self.managed.append_switch(AT, None)
        self.assertEqual([line["accountId"] for line in self.lines()], [None])

    def test_only_appends_and_leaves_existing_lines_untouched(self):
        self.managed.append_switch(AT, "acct-1")
        before = self.switch_log.read_bytes()
        self.managed.append_switch(AT, "acct-2")
        after = self.switch_log.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertEqual([line["accountId"] for line in self.lines()], ["acct-1", "acct-2"])

    def test_failed_append_raises_and_keeps_existing_lines(self):
        self.managed.append_switch(AT, "acct-1")
        before = self.switch_log.read_bytes()
        real = open

        def locked_open(file, mode="r", *args, **kwargs):
            if Path(file).name == "switches.jsonl" and "a" in mode:
                raise PermissionError("locked by another process")
            return real(file, mode, *args, **kwargs)
        with mock.patch("builtins.open", locked_open):
            with self.assertRaises(OSError):
                self.managed.append_switch(AT, "acct-2")
        self.assertEqual(self.switch_log.read_bytes(), before)

    def test_failed_first_write_raises_and_leaves_no_file_behind(self):
        with mock.patch("cc_quota_tracker.atomic.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(OSError):
                self.managed.append_switch(AT, "acct-1")
        self.assertFalse(self.switch_log.exists())
        self.assertEqual(list(self.switch_log.parent.glob("*.tmp")), [])


class ReadWindowPositionTest(ManagedDirectoryTestCase):
    def setUp(self):
        super().setUp()
        self.position_file = self.path / ".state" / "window.json"

    def test_missing_file_reads_as_nothing(self):
        self.assertIsNone(self.managed.read_window_position())

    def test_file_written_before_the_move_into_the_module_is_readable(self):
        self.put(self.position_file, json.dumps({"x": 321, "y": -123}))
        self.assertEqual(self.managed.read_window_position(), (321, -123))

    def test_unparsable_content_reads_as_nothing(self):
        self.put(self.position_file, "nonsense")
        self.assertIsNone(self.managed.read_window_position())

    def test_content_that_is_not_an_object_reads_as_nothing(self):
        self.put(self.position_file, "[1, 2]")
        self.assertIsNone(self.managed.read_window_position())

    def test_missing_or_wrongly_typed_coordinates_read_as_nothing(self):
        for content in ({"x": 1}, {"y": 1}, {"x": "1", "y": 2}, {"x": 1.5, "y": 2}, {"x": True, "y": 2}, {"x": None, "y": 2}):
            with self.subTest(content=content):
                self.put(self.position_file, json.dumps(content))
                self.assertIsNone(self.managed.read_window_position())

    def test_locked_file_reads_as_nothing(self):
        self.put(self.position_file, json.dumps({"x": 1, "y": 2}))
        with HomeTestCase.locked("window.json"):
            self.assertIsNone(self.managed.read_window_position())


class WriteWindowPositionTest(ManagedDirectoryTestCase):
    def setUp(self):
        super().setUp()
        self.state_dir = self.path / ".state"
        self.position_file = self.state_dir / "window.json"

    def stored(self):
        return json.loads(self.position_file.read_text(encoding="utf-8"))

    def test_state_directory_not_there_yet_remembers_nothing_and_creates_nothing(self):
        self.assertFalse(self.managed.write_window_position(10, 20))
        self.assertFalse(self.path.exists())

    def test_written_position_reads_back(self):
        self.state_dir.mkdir(parents=True)
        self.assertTrue(self.managed.write_window_position(321, 123))
        self.assertEqual(self.stored(), {"x": 321, "y": 123})
        self.assertEqual(self.managed.read_window_position(), (321, 123))

    def test_failed_replace_remembers_nothing_and_keeps_the_previous_position(self):
        self.state_dir.mkdir(parents=True)
        self.managed.write_window_position(1, 2)
        before = self.position_file.read_bytes()
        with mock.patch("cc_quota_tracker.atomic.os.replace", side_effect=PermissionError("locked")):
            self.assertFalse(self.managed.write_window_position(3, 4))
        self.assertEqual(self.position_file.read_bytes(), before)
        self.assertEqual(list(self.state_dir.glob("*.tmp")), [])

    def test_permissions_that_cannot_be_tightened_remember_nothing(self):
        self.state_dir.mkdir(parents=True)
        with mock.patch("cc_quota_tracker.managed_directory.make_private"), \
                mock.patch("cc_quota_tracker.managed_directory.is_private", return_value=False):
            self.assertFalse(self.managed.write_window_position(3, 4))
        self.assertFalse(self.position_file.exists())
        self.assertEqual(list(self.state_dir.glob("*.tmp")), [])

    def test_retry_after_a_failure_remembers_the_new_position(self):
        self.state_dir.mkdir(parents=True)
        with mock.patch("cc_quota_tracker.atomic.os.replace", side_effect=PermissionError("locked")):
            self.managed.write_window_position(3, 4)
        self.assertTrue(self.managed.write_window_position(3, 4))
        self.assertEqual(self.stored(), {"x": 3, "y": 4})


def reading(account_id, **cache):
    """像 Claude Code 寫進額度快取那樣的讀數；source 是解析來源，存進讀數檔的就是它。"""
    result = provider.parse_cache(usage_cache(account_uuid=account_id, **cache))
    assert isinstance(result, provider.UsageReading)
    return result


class StandbyReadingsTestCase(ManagedDirectoryTestCase):
    def setUp(self):
        super().setUp()
        self.readings_file = self.path / ".state" / "readings.json"

    def stored(self):
        return json.loads(self.readings_file.read_text(encoding="utf-8"))


class ReadStandbyReadingsTest(StandbyReadingsTestCase):
    def test_missing_file_reads_as_empty(self):
        self.assertEqual(self.managed.read_standby_readings(), {})

    def test_unparsable_content_reads_as_empty(self):
        self.put(self.readings_file, "{broken")
        self.assertEqual(self.managed.read_standby_readings(), {})

    def test_content_that_is_not_an_object_reads_as_empty(self):
        self.put(self.readings_file, "[1, 2]")
        self.assertEqual(self.managed.read_standby_readings(), {})

    def test_entries_that_cannot_be_parsed_are_left_out(self):
        self.put(self.readings_file, json.dumps({"acct-1": usage_cache(account_uuid="acct-1"), "acct-2": {"x": 1},
                                                 "acct-3": "nonsense"}))
        self.assertEqual(set(self.managed.read_standby_readings()), {"acct-1"})

    def test_file_written_before_the_move_into_the_module_is_readable(self):
        cache = usage_cache(account_uuid="acct-1", session=70)
        self.put(self.readings_file, json.dumps({"acct-1": cache}, indent=2))
        stored = self.managed.read_standby_readings()
        self.assertEqual(stored["acct-1"], provider.parse_cache(cache))
        self.assertEqual(stored["acct-1"].limits[0].percent, 70)

    def test_locked_file_reads_as_unknown(self):
        self.put(self.readings_file, json.dumps({"acct-1": usage_cache(account_uuid="acct-1")}))
        with HomeTestCase.locked("readings.json"):
            self.assertIsNone(self.managed.read_standby_readings())

    def test_a_lock_that_is_gone_reads_the_file_next_time(self):
        self.put(self.readings_file, json.dumps({"acct-1": usage_cache(account_uuid="acct-1")}))
        with HomeTestCase.locked("readings.json"):
            self.managed.read_standby_readings()
        self.assertEqual(set(self.managed.read_standby_readings()), {"acct-1"})

    def test_file_is_read_once_and_the_module_keeps_the_readings(self):
        self.put(self.readings_file, json.dumps({"acct-1": usage_cache(account_uuid="acct-1")}))
        self.managed.read_standby_readings()
        with HomeTestCase.locked("readings.json"):
            self.assertEqual(set(self.managed.read_standby_readings()), {"acct-1"})


class RememberStandbyReadingTest(StandbyReadingsTestCase):
    def test_remembered_reading_is_written_in_the_existing_format_and_reads_back(self):
        r = reading("acct-1", session=33)
        self.managed.remember_standby_reading(r, {"acct-1"})
        self.assertEqual(self.stored(), {"acct-1": usage_cache(account_uuid="acct-1", session=33)})
        self.assertEqual(self.managed.read_standby_readings(), {"acct-1": r})
        self.assertEqual(ManagedDirectory(self.path).read_standby_readings(), {"acct-1": r})  # 重新啟動後

    def test_reading_of_an_account_without_a_binding_is_not_remembered(self):
        self.managed.remember_standby_reading(reading("acct-x"), {"acct-1"})
        self.assertFalse(self.readings_file.exists())

    def test_same_reading_again_does_not_write(self):
        r = reading("acct-1")
        self.managed.remember_standby_reading(r, {"acct-1"})
        with mock.patch("cc_quota_tracker.atomic.os.replace", side_effect=PermissionError("locked")):
            self.managed.remember_standby_reading(r, {"acct-1"})  # 要寫就會丟例外

    def test_remembering_keeps_only_bound_accounts(self):
        self.put(self.readings_file, json.dumps({"acct-1": usage_cache(account_uuid="acct-1"),
                                                 "acct-gone": usage_cache(account_uuid="acct-gone")}))
        self.managed.remember_standby_reading(reading("acct-2"), {"acct-1", "acct-2"})
        self.assertEqual(set(self.stored()), {"acct-1", "acct-2"})

    def test_locked_file_writes_nothing_and_leaves_the_bytes_untouched(self):
        self.put(self.readings_file, json.dumps({"acct-1": usage_cache(account_uuid="acct-1")}))
        before = self.readings_file.read_bytes()
        with HomeTestCase.locked("readings.json"):
            self.managed.remember_standby_reading(reading("acct-2"), {"acct-1", "acct-2"})
        self.assertEqual(self.readings_file.read_bytes(), before)
        self.assertEqual(list(self.readings_file.parent.glob("*.tmp")), [])

    def test_failed_write_raises_and_keeps_the_file_as_it_was(self):
        self.managed.remember_standby_reading(reading("acct-1", session=1), {"acct-1", "acct-2"})
        before = self.readings_file.read_bytes()
        with mock.patch("cc_quota_tracker.atomic.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(OSError):
                self.managed.remember_standby_reading(reading("acct-2"), {"acct-1", "acct-2"})
        self.assertEqual(self.readings_file.read_bytes(), before)
        self.assertEqual(list(self.readings_file.parent.glob("*.tmp")), [])

    def test_failed_write_is_tried_again_next_time(self):
        r = reading("acct-1")
        with mock.patch("cc_quota_tracker.atomic.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(OSError):
                self.managed.remember_standby_reading(r, {"acct-1"})
        self.managed.remember_standby_reading(r, {"acct-1"})
        self.assertEqual(set(self.stored()), {"acct-1"})


class PruneStandbyReadingsTest(StandbyReadingsTestCase):
    def test_readings_of_accounts_no_longer_bound_are_dropped(self):
        self.put(self.readings_file, json.dumps({"acct-1": usage_cache(account_uuid="acct-1"),
                                                 "acct-2": usage_cache(account_uuid="acct-2")}))
        self.managed.prune_standby_readings({"acct-2"})
        self.assertEqual(set(self.stored()), {"acct-2"})
        self.assertEqual(set(self.managed.read_standby_readings()), {"acct-2"})

    def test_nothing_to_drop_does_not_write(self):
        self.put(self.readings_file, json.dumps({"acct-1": usage_cache(account_uuid="acct-1")}))
        before = self.readings_file.read_bytes()
        with mock.patch("cc_quota_tracker.atomic.os.replace", side_effect=PermissionError("locked")):
            self.managed.prune_standby_readings({"acct-1", "acct-2"})
        self.assertEqual(self.readings_file.read_bytes(), before)

    def test_locked_file_is_not_pruned(self):
        self.put(self.readings_file, json.dumps({"acct-1": usage_cache(account_uuid="acct-1")}))
        before = self.readings_file.read_bytes()
        with HomeTestCase.locked("readings.json"):
            self.managed.prune_standby_readings(set())
        self.assertEqual(self.readings_file.read_bytes(), before)


@unittest.skipUnless(sys.platform == "win32", "Windows ACL")
class StandbyReadingsPermissionTest(StandbyReadingsTestCase, WindowsAclAssertions):
    def test_readings_file_is_private(self):
        self.managed.remember_standby_reading(reading("acct-1"), {"acct-1"})
        self.assert_private(self.readings_file)


@unittest.skipUnless(sys.platform == "win32", "Windows ACL")
class WindowPositionPermissionTest(ManagedDirectoryTestCase, WindowsAclAssertions):
    def test_position_file_is_private(self):
        self.managed.write_observed(AT, Observed())  # 工具狀態目錄由其他寫入建立並收緊
        self.assertTrue(self.managed.write_window_position(5, 6))
        self.assert_private(self.path / ".state" / "window.json")


if __name__ == "__main__":
    unittest.main()
