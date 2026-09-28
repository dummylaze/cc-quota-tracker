import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from cc_quota_tracker import COMMAND
from cc_quota_tracker.__main__ import main
from tests.fakehome import HomeTestCase


class CliTest(HomeTestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("pathlib.Path.home", return_value=self.home), redirect_stdout(out), redirect_stderr(err):
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

    def test_bad_usage_prints_full_command(self):
        for args in [(), ("add",), ("add", "a", "b"), ("list", "x"), ("nope",)]:
            with self.subTest(args=args):
                code, _, err = self.run_cli(*args)
                self.assertEqual(code, 2)
                self.assertIn(f"{COMMAND} add <帳號標籤>", err)


if __name__ == "__main__":
    unittest.main()
