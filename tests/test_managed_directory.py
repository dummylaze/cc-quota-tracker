"""縫 ④：納管目錄 module 的 interface。用暫存目錄建立真實的納管目錄，注入故障，只看回傳值與檔案內容。"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from cc_quota_tracker import claude_provider as provider
from cc_quota_tracker.managed_directory import (BindingsUnreadable, InvalidLabel, ManagedAccount, ManagedDirectory,
                                                NoCredential, Observed, Stored, UnknownLabel)
from tests.fakehome import HomeTestCase, WindowsAclAssertions, usage_cache

AT = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
KEY_RT1 = "a33d8c625833429d"  # refreshToken "rt-1" 的憑證指紋，事先算好的字面值
KEY_RT2 = "1f23b7dadfb229cb"  # refreshToken "rt-2"


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

    def test_permissions_that_cannot_be_tightened_still_remember_the_position(self):
        self.state_dir.mkdir(parents=True)
        with mock.patch("cc_quota_tracker.managed_directory.make_private"), \
                mock.patch("cc_quota_tracker.managed_directory.is_private", return_value=False):
            self.assertTrue(self.managed.write_window_position(3, 4))
        self.assertEqual(self.stored(), {"x": 3, "y": 4})

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


class StandbyLaggingTest(StandbyReadingsTestCase):
    """待命讀數的落後標記：與讀數存在同一個檔案，標的是「哪一個觀測時間的讀數」，讀數換了標記就不再成立。"""

    def remember(self, account_id="acct-1", **cache):
        self.managed.remember_standby_reading(reading(account_id, **cache), {"acct-1", "acct-2"})

    def test_no_mark_means_not_lagging(self):
        self.remember()
        self.assertFalse(self.managed.standby_lagging("acct-1"))
        self.assertFalse(self.managed.standby_lagging("acct-unknown"))

    def test_marked_reading_is_lagging_and_stays_so_after_a_restart(self):
        self.remember()
        self.managed.mark_standby_lagging("acct-1", True)
        self.assertTrue(self.managed.standby_lagging("acct-1"))
        self.assertTrue(ManagedDirectory(self.path).standby_lagging("acct-1"))
        self.assertFalse(self.managed.standby_lagging("acct-2"))

    def test_the_mark_can_be_cleared(self):
        self.remember()
        self.managed.mark_standby_lagging("acct-1", True)
        self.managed.mark_standby_lagging("acct-1", False)
        self.assertFalse(ManagedDirectory(self.path).standby_lagging("acct-1"))
        self.assertEqual(set(self.stored()), {"acct-1"})  # 沒有標記時檔案維持原本的格式

    def test_a_reading_that_is_not_stored_cannot_be_marked(self):
        self.managed.mark_standby_lagging("acct-1", True)
        self.assertFalse(self.readings_file.exists())
        self.assertFalse(self.managed.standby_lagging("acct-1"))

    def test_a_file_without_the_field_reads_as_not_lagging(self):
        self.put(self.readings_file, json.dumps({"acct-1": usage_cache(account_uuid="acct-1")}))
        self.assertFalse(self.managed.standby_lagging("acct-1"))

    def test_the_mark_is_not_mistaken_for_an_account(self):
        self.remember()
        self.managed.mark_standby_lagging("acct-1", True)
        self.assertEqual(set(ManagedDirectory(self.path).read_standby_readings()), {"acct-1"})

    def test_an_unreadable_field_reads_as_not_lagging(self):
        for junk in ("oops", [1], {"acct-1": 7}, {"acct-1": "not a time"}):
            with self.subTest(junk=junk):
                self.put(self.readings_file, json.dumps({"acct-1": usage_cache(account_uuid="acct-1"),
                                                         "_lagging": junk}))
                self.assertFalse(ManagedDirectory(self.path).standby_lagging("acct-1"))

    def test_a_newer_reading_for_the_same_account_clears_the_mark(self):
        self.remember()
        self.managed.mark_standby_lagging("acct-1", True)
        self.remember(fetched_at=AT.replace(minute=30))
        self.assertFalse(self.managed.standby_lagging("acct-1"))
        self.assertEqual(set(self.stored()), {"acct-1"})

    def test_marks_of_other_accounts_survive_a_new_reading(self):
        self.remember("acct-1")
        self.remember("acct-2")
        self.managed.mark_standby_lagging("acct-1", True)
        self.remember("acct-2", fetched_at=AT.replace(minute=30))
        self.assertTrue(self.managed.standby_lagging("acct-1"))

    def test_pruning_an_unbound_account_takes_its_mark_along(self):
        self.remember()
        self.managed.mark_standby_lagging("acct-1", True)
        self.managed.remember_standby_reading(reading("acct-2"), {"acct-2"})
        self.assertFalse(self.managed.standby_lagging("acct-1"))
        self.assertNotIn("_lagging", self.stored())

    def test_locked_file_writes_nothing(self):
        self.remember()
        before = self.readings_file.read_bytes()
        with HomeTestCase.locked("readings.json"):
            ManagedDirectory(self.path).mark_standby_lagging("acct-1", True)  # 重新啟動後第一次讀就被鎖住
        self.assertEqual(self.readings_file.read_bytes(), before)

    def test_failed_write_raises_and_the_mark_is_not_kept(self):
        self.remember()
        with mock.patch("cc_quota_tracker.atomic.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(OSError):
                self.managed.mark_standby_lagging("acct-1", True)
        self.assertFalse(self.managed.standby_lagging("acct-1"))
        self.assertEqual(set(self.stored()), {"acct-1"})


def credential(refresh, expires_at_ms=None):
    oauth = {"accessToken": "at", "refreshToken": refresh}
    if expires_at_ms is not None:
        oauth["refreshTokenExpiresAt"] = expires_at_ms
    return json.dumps({"claudeAiOauth": oauth})


class BindingsTestCase(StandbyReadingsTestCase):
    def setUp(self):
        super().setUp()
        self.bindings_file = self.path / ".state" / "bindings.json"

    def stored_bindings(self):
        return json.loads(self.bindings_file.read_text(encoding="utf-8"))

    def snapshot(self, label, refresh):
        self.put(self.path / f"{label}.json", credential(refresh))

    def put_bindings(self, **by_fingerprint):
        self.put(self.bindings_file, json.dumps({fp: {"accountId": a} for fp, a in by_fingerprint.items()}))

    def put_readings(self, *account_ids):
        self.put(self.readings_file, json.dumps({a: usage_cache(account_uuid=a) for a in account_ids}))

    def unreadable_snapshot(self, label):
        self.put(self.path / f"{label}.json", '{"claudeAiOauth": {"acc')  # 寫到一半或被防毒鎖住


class ListAccountsTest(BindingsTestCase):
    def test_no_directory_lists_nothing(self):
        self.assertEqual(self.managed.list_accounts(), ())

    def test_lists_each_label_with_its_fingerprint_binding_and_expiry(self):
        self.put(self.path / "work.json", credential("rt-1", 1_767_268_800_000))
        self.snapshot("home", "rt-2")
        self.put_bindings(**{KEY_RT1: "acct-1"})
        expires = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(self.managed.list_accounts(),
                         (ManagedAccount("home", KEY_RT2, None, None), ManagedAccount("work", KEY_RT1, "acct-1", expires)))

    def test_files_of_the_tool_itself_are_not_accounts(self):
        self.snapshot("work", "rt-1")
        self.snapshot(".hidden", "rt-2")
        (self.path / "folder.json").mkdir()
        self.assertEqual([a.label for a in self.managed.list_accounts()], ["work"])

    def test_snapshot_without_a_readable_fingerprint_is_listed_as_unknown(self):
        self.unreadable_snapshot("work")
        self.put_bindings(**{KEY_RT1: "acct-1"})
        self.assertEqual(self.managed.list_accounts(), (ManagedAccount("work", None, None, None),))

    def test_locked_bindings_file_lists_accounts_without_a_binding(self):
        self.snapshot("work", "rt-1")
        self.put_bindings(**{KEY_RT1: "acct-1"})
        with HomeTestCase.locked("bindings.json"):
            self.assertEqual(self.managed.list_accounts(), (ManagedAccount("work", KEY_RT1, None, None),))

    def test_binding_with_a_missing_or_wrongly_typed_account_id_is_no_binding(self):
        self.snapshot("work", "rt-1")
        self.snapshot("home", "rt-2")
        self.put(self.bindings_file, json.dumps({KEY_RT1: {"accountId": ""}, KEY_RT2: "acct-2"}))
        self.assertEqual([a.account_id for a in self.managed.list_accounts()], [None, None])

    def test_bindings_file_written_before_the_move_into_the_module_is_readable(self):
        self.snapshot("work", "rt-1")
        self.put(self.bindings_file, json.dumps({KEY_RT1: {"accountId": "acct-1"}}, indent=2))
        self.assertEqual(self.managed.list_accounts()[0].account_id, "acct-1")


class MaintainBindingsTest(BindingsTestCase):
    def test_learns_a_binding_for_a_snapshot_that_has_none(self):
        self.snapshot("work", "rt-1")
        self.assertTrue(self.managed.maintain_bindings((KEY_RT1, "acct-1")))
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}})
        self.assertEqual(self.managed.list_accounts()[0].account_id, "acct-1")

    def test_orphan_binding_is_removed(self):
        self.snapshot("work", "rt-1")
        self.put_bindings(**{KEY_RT1: "acct-1", KEY_RT2: "acct-2"})
        self.assertTrue(self.managed.maintain_bindings())
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}})

    def test_learning_and_cleaning_orphans_happen_in_one_write(self):
        self.snapshot("work", "rt-1")
        self.put_bindings(**{KEY_RT2: "acct-2"})
        self.assertTrue(self.managed.maintain_bindings((KEY_RT1, "acct-1")))
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}})

    def test_orphan_cleanup_drops_the_readings_of_accounts_that_lost_their_binding(self):
        self.snapshot("work", "rt-1")
        self.put_bindings(**{KEY_RT1: "acct-1", KEY_RT2: "acct-2"})
        self.put_readings("acct-1", "acct-2")
        self.managed.maintain_bindings()
        self.assertEqual(set(self.stored()), {"acct-1"})
        self.assertEqual(set(self.managed.read_standby_readings()), {"acct-1"})

    def test_readings_that_all_keep_their_binding_are_not_rewritten(self):
        self.snapshot("work", "rt-1")
        self.put_bindings(**{KEY_RT1: "acct-1", KEY_RT2: "acct-2"})
        self.put_readings("acct-1")
        readings_before = self.readings_file.read_bytes()
        real = os.replace

        def replace(src, dst):
            if Path(dst).name == "readings.json":
                raise PermissionError("locked")  # 要寫讀數檔就會丟例外
            real(src, dst)
        with mock.patch("cc_quota_tracker.atomic.os.replace", replace):
            self.managed.maintain_bindings()
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}})
        self.assertEqual(self.readings_file.read_bytes(), readings_before)

    def test_nothing_to_learn_or_clean_does_not_write(self):
        self.snapshot("work", "rt-1")
        self.put_bindings(**{KEY_RT1: "acct-1"})
        before = self.bindings_file.read_bytes()
        with mock.patch("cc_quota_tracker.atomic.os.replace", side_effect=PermissionError("locked")):
            self.assertFalse(self.managed.maintain_bindings())
        self.assertEqual(self.bindings_file.read_bytes(), before)

    def test_locked_bindings_file_writes_nothing_and_leaves_the_bytes_untouched(self):
        self.snapshot("work", "rt-1")
        self.put_bindings(**{KEY_RT1: "acct-1", KEY_RT2: "acct-2"})
        self.put_readings("acct-1", "acct-2")
        bindings_before, readings_before = self.bindings_file.read_bytes(), self.readings_file.read_bytes()
        with HomeTestCase.locked("bindings.json"):
            self.assertFalse(self.managed.maintain_bindings((KEY_RT1, "acct-3")))
            self.assertFalse(self.managed.maintain_bindings())
        self.assertEqual(self.bindings_file.read_bytes(), bindings_before)
        self.assertEqual(self.readings_file.read_bytes(), readings_before)
        self.assertEqual(list(self.bindings_file.parent.glob("*.tmp")), [])

    def test_snapshot_without_a_readable_fingerprint_prunes_and_learns_nothing(self):
        self.snapshot("work", "rt-1")
        self.unreadable_snapshot("home")
        self.put_bindings(**{KEY_RT1: "acct-1", KEY_RT2: "acct-2"})
        self.put_readings("acct-1", "acct-2")
        bindings_before, readings_before = self.bindings_file.read_bytes(), self.readings_file.read_bytes()
        self.assertFalse(self.managed.maintain_bindings((KEY_RT1, "acct-3")))
        self.assertFalse(self.managed.maintain_bindings())
        self.assertEqual(self.bindings_file.read_bytes(), bindings_before)
        self.assertEqual(self.readings_file.read_bytes(), readings_before)

    def test_unparsable_bindings_file_counts_as_empty_and_gets_the_new_binding(self):
        self.snapshot("work", "rt-1")
        self.put(self.bindings_file, "{broken")
        self.assertTrue(self.managed.maintain_bindings((KEY_RT1, "acct-1")))
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}})

    def test_failed_write_raises_and_keeps_the_bindings_as_they_were(self):
        self.snapshot("work", "rt-1")
        self.put_bindings(**{KEY_RT1: "acct-1", KEY_RT2: "acct-2"})
        before = self.bindings_file.read_bytes()
        with mock.patch("cc_quota_tracker.atomic.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(OSError):
                self.managed.maintain_bindings()
        self.assertEqual(self.bindings_file.read_bytes(), before)
        self.assertEqual(list(self.bindings_file.parent.glob("*.tmp")), [])


class StoreSnapshotTest(BindingsTestCase):
    def managed_files(self):
        return {p.relative_to(self.path): p.read_bytes() for p in self.path.rglob("*") if p.is_file()}

    def test_writes_the_snapshot_and_its_binding_and_reports_it_as_bound(self):
        data = credential("rt-1").encode("utf-8")
        stored = self.managed.store_snapshot("work", data, "acct-1")
        self.assertEqual(stored, Stored(bound=True, permissions_fixed=False))
        self.assertEqual((self.path / "work.json").read_bytes(), data)
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}})
        self.assertEqual(self.managed.list_accounts(), (ManagedAccount("work", KEY_RT1, "acct-1", None),))

    def test_without_an_account_id_the_existing_binding_of_that_fingerprint_stays(self):
        self.put_bindings(**{KEY_RT1: "acct-1", KEY_RT2: "acct-2"})
        stored = self.managed.store_snapshot("work", credential("rt-1").encode("utf-8"), None)
        self.assertTrue(stored.bound)
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}})  # 順帶清掉換掉的舊憑證指紋

    def test_without_an_account_id_and_no_binding_reports_not_bound_but_writes_the_file(self):
        stored = self.managed.store_snapshot("work", credential("rt-1").encode("utf-8"), None)
        self.assertFalse(stored.bound)
        self.assertEqual(self.stored_bindings(), {})

    def test_unparsable_bindings_file_counts_as_empty_and_gets_the_new_binding(self):
        self.put(self.bindings_file, "{broken")
        self.assertTrue(self.managed.store_snapshot("work", credential("rt-1").encode("utf-8"), "acct-1").bound)
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}})

    def test_replacing_a_snapshot_cleans_the_old_fingerprint_with_its_reading(self):
        self.snapshot("work", "rt-2")
        self.put_bindings(**{KEY_RT2: "acct-2"})
        self.put_readings("acct-2")
        self.managed.store_snapshot("work", credential("rt-1").encode("utf-8"), "acct-1")
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}})
        self.assertEqual(self.stored(), {})

    def test_label_that_is_not_a_plain_file_name_is_refused_before_anything_is_written(self):
        for label in ["", " ", "../work", "a/b", "a\\b", "a:b", ".hidden", "work.", "con", "NUL", "COM1.txt", "a*b"]:
            with self.subTest(label=label), self.assertRaises(InvalidLabel):
                self.managed.store_snapshot(label, credential("rt-1").encode("utf-8"), "acct-1")
        self.assertFalse(self.path.exists())

    def test_locked_bindings_file_refuses_and_leaves_every_file_untouched(self):
        self.snapshot("work", "rt-1")
        self.put_bindings(**{KEY_RT1: "acct-1"})
        self.put_readings("acct-1")
        before = self.managed_files()
        with HomeTestCase.locked("bindings.json"), self.assertRaises(BindingsUnreadable) as raised:
            self.managed.store_snapshot("work", credential("rt-2").encode("utf-8"), "acct-2")
        self.assertEqual(raised.exception.path, self.bindings_file)
        self.assertEqual(self.managed_files(), before)

    def test_credential_without_a_fingerprint_keeps_the_existing_snapshot(self):
        self.managed.store_snapshot("work", credential("rt-1").encode("utf-8"), "acct-1")
        before = self.managed_files()
        with self.assertRaises(NoCredential):
            self.managed.store_snapshot("work", b'{"claudeAiOauth": {"acc', "acct-1")
        self.assertEqual(self.managed_files(), before)

    def test_snapshot_without_a_readable_fingerprint_only_adds_the_new_binding(self):
        self.unreadable_snapshot("home")
        self.put_bindings(**{KEY_RT2: "acct-2"})
        self.put_readings("acct-2")
        self.managed.store_snapshot("work", credential("rt-1").encode("utf-8"), "acct-1")
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}, KEY_RT2: {"accountId": "acct-2"}})
        self.assertEqual(set(self.stored()), {"acct-2"})

    def test_locked_readings_file_still_writes_the_binding_but_prunes_no_readings(self):
        self.put_bindings(**{KEY_RT2: "acct-2"})
        self.put_readings("acct-2")
        readings_before = self.readings_file.read_bytes()
        with HomeTestCase.locked("readings.json"):
            self.managed.store_snapshot("work", credential("rt-1").encode("utf-8"), "acct-1")
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}})
        self.assertEqual(self.readings_file.read_bytes(), readings_before)

    def test_failed_bindings_write_raises_and_keeps_the_bindings_as_they_were(self):
        self.put_bindings(**{KEY_RT2: "acct-2"})
        before = self.bindings_file.read_bytes()
        real = os.replace

        def replace(src, dst):
            if Path(dst).name == "bindings.json":
                raise PermissionError("locked")
            real(src, dst)
        with mock.patch("cc_quota_tracker.atomic.os.replace", replace), self.assertRaises(OSError):
            self.managed.store_snapshot("work", credential("rt-1").encode("utf-8"), "acct-1")
        self.assertEqual(self.bindings_file.read_bytes(), before)


class RemoveSnapshotTest(BindingsTestCase):
    def setUp(self):
        super().setUp()
        self.snapshot("work", "rt-1")
        self.snapshot("home", "rt-2")
        self.put_bindings(**{KEY_RT1: "acct-1", KEY_RT2: "acct-2"})
        self.put_readings("acct-1", "acct-2")

    def test_deletes_the_snapshot_with_its_binding_and_reading(self):
        self.managed.remove_snapshot("home")
        self.assertFalse((self.path / "home.json").exists())
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}})
        self.assertEqual(set(self.stored()), {"acct-1"})

    def test_unknown_label_is_refused_and_changes_nothing(self):
        bindings_before = self.bindings_file.read_bytes()
        with self.assertRaises(UnknownLabel):
            self.managed.remove_snapshot("other")
        self.assertEqual([a.label for a in self.managed.list_accounts()], ["home", "work"])
        self.assertEqual(self.bindings_file.read_bytes(), bindings_before)

    def test_locked_bindings_file_deletes_the_snapshot_and_writes_nothing_else(self):
        bindings_before, readings_before = self.bindings_file.read_bytes(), self.readings_file.read_bytes()
        with HomeTestCase.locked("bindings.json"):
            self.managed.remove_snapshot("home")
        self.assertFalse((self.path / "home.json").exists())
        self.assertEqual(self.bindings_file.read_bytes(), bindings_before)
        self.assertEqual(self.readings_file.read_bytes(), readings_before)

    def test_snapshot_without_a_readable_fingerprint_prunes_nothing(self):
        with HomeTestCase.locked("work.json"):
            self.managed.remove_snapshot("home")
        self.assertFalse((self.path / "home.json").exists())
        self.assertEqual(set(self.stored_bindings()), {KEY_RT1, KEY_RT2})
        self.assertEqual(set(self.stored()), {"acct-1", "acct-2"})

    def test_locked_readings_file_still_writes_the_bindings_but_prunes_no_readings(self):
        readings_before = self.readings_file.read_bytes()
        with HomeTestCase.locked("readings.json"):
            self.managed.remove_snapshot("home")
        self.assertEqual(self.stored_bindings(), {KEY_RT1: {"accountId": "acct-1"}})
        self.assertEqual(self.readings_file.read_bytes(), readings_before)


@unittest.skipUnless(sys.platform == "win32", "Windows ACL")
class StandbyReadingsPermissionTest(StandbyReadingsTestCase, WindowsAclAssertions):
    def test_readings_file_is_private(self):
        self.managed.remember_standby_reading(reading("acct-1"), {"acct-1"})
        self.assert_private(self.readings_file)


@unittest.skipUnless(sys.platform == "win32", "Windows ACL")
class BindingsPermissionTest(BindingsTestCase, WindowsAclAssertions):
    def test_stored_snapshot_its_directories_and_the_bindings_file_are_private(self):
        stored = self.managed.store_snapshot("work", credential("rt-1").encode("utf-8"), "acct-1")
        for path in (self.path, self.path / "work.json", self.bindings_file.parent, self.bindings_file):
            self.assert_private(path)
        self.assertFalse(stored.permissions_fixed)

    def test_storing_fixes_a_loose_existing_directory_and_snapshot_and_says_so(self):
        self.path.mkdir()  # 繼承暫存目錄的權限
        self.snapshot("home", "rt-2")  # 直接放進目錄、權限靠繼承
        stored = self.managed.store_snapshot("work", credential("rt-1").encode("utf-8"), "acct-1")
        for path in (self.path, self.path / "home.json", self.path / "work.json"):
            self.assert_private(path)
        self.assertTrue(stored.permissions_fixed)

    def test_bindings_learned_by_maintenance_are_private(self):
        self.snapshot("work", "rt-1")
        self.managed.maintain_bindings((KEY_RT1, "acct-1"))
        self.assert_private(self.bindings_file)


@unittest.skipUnless(sys.platform == "win32", "Windows ACL")
class WindowPositionPermissionTest(ManagedDirectoryTestCase, WindowsAclAssertions):
    def test_position_file_is_private(self):
        self.managed.write_observed(AT, Observed())  # 工具狀態目錄由其他寫入建立並收緊
        self.assertTrue(self.managed.write_window_position(5, 6))
        self.assert_private(self.path / ".state" / "window.json")


if __name__ == "__main__":
    unittest.main()
