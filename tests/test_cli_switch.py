"""命令列 `switch <帳號標籤> --yes`：依切換的結果印出訊息、回傳結束代碼。互動確認由後續的票補上。"""
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

from cc_quota_tracker import atomic
from cc_quota_tracker.__main__ import main
from tests.test_credential_sync import HOME, WORK, SyncTestCase


class CliSwitchTest(SyncTestCase):
    def setUp(self):
        super().setUp()
        self.manage("home", "rt-h", "acct-h", HOME)
        self.manage("work", "rt-w", "acct-w", WORK)
        self.core.poll()

    def run_cli(self, *args, system_language="zh-TW"):
        out, err = io.StringIO(), io.StringIO()
        with self.cli_environment(system_language), redirect_stdout(out), redirect_stderr(err), \
                mock.patch("cc_quota_tracker.__main__.datetime") as clock:
            clock.now.side_effect = lambda tz: self.clock.now  # 假 home 的憑證快照依測試時鐘到期
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def untouched(self):
        return self.current().read_bytes(), self.paths.claude_json.read_bytes()

    def test_switch_with_yes_succeeds(self):
        code, out, err = self.run_cli("switch", "home", "--yes")
        self.assertEqual((code, out.strip(), err), (0, "已切換到「home」", ""))
        self.assertEqual(self.current().read_bytes(), self.snapshot("home").read_bytes())

    def test_yes_may_come_first(self):
        self.assertEqual(self.run_cli("switch", "--yes", "home")[0], 0)

    def test_success_in_english(self):
        code, out, _ = self.run_cli("switch", "home", "--yes", system_language="en-US")
        self.assertEqual((code, out.strip()), (0, 'Switched to "home"'))

    def test_without_yes_prints_usage_and_writes_nothing(self):
        before = self.untouched()
        code, out, err = self.run_cli("switch", "home")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("switch <帳號標籤>", err)
        self.assertEqual(self.untouched(), before)

    def test_refusals_exit_one_with_the_reason(self):
        cases = {
            "nobody": "沒有帳號標籤為「nobody」的監看帳號。",
            "work": "「work」已經是當前憑證帳號。",
        }
        for label, message in cases.items():
            with self.subTest(label):
                before = self.untouched()
                code, out, err = self.run_cli("switch", label, "--yes")
                self.assertEqual((code, out, err.strip()), (1, "", message))
                self.assertEqual(self.untouched(), before)

    def test_watch_only_target_names_the_reason_and_the_remedy(self):
        self.clock.now = HOME + timedelta(seconds=1)
        code, _, err = self.run_cli("switch", "home", "--yes")
        self.assertEqual(code, 1)
        self.assertEqual(err.strip(), "「home」是僅監看帳號（已過期），不能切換過去：在 Claude Code 登入這個帳號後重新納管")

    def test_failed_sync_refuses(self):
        self.write_credentials(refresh="rt-w2", refresh_expires_at=WORK + timedelta(seconds=1))
        real = atomic.write_atomic

        def write(path, *args, **kwargs):
            if Path(path).name == "work.json":
                raise OSError("disk full")
            return real(path, *args, **kwargs)
        with mock.patch.object(atomic, "write_atomic", write):
            code, _, err = self.run_cli("switch", "home", "--yes")
        self.assertEqual(code, 1)
        self.assertEqual(err.strip(), "目前帳號的憑證沒能同步回它的快照，沒有切換；請稍後再試。")

    def test_unreadable_settings_file_refuses(self):
        self.paths.claude_json.write_text("{not json", encoding="utf-8")
        code, _, err = self.run_cli("switch", "home", "--yes")
        self.assertEqual(code, 1)
        self.assertEqual(err.strip(), "讀不到目前的憑證或 Claude Code 的帳號資訊，沒有切換；請稍後再試。")

    def test_half_written_switch_exits_three(self):
        real = atomic.write_atomic

        def write(path, *args, **kwargs):
            if Path(path) == self.paths.claude_json:
                raise PermissionError("locked")
            return real(path, *args, **kwargs)
        with mock.patch.object(atomic, "write_atomic", write):
            code, _, err = self.run_cli("switch", "home", "--yes")
        self.assertEqual(code, 3)
        self.assertIn("重新登入", err)

    def test_wrong_arguments_are_a_usage_error(self):
        self.assertEqual(self.run_cli("switch")[0], 2)
        self.assertEqual(self.run_cli("switch", "home", "--yes", "extra")[0], 2)
        self.assertEqual(self.run_cli("switch", "--yes", "--yes")[0], 2)

    def test_help_mentions_switch_and_yes(self):
        for lang, label in (("zh-TW", "switch <帳號標籤>"), ("en-US", "switch <label>")):
            with self.subTest(lang):
                code, out, _ = self.run_cli("--help", system_language=lang)
                self.assertEqual(code, 0)
                self.assertIn(label, out)
                self.assertIn("--yes", out)

    def test_switch_log_gets_one_line(self):
        log = self.home / ".claude-multi" / ".state" / "switches.jsonl"
        before = len(log.read_text(encoding="utf-8").splitlines())
        self.run_cli("switch", "home", "--yes")
        self.run_cli("list")
        lines = log.read_text(encoding="utf-8").splitlines()[before:]
        self.assertEqual([json.loads(line)["accountId"] for line in lines], ["acct-h"])
