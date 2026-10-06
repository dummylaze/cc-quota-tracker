"""命令列 `switch <帳號標籤> --yes`：依切換的結果印出訊息、回傳結束代碼。互動確認由後續的票補上。"""
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

from cc_quota_tracker import atomic
from cc_quota_tracker.__main__ import main
from tests.fakehome import NOW
from tests.test_credential_sync import HOME, WORK
from tests.test_switch import SwitchTestCase


class CliSwitchTest(SwitchTestCase):
    def setUp(self):
        super().setUp()
        # 命令列讀真實的環境變數：假 claude 是批次檔，要有 COMSPEC 才開得起來
        self.env.update(SYSTEMROOT=os.environ.get("SYSTEMROOT", ""), COMSPEC=os.environ.get("COMSPEC", ""))

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

    def test_failed_verification_exits_three_but_the_switch_stays_written(self):
        self.script_queries({0: {"usage": "silent"}})
        code, out, err = self.run_cli("switch", "home", "--yes")
        self.assertEqual((code, out), (3, ""))
        self.assertEqual(err.strip(), "已切換到「home」，但替它查詢額度失敗，沒能確認切換有生效：Claude Code 已結束，但額度快取沒有更新。\n"
                                      "要回到切換前的帳號：python -m cc_quota_tracker switch --previous --yes")
        self.assertEqual(self.current().read_bytes(), self.snapshot("home").read_bytes())

    def test_failed_verification_in_english(self):
        self.script_queries({0: {"usage": "error", "message": "Not logged in"}})
        code, _, err = self.run_cli("switch", "home", "--yes", system_language="en-US")
        self.assertEqual(code, 3)
        self.assertEqual(err.strip(), 'Switched to "home", but the usage query for it failed, so the switch '
                                      "couldn't be confirmed: Claude Code reported an error: Not logged in\n"
                                      "To go back to the account you were using: "
                                      "python -m cc_quota_tracker switch --previous --yes")

    def test_old_account_query_failure_is_not_mentioned(self):
        """切換前替舊帳號的查詢失敗：切換照常、訊息與成功時一樣、結束代碼 0。"""
        self.write_cache(oauth="acct-w", account_uuid="acct-w", fetched_at=NOW - timedelta(hours=3))
        talk = self.paths.claude_dir / "projects" / "proj" / "s1.jsonl"
        talk.parent.mkdir(parents=True)
        talk.write_text('{"type":"user"}\n', encoding="utf-8")
        os.utime(talk, ((NOW - timedelta(hours=2)).timestamp(),) * 2)
        self.script_queries({0: {"usage": "silent"}})
        code, out, err = self.run_cli("switch", "home", "--yes")
        self.assertEqual((code, out.strip(), err), (0, "已切換到「home」", ""))
        self.assertEqual(self.starts(), 2)

    def test_wrong_arguments_are_a_usage_error(self):
        self.assertEqual(self.run_cli("switch")[0], 2)
        self.assertEqual(self.run_cli("switch", "home", "--yes", "extra")[0], 2)
        self.assertEqual(self.run_cli("switch", "--yes", "--yes")[0], 2)
        self.assertEqual(self.run_cli("switch", "--previous", "home", "--yes")[0], 2)

    def test_help_mentions_switch_and_yes(self):
        cases = (("zh-TW", "switch <帳號標籤>", "已寫入但驗證失敗"), ("en-US", "switch <label>", "3 if written but"))
        for lang, label, exit_three in cases:
            with self.subTest(lang):
                code, out, _ = self.run_cli("--help", system_language=lang)
                self.assertEqual(code, 0)
                self.assertIn(label, out)
                self.assertIn("switch --previous --yes", out)
                self.assertIn("--yes", out)
                self.assertIn(exit_three, out)  # 結束代碼 3 也包含「已寫入但驗證失敗」

    def test_switch_log_gets_one_line(self):
        log = self.home / ".claude-multi" / ".state" / "switches.jsonl"
        before = len(log.read_text(encoding="utf-8").splitlines())
        self.run_cli("switch", "home", "--yes")
        self.run_cli("list")
        lines = log.read_text(encoding="utf-8").splitlines()[before:]
        self.assertEqual([json.loads(line)["accountId"] for line in lines], ["acct-h"])

    def test_restore_succeeds(self):
        before = self.untouched()
        self.run_cli("switch", "home", "--yes")
        code, out, err = self.run_cli("switch", "--previous", "--yes")
        self.assertEqual((code, out.strip(), err), (0, "已還原上一次切換", ""))
        self.assertEqual(self.untouched()[0], before[0])
        self.assertEqual(json.loads(self.paths.claude_json.read_text(encoding="utf-8"))["oauthAccount"]["accountUuid"],
                         "acct-w")

    def test_restore_with_yes_first_and_in_english(self):
        self.run_cli("switch", "home", "--yes")
        code, out, _ = self.run_cli("switch", "--yes", "--previous", system_language="en-US")
        self.assertEqual((code, out.strip()), (0, "Restored the previous switch"))

    def test_restore_without_yes_prints_usage_and_writes_nothing(self):
        self.run_cli("switch", "home", "--yes")
        before = self.untouched()
        code, out, err = self.run_cli("switch", "--previous")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("switch --previous --yes", err)
        self.assertEqual(self.untouched(), before)

    def test_nothing_to_restore_exits_one_and_writes_nothing(self):
        before = self.untouched()
        code, out, err = self.run_cli("switch", "--previous", "--yes")
        self.assertEqual((code, out, err.strip()), (1, "", "沒有可還原的切換前憑證，沒有切換。"))
        self.assertEqual(self.untouched(), before)

    def test_expired_pre_switch_credential_exits_one_and_writes_nothing(self):
        self.run_cli("switch", "home", "--yes")
        self.clock.now = WORK + timedelta(seconds=1)
        before = self.untouched()
        code, _, err = self.run_cli("switch", "--previous", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("切換前憑證已過期", err)
        self.assertEqual(self.untouched(), before)

    def test_restore_with_failed_verification_exits_three_but_stays_written(self):
        self.run_cli("switch", "home", "--yes")
        self.script_queries({n: {"usage": "silent"} for n in range(5)})
        code, out, err = self.run_cli("switch", "--previous", "--yes")
        self.assertEqual((code, out), (3, ""))
        self.assertEqual(err.strip(), "已還原上一次切換，但還原後的帳號查詢額度失敗，未能確認還原有生效："
                                      "Claude Code 已結束，但額度快取沒有更新。")
        self.assertEqual(json.loads(self.paths.claude_json.read_text(encoding="utf-8"))["oauthAccount"]["accountUuid"],
                         "acct-w")
