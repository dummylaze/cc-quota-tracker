"""背景子行程：打包版呼叫同資料夾的命令列 exe、原始碼版呼叫 `python -m`；真的啟動一個，跑在假 home 上。"""
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from cc_quota_tracker import report_jobs
from tests.fakehome import HomeTestCase
from tests.test_packaging import PACKAGING

sys.path.insert(0, str(PACKAGING))
import package_release  # noqa: E402


class CommandTest(unittest.TestCase):
    def test_a_packaged_build_calls_the_console_exe_beside_the_window_exe(self):
        window = str(Path("C:/apps/cc-quota-tracker/cc-quota-tracker.exe"))
        self.assertEqual(report_jobs.base_command(True, window),
                         [str(Path("C:/apps/cc-quota-tracker/cc-quota-tracker-cli.exe")), "report"])

    def test_a_source_checkout_calls_python_dash_m(self):
        self.assertEqual(report_jobs.base_command(False, "pythonw.exe"),
                         ["pythonw.exe", "-m", "cc_quota_tracker", "report"])

    def test_the_console_exe_name_is_one_the_release_ships(self):
        self.assertIn(report_jobs.CLI_EXE, package_release.REQUIRED)


class LaunchTest(HomeTestCase):
    def child_env(self):
        env = dict(self.env, USERPROFILE=str(self.home), HOME=str(self.home))
        for name in ("SYSTEMROOT", "PATH"):
            if name in os.environ:
                env[name] = os.environ[name]
        return env

    def wait(self, job, seconds=120):
        deadline = time.monotonic() + seconds
        while job.poll() is None:
            self.assertLess(time.monotonic(), deadline, "子行程沒有結束")
            time.sleep(0.05)
        return job.poll()

    def test_it_runs_the_report_command_in_a_child_process_on_the_given_environment(self):
        job = report_jobs.launch(("--no-open",), self.child_env())
        self.assertEqual((self.wait(job), job.error_output()), (0, ""))
        self.assertTrue((self.settings_file().parent / "token-report.html").exists())

    def test_what_the_child_prints_to_stderr_is_kept_for_the_error_log(self):
        job = report_jobs.launch(("--no-such-flag",), self.child_env())
        self.assertEqual(self.wait(job), 2)
        self.assertIn("report", job.error_output())

    def test_only_the_end_of_a_long_stderr_is_kept(self):
        with mock.patch.object(report_jobs, "base_command",
                               return_value=[sys.executable, "-c", "import sys; sys.stderr.write('x' * 9000 + 'END')"]):
            job = report_jobs.launch((), self.child_env())
        self.wait(job)
        tail = job.error_output()
        self.assertTrue(tail.endswith("END"))
        self.assertLess(len(tail), 3000)

    def launch_options(self, frozen):
        """不真的啟動：只看交給 Popen 的選項（真的子行程看不出有沒有開主控台，也掩蓋不了工作目錄）。"""
        with mock.patch.object(sys, "frozen", frozen, create=True), mock.patch("subprocess.Popen") as popen:
            report_jobs.launch(("--no-open",))
        return popen.call_args.kwargs

    @unittest.skipUnless(os.name == "nt", "CREATE_NO_WINDOW 只在 Windows")
    def test_no_console_window_is_opened_for_the_child(self):
        for frozen in (False, True):
            self.assertTrue(self.launch_options(frozen)["creationflags"] & 0x08000000, frozen)

    def test_the_source_checkout_child_starts_in_the_project_root_whatever_the_current_directory(self):
        # -m 要從專案根目錄找得到套件；原始碼部署沒有裝進 site-packages
        self.assertEqual(self.launch_options(False)["cwd"], report_jobs.PROJECT_ROOT)
        self.assertTrue((report_jobs.PROJECT_ROOT / "cc_quota_tracker" / "__main__.py").is_file())

    def test_the_child_output_is_not_a_pipe_that_could_fill_up(self):
        options = self.launch_options(False)
        self.assertEqual((options["stdin"], options["stdout"]), (subprocess.DEVNULL, subprocess.DEVNULL))
        self.assertNotEqual(options["stderr"], subprocess.PIPE)

    def test_a_command_that_cannot_start_raises_os_error(self):
        with mock.patch.object(report_jobs, "base_command", return_value=[str(self.home / "missing.exe")]):
            with self.assertRaises(OSError):
                report_jobs.launch((), self.child_env())


if __name__ == "__main__":
    unittest.main()
