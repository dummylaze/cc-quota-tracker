import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from cc_quota_tracker import COMMAND
from cc_quota_tracker.__main__ import main
from tests.fakehome import HomeTestCase


class CliTest(HomeTestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with self.cli_environment(), redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_single_entry_point_is_python_dash_m(self):
        self.assertEqual(COMMAND, "python -m cc_quota_tracker")

    def test_add_then_list_then_remove(self):
        self.log_in()
        code, out, _ = self.run_cli("add", "work")
        self.assertEqual(code, 0)
        self.assertIn("work", out)
        self.assertIn("納管帳號：work", self.run_cli("list")[1])
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
        self.assertIn("納管帳號：work", self.run_cli("list")[1])

    def test_unreadable_settings_file_is_reported(self):
        self.log_in()
        self.write_settings_text("{")
        for command in (("add", "work"), ("remove", "work"), ("list",)):
            with self.subTest(command=command):
                code, out, err = self.run_cli(*command)
                self.assertEqual(code, 0)
                self.assertIn("設定檔無法讀取", out + err)

    def test_list_shows_path_hints(self):
        self.assertIn("可能讀錯位置", self.run_cli("list")[1])  # 預設位置沒有 .claude.json
        self.log_in()
        self.assertNotIn("可能讀錯位置", self.run_cli("list")[1])

    def test_bad_usage_prints_full_command(self):
        for args in [(), ("add",), ("add", "a", "b"), ("list", "x"), ("nope",)]:
            with self.subTest(args=args):
                code, _, err = self.run_cli(*args)
                self.assertEqual(code, 2)
                self.assertIn(f"{COMMAND} add <帳號標籤>", err)


if __name__ == "__main__":
    unittest.main()
