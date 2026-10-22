"""視窗接線：右鍵選單的「token 報表」、啟動時與每 24 小時一次的帳本更新，都在背景子行程裡跑。
子行程以假的取代，只驗選單項目、啟動時機與參數；失敗只寫進錯誤紀錄，不跳任何提示。"""
import tkinter as tk
from unittest import mock

from cc_quota_tracker import report_jobs
from cc_quota_tracker.__main__ import main
from cc_quota_tracker.widget import Widget
from tests.fakehome import HomeTestCase
from tests.test_widget import WidgetTestCase


class FakeJob:
    def __init__(self, args):
        self.args = tuple(args)
        self.code = None  # None：還在跑
        self.output = ""

    def poll(self):
        return self.code

    def error_output(self):
        return self.output


class ReportTestCase(WidgetTestCase):
    def setUp(self):
        self.jobs = []
        self.launch_error = None
        super().setUp()

    def launch(self, args):
        if self.launch_error is not None:
            raise self.launch_error
        self.jobs.append(FakeJob(args))
        return self.jobs[-1]

    def open_widget(self):
        super().open_widget(report_launcher=self.launch)

    def error_log(self):
        path = self.settings_file().parent / "errors.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def menu_item(self, label):
        menu = self.widget._menu
        return next(i for i in range(menu.index("end") + 1) if menu.type(i) != "separator"
                    and menu.entrycget(i, "label") == label)

    def choose_report(self):
        self.widget._menu.invoke(self.menu_item("token 報表"))

    def args(self):
        return [job.args for job in self.jobs]


class MenuTest(ReportTestCase):
    def test_the_menu_offers_the_token_report_next_to_the_usage_entries(self):
        labels = self.widget.menu_labels()
        self.assertEqual(labels[labels.index("自動查詢額度") + 1], "token 報表")

    def test_the_label_follows_the_language(self):
        self.widget.set_preference("language", "en")
        self.assertIn("Token report", self.widget.menu_labels())
        self.assertNotIn("token 報表", self.widget.menu_labels())

    def test_there_is_no_entry_when_the_widget_cannot_run_children(self):
        other = tk.Tk()
        self.addCleanup(other.destroy)
        other.withdraw()
        widget = Widget(other, self.counting, self.paths, on_screen=lambda x, y: True, clock=self.clock)
        self.assertNotIn("token 報表", widget.menu_labels())

    def test_choosing_it_starts_a_report_child_with_no_extra_arguments(self):
        self.jobs.clear()
        self.choose_report()
        self.assertEqual(self.args(), [report_jobs.REPORT_ARGS])

    def test_choosing_it_again_while_the_report_is_still_being_made_starts_nothing_more(self):
        self.jobs.clear()
        self.choose_report()
        self.choose_report()
        self.assertEqual(len(self.jobs), 1)

    def test_once_the_report_child_has_ended_it_can_be_chosen_again(self):
        self.jobs.clear()
        self.choose_report()
        self.jobs[0].code = 0
        self.choose_report()
        self.assertEqual(len(self.jobs), 2)

    def test_choosing_it_does_not_block_and_shows_no_dialog(self):
        with mock.patch("cc_quota_tracker.widget.messagebox") as box:
            self.choose_report()
        self.assertEqual(box.mock_calls, [])


class DailyUpdateTest(ReportTestCase):
    def test_a_ledger_only_child_starts_once_the_widget_is_up(self):
        self.assertEqual(self.args(), [report_jobs.LEDGER_ARGS])

    def test_it_does_not_start_again_on_the_following_rounds(self):
        self.jobs[0].code = 0
        for _ in range(5):
            self.clock.advance(seconds=5)
            self.widget.refresh()
        self.assertEqual(len(self.jobs), 1)

    def test_it_starts_again_24_hours_after_the_last_start_and_not_before(self):
        self.jobs[0].code = 0
        self.clock.advance(hours=23, minutes=59)
        self.widget.refresh()
        self.assertEqual(len(self.jobs), 1)
        self.clock.advance(minutes=1)
        self.widget.refresh()
        self.assertEqual(self.args(), [report_jobs.LEDGER_ARGS] * 2)
        self.jobs[1].code = 0
        self.clock.advance(hours=24)
        self.widget.refresh()
        self.assertEqual(len(self.jobs), 3)

    def test_it_waits_while_the_previous_ledger_child_is_still_running(self):
        self.clock.advance(hours=25)
        self.widget.refresh()
        self.assertEqual(len(self.jobs), 1)  # 前一個還沒結束
        self.jobs[0].code = 0
        self.widget.refresh()
        self.assertEqual(len(self.jobs), 2)

    def test_a_report_made_from_the_menu_and_the_daily_update_can_run_at_the_same_time(self):
        self.choose_report()
        self.assertEqual(self.args(), [report_jobs.LEDGER_ARGS, report_jobs.REPORT_ARGS])
        self.assertTrue(all(job.poll() is None for job in self.jobs))

    def test_a_daily_update_that_comes_due_while_a_report_is_being_made_still_starts(self):
        self.jobs[0].code = 0
        self.choose_report()
        self.clock.advance(hours=24)
        self.widget.refresh()
        self.assertEqual(self.args(), [report_jobs.LEDGER_ARGS, report_jobs.REPORT_ARGS, report_jobs.LEDGER_ARGS])


class ParsingStaysInTheChildTest(ReportTestCase):
    def test_the_widget_process_never_reads_the_transcripts_itself(self):
        with mock.patch("cc_quota_tracker.transcripts.scan", side_effect=AssertionError("parsed in the widget")), \
                mock.patch("cc_quota_tracker.token_report.update_ledger", side_effect=AssertionError("ledger in widget")):
            self.choose_report()
            self.clock.advance(hours=25)
            self.jobs[0].code = 0
            self.widget.refresh()
        self.assertEqual(self.error_log(), "")


class FailureTest(ReportTestCase):
    def test_a_child_that_fails_is_written_to_the_error_log_with_its_exit_code_and_stderr(self):
        self.jobs[0].code, self.jobs[0].output = 1, "用量帳本更新失敗（No space left on device）"
        with mock.patch("cc_quota_tracker.widget.messagebox") as box:
            self.widget.refresh()
        self.assertEqual(box.mock_calls, [])
        log = self.error_log()
        self.assertIn("1", log)
        self.assertIn("用量帳本更新失敗（No space left on device）", log)
        self.assertIn("--update-ledger", log)

    def test_a_failed_report_from_the_menu_is_logged_too(self):
        self.jobs[0].code = 0
        self.choose_report()
        self.jobs[1].code, self.jobs[1].output = 2, "boom"
        self.widget.refresh()
        self.assertIn("boom", self.error_log())

    def test_a_child_that_ends_well_leaves_nothing_in_the_log(self):
        self.jobs[0].code = 0
        self.widget.refresh()
        self.assertEqual(self.error_log(), "")

    def test_a_child_is_judged_once(self):
        self.jobs[0].code, self.jobs[0].output = 1, "first"
        self.widget.refresh()
        with mock.patch.object(self.jobs[0], "error_output", wraps=self.jobs[0].error_output) as read:
            self.widget.refresh()
        self.assertEqual(read.call_count, 0)

    def test_a_child_that_cannot_start_is_logged_without_a_dialog_and_the_update_is_tried_again_next_day(self):
        self.jobs[0].code = 0
        self.launch_error = FileNotFoundError(2, "No such file or directory")
        with mock.patch("cc_quota_tracker.widget.messagebox") as box:
            self.clock.advance(hours=24)
            self.widget.refresh()
            self.choose_report()
        self.assertEqual(box.mock_calls, [])
        self.assertIn("FileNotFoundError", self.error_log())
        self.launch_error = None
        self.clock.advance(hours=24)
        self.widget.refresh()
        self.assertEqual(len(self.jobs), 2)

    def test_any_other_launch_error_is_logged_once_and_neither_retried_every_round_nor_thrown_to_the_menu(self):
        self.jobs[0].code = 0
        self.launch_error = ValueError("embedded null")
        self.clock.advance(hours=24)
        self.widget.refresh()
        self.widget.refresh()  # 每輪重試的話，這裡會再試一次
        self.assertEqual(self.error_log().count("ValueError: embedded null"), 1)
        self.choose_report()  # 選單的處理函式：不能把例外丟出去
        self.assertEqual(self.args(), [report_jobs.LEDGER_ARGS])

    def test_a_failure_does_not_stop_the_widget_from_polling(self):
        self.jobs[0].code, self.jobs[0].output = 1, "boom"
        polls = self.counting.polls
        self.widget.refresh()
        self.assertEqual(self.counting.polls, polls + 1)
        self.assertEqual(len(self.pending_after()), 1)


class GuiWiringTest(HomeTestCase):
    def test_the_gui_command_gives_the_widget_the_real_launcher(self):
        with self.cli_environment(), mock.patch("tkinter.Tk"), mock.patch("cc_quota_tracker.widget.Widget") as widget, \
                mock.patch("cc_quota_tracker.widget.enable_dpi_awareness"), \
                mock.patch("cc_quota_tracker.autostart.RegistryAutostart"):
            self.assertEqual(main(["gui"]), 0)
        self.assertIs(widget.call_args.kwargs["report_launcher"], report_jobs.launch)
