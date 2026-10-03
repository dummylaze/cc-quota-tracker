"""錯誤紀錄：每輪沒有完成時寫進設定目錄的 errors.log；同一個錯誤連續發生只寫一次，超過 1 MB 輪替，寫不進去不影響視窗。
縫：把核心的 poll 換成會丟例外的替身。"""
import unittest
from unittest import mock

from cc_quota_tracker.error_log import LOG_NAME, MAX_BYTES
from tests.test_stalled import StalledTestCase


class ErrorLogTestCase(StalledTestCase):
    @property
    def log_dir(self):
        return self.paths.settings_file.parent

    def count(self):
        path = self.log_dir / LOG_NAME
        return path.read_text(encoding="utf-8").count("Traceback (most recent call last)") if path.exists() else 0


class WhenToWriteTest(ErrorLogTestCase):
    def test_the_first_failed_round_writes_time_and_traceback(self):
        self.fail_rounds(1)
        text = (self.log_dir / LOG_NAME).read_text(encoding="utf-8")
        self.assertIn(self.clock.now.isoformat(timespec="seconds"), text)
        self.assertIn("Traceback (most recent call last)", text)
        self.assertIn("RuntimeError: boom", text)

    def test_the_same_error_in_a_row_is_written_once(self):
        self.fail_rounds(5)
        self.assertEqual(self.count(), 1)

    def test_a_different_message_or_type_is_written_again(self):
        self.fail_rounds(1)
        self.fail_rounds(1, RuntimeError("another"))
        self.fail_rounds(1, ValueError("another"))
        self.assertEqual(self.count(), 3)

    def test_failing_again_after_recovering_is_written_again(self):
        self.fail_rounds(2)
        self.recover()
        self.fail_rounds(2)
        self.assertEqual(self.count(), 2)


class StartupRoundLoggedTest(ErrorLogTestCase):
    def open_widget(self):
        with mock.patch.object(self.core, "poll", side_effect=RuntimeError("boom")):
            super().open_widget()  # 啟動的那一輪就沒有完成

    def test_the_startup_round_is_written(self):
        self.assertEqual(self.count(), 1)


class RotationTest(ErrorLogTestCase):
    def test_a_log_over_one_megabyte_is_rotated_and_only_one_old_file_is_kept(self):
        log = self.log_dir / LOG_NAME
        old = self.log_dir / (LOG_NAME + ".1")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        old.write_text("ancient", encoding="utf-8")
        log.write_bytes(b"x" * (MAX_BYTES + 1))
        self.fail_rounds(1)
        self.assertEqual(old.stat().st_size, MAX_BYTES + 1)  # 原本那份舊檔被取代，沒有 .2
        self.assertFalse((self.log_dir / (LOG_NAME + ".2")).exists())
        self.assertEqual(self.count(), 1)
        self.assertLess(log.stat().st_size, MAX_BYTES)

    def test_a_log_at_the_limit_is_not_rotated(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / LOG_NAME).write_bytes(b"x" * MAX_BYTES)
        self.fail_rounds(1)
        self.assertFalse((self.log_dir / (LOG_NAME + ".1")).exists())


class RotationFailureTest(ErrorLogTestCase):
    def test_a_failed_rotation_still_appends(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / LOG_NAME).write_bytes(b"x" * (MAX_BYTES + 1))
        with mock.patch("cc_quota_tracker.error_log.os.replace", side_effect=PermissionError("locked")):
            self.fail_rounds(1)
        self.assertEqual(self.count(), 1)

    def test_an_error_whose_str_raises_does_not_escape(self):
        class Bad(Exception):
            def __str__(self):
                raise RuntimeError("no str")
        self.fail_rounds(2, Bad())
        self.assertEqual(len(self.pending_after()), 1)


class UnwritableLogTest(ErrorLogTestCase):
    def block_the_log(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / LOG_NAME).mkdir()  # 同名的目錄：開檔必定失敗，與唯讀目錄同一條路徑

    def test_refresh_does_not_raise_keeps_one_after_and_shows_no_dialog(self):
        self.block_the_log()
        with mock.patch("cc_quota_tracker.widget.messagebox") as box:
            self.fail_rounds(3)
        self.assertEqual(len(self.pending_after()), 1)
        box.showerror.assert_not_called()
        box.showinfo.assert_not_called()
        box.showwarning.assert_not_called()

    def test_a_failed_write_is_retried_on_the_next_round(self):
        self.block_the_log()
        self.fail_rounds(2)
        (self.log_dir / LOG_NAME).rmdir()
        self.fail_rounds(1)
        self.assertEqual(self.count(), 1)


if __name__ == "__main__":
    unittest.main()
