"""縫 ④：納管目錄 module 的 interface。用暫存目錄建立真實的納管目錄，注入故障，只看回傳值與檔案內容。"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from cc_quota_tracker.managed_directory import ManagedDirectory, Observed
from tests.fakehome import HomeTestCase

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


if __name__ == "__main__":
    unittest.main()
