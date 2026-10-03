"""收不緊權限的位置（FAT32／exFAT）：照常運作並告警（ADR-0008）。縫 ①：把 permissions 的 make_private／is_private
換掉，模擬「收緊成功但沒效果」與「收緊回報錯誤」兩種。"""
import contextlib
import json
from unittest import mock

from cc_quota_tracker.canvas_text import banner_lines
from cc_quota_tracker.core import AddWarning
from tests.fakehome import HomeTestCase, claude_json, usage_cache
from tests.test_cli import CliTestCase

_NO_EFFECT = "no_effect"
_ERRORS = "errors"


@contextlib.contextmanager
def untightenable(mode=_NO_EFFECT):
    """收緊不成：no_effect 是收緊不報錯、查回仍未收緊；errors 是收緊本身回報錯誤。"""
    with mock.patch("cc_quota_tracker.managed_directory.is_private", return_value=False):
        if mode == _ERRORS:
            with mock.patch("cc_quota_tracker.managed_directory.make_private", side_effect=PermissionError("denied")):
                yield
        else:
            with mock.patch("cc_quota_tracker.managed_directory.make_private"):
                yield


class UntightenedTestCase(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.state = self.home / ".claude-multi" / ".state"

    def lines(self, name):
        return [json.loads(line) for line in (self.state / name).read_text(encoding="utf-8").splitlines()]


class UntightenedWritesTest(UntightenedTestCase):
    def test_switch_log_and_last_run_are_written_in_both_modes(self):
        for mode in (_NO_EFFECT, _ERRORS):
            with self.subTest(mode=mode), untightenable(mode):
                self.setUp()
                self.log_in()
                self.core.add("work")
                self.core.poll()
                self.assertEqual(len(self.lines("switches.jsonl")), 1)
                observed = json.loads((self.state / "observed.json").read_text(encoding="utf-8"))
                self.assertIn("lastRunAt", observed)

    def test_window_position_is_written_in_both_modes(self):
        for mode in (_NO_EFFECT, _ERRORS):
            with self.subTest(mode=mode), untightenable(mode):
                self.setUp()
                self.core.poll()
                self.assertTrue(self.core._managed.write_window_position(3, 4))

    def test_a_failing_permission_query_is_treated_as_untightened(self):
        query_fails = mock.patch("cc_quota_tracker.managed_directory.is_private", side_effect=OSError("query failed"))
        with query_fails, mock.patch("cc_quota_tracker.managed_directory.make_private"):
            self.log_in()
            result = self.core.add("work")
        self.assertIn(AddWarning.PERMISSIONS_UNTIGHTENED, result.warnings)

    def test_standby_reading_is_remembered_and_the_poll_does_not_fail(self):
        with untightenable():
            self.log_in(refresh="rt-1", account_uuid="acct-1")
            self.core.add("work")
            self.write_cache(oauth="acct-1", session=40)
            self.core.poll()
            self.assertIn("acct-1", json.loads((self.state / "readings.json").read_text(encoding="utf-8")))
            self.log_in(refresh="rt-2", account_uuid="acct-2")
            self.write_cache(oauth="acct-2", account_uuid="acct-2", session=10)
            board = self.core.poll()
        standby = [c for c in board.cards if c.role.value == "standby"][0]
        self.assertEqual(standby.limits[0].percent, 40)


class UntightenedBoardTest(UntightenedTestCase):
    def test_board_is_flagged_by_behavior_in_both_modes(self):
        for mode in (_NO_EFFECT, _ERRORS):
            with self.subTest(mode=mode), untightenable(mode):
                self.setUp()
                self.assertTrue(self.core.poll().permissions_untightened)

    def test_board_is_not_flagged_when_tightening_works(self):
        self.assertFalse(self.core.poll().permissions_untightened)

    def test_one_failed_tightening_in_a_round_flags_it_and_a_clean_round_clears_it(self):
        with untightenable():
            self.assertTrue(self.core.poll().permissions_untightened)
        self.assertFalse(self.core.poll().permissions_untightened)

    def test_banner_text_in_both_languages(self):
        with untightenable():
            board = self.core.poll()
        self.assertIn("納管目錄的權限無法收緊。把它搬到 NTFS 磁碟（一般的 C:、D: 槽）即可解除。", banner_lines(board, "zh-TW"))
        self.assertTrue(any("NTFS" in line and "can't be restricted" in line for line in banner_lines(board, "en")))

    def test_no_banner_when_not_flagged(self):
        self.assertFalse(any("無法收緊" in line for line in banner_lines(self.core.poll(), "zh-TW")))


class UntightenedAddTest(UntightenedTestCase):
    def test_add_and_import_warn_and_still_store_the_snapshot(self):
        for mode in (_NO_EFFECT, _ERRORS):
            with self.subTest(mode=mode), untightenable(mode):
                self.setUp()
                self.log_in()
                result = self.core.add("work")
                self.assertIn(AddWarning.PERMISSIONS_UNTIGHTENED, result.warnings)
                self.assertNotIn(AddWarning.PERMISSIONS_FIXED, result.warnings)
                imported = self.core.import_snapshot(self.paths.claude_dir / ".credentials.json", "other")
                self.assertIn(AddWarning.PERMISSIONS_UNTIGHTENED, imported.warnings)
                self.assertTrue((self.home / ".claude-multi" / "work.json").exists())

    def test_no_warning_when_tightening_works(self):
        self.log_in()
        self.assertNotIn(AddWarning.PERMISSIONS_UNTIGHTENED, self.core.add("work").warnings)


class UntightenedCliTest(CliTestCase):
    def test_add_prints_the_warning_to_stderr_and_exits_zero_without_a_traceback(self):
        self.log_in()
        with untightenable():
            code, out, err = self.run_cli("add", "work")
        self.assertEqual(code, 0)
        self.assertIn("納管目錄的權限無法收緊。把它搬到 NTFS 磁碟（一般的 C:、D: 槽）即可解除。", err)
        self.assertNotIn("Traceback", out + err)

    def test_add_warning_in_english(self):
        self.write_settings(language="en")
        self.log_in()
        with untightenable(_ERRORS):
            code, _, err = self.run_cli("add", "work")
        self.assertEqual(code, 0)
        self.assertIn("can't be restricted", err)

    def check_line(self):
        self.write_claude_json(claude_json(usage_cache()))
        return self.run_cli("check")[1]

    def test_check_says_not_created_before_the_directory_exists(self):
        self.assertIn("納管目錄權限：尚未建立", self.check_line())

    def test_check_says_tightened_after_add(self):
        self.log_in()
        self.run_cli("add", "work")
        self.assertIn("納管目錄權限：已收緊", self.check_line())

    def test_check_says_untightened_without_trying_to_fix_it(self):
        self.log_in()
        with untightenable():
            self.run_cli("add", "work")
        with mock.patch("cc_quota_tracker.managed_directory.is_private", return_value=False), \
                mock.patch("cc_quota_tracker.managed_directory.make_private") as make:
            self.assertIn("納管目錄權限：未收緊", self.check_line())
        make.assert_not_called()

    def test_check_in_english(self):
        self.write_settings(language="en")
        self.assertIn("Managed directory permissions: not created yet", self.check_line())


@contextlib.contextmanager
def dismissal_unwritable():
    """關掉的紀錄寫不進去（例如被防毒鎖住）；其他工具狀態照常寫。"""
    from cc_quota_tracker import atomic
    original = atomic.write_atomic

    def write(path, *args, **kwargs):
        if path.name == "warnings.json":
            raise PermissionError("locked")
        return original(path, *args, **kwargs)
    with mock.patch("cc_quota_tracker.atomic.write_atomic", side_effect=write):
        yield


class UntightenedDismissTest(UntightenedTestCase):
    def dismissed_on_disk(self):
        path = self.state / "warnings.json"
        return path.exists() and json.loads(path.read_text(encoding="utf-8")).get("untightenedDismissed") is True

    def test_dismissing_hides_the_warning_and_survives_a_restart(self):
        with untightenable():
            self.assertTrue(self.core.poll().permissions_untightened)
            self.core.dismiss_untightened_warning()
            self.assertFalse(self.core.poll().permissions_untightened)
            self.start()  # 重新啟動：記憶體裡的狀態都沒了，只剩納管目錄裡的紀錄
            self.assertFalse(self.core.poll().permissions_untightened)
        self.assertTrue(self.dismissed_on_disk())

    def test_another_managed_directory_has_no_dismissal(self):
        with untightenable():
            self.core.poll()
            self.core.dismiss_untightened_warning()
            self.write_settings(managedDir=str(self.make_dir("elsewhere")))
            self.start()
            self.assertTrue(self.core.poll().permissions_untightened)

    def test_a_fully_tightened_round_clears_the_dismissal(self):
        with untightenable():
            self.core.poll()
            self.core.dismiss_untightened_warning()
        self.assertFalse(self.core.poll().permissions_untightened)
        self.assertFalse(self.dismissed_on_disk())
        with untightenable():
            self.assertTrue(self.core.poll().permissions_untightened)

    def test_add_and_import_still_warn_after_dismissing(self):
        with untightenable():
            self.core.poll()
            self.core.dismiss_untightened_warning()
            self.log_in()
            self.assertIn(AddWarning.PERMISSIONS_UNTIGHTENED, self.core.add("work").warnings)
            imported = self.core.import_snapshot(self.paths.claude_dir / ".credentials.json", "other")
            self.assertIn(AddWarning.PERMISSIONS_UNTIGHTENED, imported.warnings)
            self.assertFalse(self.core.poll().permissions_untightened)

    def test_an_unwritable_dismissal_still_hides_the_warning_and_is_retried_next_round(self):
        with untightenable():
            self.core.poll()
            with dismissal_unwritable():
                self.core.dismiss_untightened_warning()
                self.assertFalse(self.core.poll().permissions_untightened)
            self.assertFalse(self.dismissed_on_disk())
            self.assertFalse(self.core.poll().permissions_untightened)
        self.assertTrue(self.dismissed_on_disk())
