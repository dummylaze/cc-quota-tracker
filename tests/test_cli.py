import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone

from cc_quota_tracker import COMMAND, __version__, command_for
from cc_quota_tracker.__main__ import main
from tests.fakehome import HomeTestCase, claude_json, usage_cache


class CliTestCase(HomeTestCase):
    def run_cli(self, *args, system_language="zh-TW"):
        out, err = io.StringIO(), io.StringIO()
        with self.cli_environment(system_language), redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()


class CliTest(CliTestCase):
    def test_single_entry_point_is_python_dash_m(self):
        self.assertEqual(COMMAND, "python -m cc_quota_tracker")

    def test_add_then_list_then_remove(self):
        self.log_in()
        code, out, _ = self.run_cli("add", "work")
        self.assertEqual(code, 0)
        self.assertIn("work", out)
        self.assertIn("監看帳號：work", self.run_cli("list")[1])
        code, out, _ = self.run_cli("remove", "work")
        self.assertEqual(code, 0)
        self.assertIn("work", out)
        self.assertIn("尚未納管任何帳號", self.run_cli("list")[1])

    def test_add_warns_that_email_like_label_is_shown_on_screen(self):
        self.log_in()
        code, out, err = self.run_cli("add", "someone@example.com")
        self.assertEqual(code, 0)
        self.assertIn("會顯示在畫面上", out + err)

    def test_add_when_not_logged_in_fails(self):
        code, _, err = self.run_cli("add", "work")
        self.assertEqual(code, 1)
        self.assertIn("登入", err)

    def test_add_with_invalid_label_fails(self):
        self.log_in()
        code, _, err = self.run_cli("add", "../work")
        self.assertEqual(code, 2)
        self.assertIn("../work", err)

    def test_add_with_locked_bindings_file_fails_with_its_path(self):
        self.log_in()
        self.run_cli("add", "work")
        with self.locked("bindings.json"):
            code, _, err = self.run_cli("add", "home")
        self.assertEqual(code, 1)
        self.assertIn("鎖住", err)
        self.assertIn(str(self.home / ".claude-multi" / ".state" / "bindings.json"), err)

    def test_remove_with_locked_bindings_file_still_reports_removed(self):
        self.log_in()
        self.run_cli("add", "work")
        with self.locked("bindings.json"):
            code, out, err = self.run_cli("remove", "work")
        self.assertEqual(code, 0)
        self.assertIn("work", out)
        self.assertEqual(err, "")
        self.assertFalse((self.home / ".claude-multi" / "work.json").exists())

    def test_remove_unknown_label_fails(self):
        code, _, err = self.run_cli("remove", "work")
        self.assertEqual(code, 1)
        self.assertIn("work", err)

    def test_path_setting_that_cannot_be_used_names_the_field(self):
        self.log_in()
        for fields, expected in [({"managedDir": str(self.home / "unplugged")}, "managedDir"),
                                 ({"claudeConfigDir": "relative"}, "claudeConfigDir"),
                                 ({"managedDir": str(self.home / ".claude")}, "managedDir")]:
            for command in (("add", "work"), ("remove", "work"), ("list",)):
                with self.subTest(fields=fields, command=command):
                    self.write_settings(**fields)
                    code, _, err = self.run_cli(*command)
                    self.assertEqual(code, 1)
                    self.assertIn(expected, err)
                    self.assertIn("settings.json", err)
        self.assertFalse((self.home / ".claude-multi").exists())

    def test_add_uses_the_managed_dir_from_the_settings_file(self):
        self.log_in()
        managed = self.home / "other-disk"
        managed.mkdir()
        self.write_settings(managedDir=str(managed))
        self.assertEqual(self.run_cli("add", "work")[0], 0)
        self.assertTrue((managed / "work.json").is_file())
        self.assertIn("監看帳號：work", self.run_cli("list")[1])

    def test_unreadable_settings_file_is_reported(self):
        self.log_in()
        self.write_settings_text("{")
        for command in (("add", "work"), ("remove", "work"), ("list",)):
            with self.subTest(command=command):
                code, out, err = self.run_cli(*command)
                self.assertEqual(code, 0)
                self.assertIn("注意：設定檔無法讀取", out + err)

    def test_list_shows_path_hints(self):
        self.assertIn("可能讀錯位置", self.run_cli("list")[1])  # 預設位置沒有 .claude.json
        self.log_in()
        self.assertNotIn("可能讀錯位置", self.run_cli("list")[1])

    def test_bad_usage_prints_full_command(self):
        for args in [(), ("add",), ("add", "a", "b"), ("list", "x"), ("gui", "x"), ("nope",)]:
            with self.subTest(args=args):
                code, _, err = self.run_cli(*args)
                self.assertEqual(code, 2)
                self.assertIn(f"{COMMAND} add <帳號標籤>", err)

    def test_help_flags_print_usage_to_stdout_and_succeed(self):
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                code, out, err = self.run_cli(flag)
                self.assertEqual(code, 0)
                self.assertIn(f"{COMMAND} add <帳號標籤>", out)
                self.assertEqual(err, "")

    def test_help_prints_the_same_text_as_a_mistyped_command(self):
        for tag in ("zh-TW", "en-US"):
            with self.subTest(language=tag):
                _, help_out, _ = self.run_cli("--help", system_language=tag)
                _, _, usage_err = self.run_cli("nope", system_language=tag)
                self.assertEqual(help_out, usage_err)

    def test_help_does_not_resolve_paths(self):
        self.write_settings(claudeConfigDir="relative", managedDir=str(self.home / "unplugged"))
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                code, out, err = self.run_cli(flag)
                self.assertEqual(code, 0)
                self.assertIn(f"{COMMAND} add <帳號標籤>", out)
                self.assertEqual(err, "")

    def test_help_flag_with_other_arguments_is_still_bad_usage(self):
        for args in [("--help", "x"), ("list", "-h"), ("check", "--help"), ("gui", "-h"), ("-h", "-h")]:
            with self.subTest(args=args):
                code, out, err = self.run_cli(*args)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertIn(f"{COMMAND} add", err)


class VersionTest(CliTestCase):
    def test_version_flag_prints_name_and_version_to_stdout_and_succeeds(self):
        code, out, err = self.run_cli("--version")
        self.assertEqual((code, out, err), (0, f"cc-quota-tracker {__version__}\n", ""))

    def test_version_is_a_semantic_version_and_does_not_depend_on_the_language(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")
        self.assertEqual(self.run_cli("--version", system_language="zh-TW")[1],
                         self.run_cli("--version", system_language="en-US")[1])

    def test_version_does_not_resolve_paths(self):
        self.write_settings(claudeConfigDir="relative", managedDir=str(self.home / "unplugged"))
        self.assertEqual(self.run_cli("--version")[::2], (0, ""))

    def test_version_flag_with_other_arguments_is_bad_usage(self):
        for args in [("--version", "x"), ("list", "--version"), ("--version", "--help")]:
            with self.subTest(args=args):
                code, out, err = self.run_cli(*args)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(f"{COMMAND} add", err)

    def test_usage_lists_the_version_flag_in_both_languages(self):
        for tag in ("zh-TW", "en-US"):
            with self.subTest(language=tag):
                self.assertIn(f"{COMMAND} --version", self.run_cli("--help", system_language=tag)[1])

    def test_command_in_hints_is_the_cli_exe_when_frozen(self):
        self.assertEqual(command_for(frozen=False), "python -m cc_quota_tracker")
        self.assertEqual(command_for(frozen=True), "cc-quota-tracker-cli")


class CliLanguageTest(CliTestCase):
    """命令列的文案語系與視窗一致：設定檔的 language，跟隨系統時取作業系統的語系，不支援時英文。"""

    def test_follows_the_system_by_default(self):
        self.assertIn("尚未納管任何帳號", self.run_cli("list", system_language="zh-TW")[1])
        self.assertIn("No accounts managed yet", self.run_cli("list", system_language="en-US")[1])

    def test_unsupported_system_language_falls_back_to_english(self):
        for tag in ("ja-JP", "zh-CN", None):
            self.assertIn("No accounts managed yet", self.run_cli("list", system_language=tag)[1], tag)

    def test_a_chosen_language_ignores_the_system(self):
        self.write_settings(language="en")
        self.assertIn("No accounts managed yet", self.run_cli("list", system_language="zh-TW")[1])
        self.write_settings(language="zh-TW")
        self.assertIn("尚未納管任何帳號", self.run_cli("list", system_language="en-US")[1])

    def test_list_reads_in_english_without_leftover_chinese(self):
        later = datetime.now(timezone.utc) + timedelta(days=3, hours=1)
        self.write_claude_json(claude_json(usage_cache(session=12, weekly=75, resets_at=later)))
        self.write_settings(language="en")
        out = self.run_cli("list")[1]
        self.assertIn("Session window  12%  Resets: in 3d 0h", out)
        self.assertIn("Weekly window  75%", out)
        self.assertIn("[Active] Unwatched account", out)
        self.assertNotRegex(out, r"[⺀-鿿]")

    def test_add_and_remove_report_in_english(self):
        self.write_settings(language="en")
        self.log_in()
        code, out, err = self.run_cli("add", "someone@example.com")
        self.assertEqual(code, 0)
        self.assertIn("Managed \"someone@example.com\"", out)
        self.assertIn("looks like an email address", err)
        self.assertIn("Watched accounts: someone@example.com", self.run_cli("list")[1])
        self.assertIn("Removed \"someone@example.com\"", self.run_cli("remove", "someone@example.com")[1])

    def test_errors_are_in_english(self):
        self.write_settings(language="en")
        self.assertIn("Couldn't read the current sign-in credential", self.run_cli("add", "work")[2])
        self.log_in()
        self.assertIn("can't be used as a file name", self.run_cli("add", "../work")[2])
        self.assertIn("There is no watched account with the label \"work\"", self.run_cli("remove", "work")[2])
        self.run_cli("add", "work")
        with self.locked("bindings.json"):
            self.assertIn("may have it locked", self.run_cli("add", "home")[2])

    def test_usage_and_path_problems_are_in_english(self):
        self.assertIn(f"{COMMAND} add <label>", self.run_cli(system_language="en-US")[2])
        self.write_settings(language="en", claudeConfigDir="relative")
        err = self.run_cli("list")[2]
        self.assertIn("must be a full absolute path", err)
        self.assertIn("Settings file:", err)

    def test_unreadable_settings_file_follows_the_system_language(self):
        self.write_settings_text("{")
        out = self.run_cli("list", system_language="en-US")[1]
        self.assertIn("The settings file can't be read", out)

    def test_check_reads_in_english(self):
        self.write_settings(language="en")
        self.write_claude_json(claude_json(usage_cache()))
        code, out, err = self.run_cli("check")
        self.assertEqual(code, 0)
        self.assertIn("Fields depended on:", out)
        self.assertIn("Result: compatible", out)
        self.assertNotRegex(out + err, r"[⺀-鿿]")


if __name__ == "__main__":
    unittest.main()
