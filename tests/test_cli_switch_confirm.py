"""命令列 `switch` 沒帶 `--yes`：標準輸入是終端機就先顯示確認內容並詢問，不是終端機就用法錯誤。"""
from datetime import timedelta
from unittest import mock

from cc_quota_tracker.core import Core
from tests.fakehome import NOW
from tests.test_cli_switch import CliSwitchBase, Terminal
from tests.test_credential_sync import WORK
from tests.test_usage_query import claude

PROMPT = "繼續？[y/N] "


class CliConfirmTest(CliSwitchBase):
    def ask(self, *args, answer="y\n", **kw):
        return self.run_cli(*args, stdin=Terminal(answer), **kw)

    def test_the_prompt_shows_the_same_content_as_the_dialog_then_asks(self):
        code, out, err = self.ask("switch", "home")
        self.assertEqual((code, err), (0, ""))
        paragraphs = out.split("\n\n")
        self.assertEqual(paragraphs[0], "切換到「home」？")
        self.assertRegex(paragraphs[1], r"^憑證快照 20天0小時後到期（\d\d-\d\d \d\d:\d\d）$")
        self.assertEqual(paragraphs[2], "目前帳號「work」是監看帳號：切走之前，會先同步憑證至快照。")
        self.assertEqual(paragraphs[3], PROMPT + "已切換到「home」\n")  # 回答不回顯在輸出裡，所以結果緊接在提示後
        self.assertEqual(len(paragraphs), 4)

    def test_an_unwatched_current_account_gets_the_pre_switch_consequence(self):
        self.log_in_at("rt-x", "acct-x", NOW + timedelta(days=5))
        out = self.ask("switch", "home")[1]
        self.assertIn("目前帳號是未監看帳號：只會存成切換前憑證，且只留最新一份。", out)

    def test_an_invalid_snapshot_of_the_current_account_adds_one_line(self):
        self.log_in_at("rt-w2", "acct-w", WORK + timedelta(days=1))  # 同一個帳號重新登入：快照跟新登入不是同一次
        out = self.ask("switch", "home")[1]
        paragraphs = out.split("\n\n")
        self.assertEqual(paragraphs[3], "目前帳號快照已失效；用「還原上一次切換」，或在 Claude Code 重新登入後再重新納管。")
        self.assertEqual(paragraphs[4], PROMPT + "已切換到「home」\n")
        self.assertEqual(len(paragraphs), 5)

    def test_no_usage_numbers_are_shown(self):
        self.assertNotRegex(self.ask("switch", "home")[1], r"%|額度|讀數")

    def test_the_prompt_follows_the_language(self):
        code, out, _ = self.ask("switch", "home", system_language="en-US")
        self.assertEqual(code, 0)
        self.assertIn('Switch to "home"?', out)
        self.assertIn("Continue? [y/N] ", out)
        self.assertTrue(out.endswith('Switched to "home"\n'))

    def test_confirming_switches(self):
        self.script_queries({n: {} for n in range(30)})  # 每次切換查兩次，劇本要夠長
        for answer in ("y\n", "Y\n", "yes\n", "YES\n", " y \n"):
            with self.subTest(answer):
                self.run_cli("switch", "work", "--yes")  # 回到 work，下一輪才有 home 可切
                code, _, _ = self.ask("switch", "home", answer=answer)
                self.assertEqual(code, 0)
                self.assertEqual(self.current().read_bytes(), self.snapshot("home").read_bytes())

    def test_anything_else_is_a_refusal_that_writes_nothing(self):
        for answer in ("n\n", "no\n", "\n", "是\n", "yess\n", ""):
            with self.subTest(answer):
                before = self.untouched()
                code, out, err = self.ask("switch", "home", answer=answer)
                self.assertEqual(code, 1)
                self.assertEqual(err.strip(), "已取消，沒有切換。")
                self.assertTrue(out.endswith("\n\n" + PROMPT))
                self.assertEqual(self.untouched(), before)
                self.assertEqual(self.starts(), 0)

    def test_declining_in_english(self):
        code, _, err = self.ask("switch", "home", answer="n\n", system_language="en-US")
        self.assertEqual((code, err.strip()), (1, "Cancelled; nothing was switched."))

    def test_only_the_first_line_is_read(self):
        self.assertEqual(self.ask("switch", "home", answer="y\nn\n")[0], 0)

    def test_yes_skips_the_prompt_even_in_a_terminal(self):
        code, out, _ = self.ask("switch", "home", "--yes", answer="")
        self.assertEqual((code, out.strip()), (0, "已切換到「home」"))

    def test_a_target_that_would_be_refused_is_refused_without_asking(self):
        cases = {
            "nobody": "沒有帳號標籤為「nobody」的監看帳號。",
            "work": "「work」已經是當前憑證帳號。",
        }
        for label, message in cases.items():
            with self.subTest(label):
                before = self.untouched()
                code, out, err = self.ask("switch", label)
                self.assertEqual((code, out, err.strip()), (1, "", message))
                self.assertEqual(self.untouched(), before)

    def test_a_watch_only_target_is_refused_without_asking(self):
        self.clock.now = NOW + timedelta(days=30)
        code, out, err = self.ask("switch", "home")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("僅監看帳號", err)

    def test_not_a_terminal_without_yes_is_a_usage_error_and_writes_nothing(self):
        before = self.untouched()
        code, out, err = self.run_cli("switch", "home")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("switch <帳號標籤>", err)
        self.assertEqual(self.untouched(), before)

    def test_wrong_arguments_in_a_terminal_are_a_usage_error(self):
        for args in (("switch",), ("switch", "home", "extra"), ("switch", "--yes"), ("switch", "--previous", "home")):
            with self.subTest(args):
                code, out, err = self.ask(*args)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("switch", err)

    def test_a_repeated_yes_is_a_usage_error(self):
        for stdin in (None, Terminal("y\n")):
            with self.subTest(terminal=stdin is not None):
                before = self.untouched()
                code, out, err = self.run_cli("switch", "home", "--yes", "--yes", stdin=stdin)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("switch <帳號標籤>", err)
                self.assertEqual(self.untouched(), before)

    def test_interrupting_the_prompt_is_a_refusal_that_writes_nothing(self):
        class Interrupted(Terminal):
            def readline(self, *args):
                raise KeyboardInterrupt
        before = self.untouched()
        code, _, err = self.run_cli("switch", "home", stdin=Interrupted())
        self.assertEqual((code, err.strip()), (1, "已取消，沒有切換。"))
        self.assertEqual(self.untouched(), before)

    def test_asking_starts_no_automatic_query(self):
        """詢問（與預判的拒絕）不啟動任何查詢：額度讀數落後時，一般的 poll 會自動查詢，預判不會。"""
        self.write_settings(providers=claude(autoUsageQuery=True, claudeCommand=str(self.fake_dir / "claude.cmd")))
        self.write_cache(oauth="acct-w", account_uuid="acct-h")  # 額度快取還是別的帳號的：讀數待更新
        self.clock.advance(hours=1)
        with mock.patch.object(Core, "_launch") as launch:
            self.core.poll()
            self.assertEqual(launch.call_count, 1)  # 對照：一般的 poll 這時會自動查詢
            for args, answer in ((("switch", "home"), "n\n"), (("switch", "nobody"), "")):
                with self.subTest(args):
                    self.ask(*args, answer=answer)
                    self.assertEqual(launch.call_count, 1)

    def test_help_describes_the_prompt(self):
        cases = (("zh-TW", ("switch <帳號標籤> [--yes]", "switch --previous [--yes]"), "會先顯示確認內容並詢問"),
                 ("en-US", ("switch <label> [--yes]", "switch --previous [--yes]"), "asks before switching"))
        for lang, forms, line in cases:
            with self.subTest(lang):
                out = self.run_cli("--help", system_language=lang)[1]
                for form in forms:
                    self.assertIn(form, out)
                self.assertIn(line, out)


class CliRestoreConfirmTest(CliSwitchBase):
    def ask(self, *args, answer="y\n", **kw):
        return self.run_cli(*args, stdin=Terminal(answer), **kw)

    def test_the_prompt_shows_the_restore_content_then_asks(self):
        self.run_cli("switch", "home", "--yes")
        code, out, err = self.ask("switch", "--previous")
        self.assertEqual((code, err), (0, ""))
        paragraphs = out.split("\n\n")
        self.assertEqual(paragraphs[0], "還原上一次切換？")
        self.assertIn("會用切換前的憑證與帳號資訊換回去", paragraphs[1])
        self.assertRegex(paragraphs[2], r"^切換前憑證 \S+後到期（")
        self.assertEqual(paragraphs[3], PROMPT + "已還原上一次切換\n")

    def test_declining_writes_nothing(self):
        self.run_cli("switch", "home", "--yes")
        before = self.untouched()
        code, _, err = self.ask("switch", "--previous", answer="n\n")
        self.assertEqual((code, err.strip()), (1, "已取消，沒有切換。"))
        self.assertEqual(self.untouched(), before)

    def test_nothing_to_restore_is_refused_without_asking(self):
        before = self.untouched()
        code, out, err = self.ask("switch", "--previous")
        self.assertEqual((code, out, err.strip()), (1, "", "沒有可還原的切換前憑證，沒有切換。"))
        self.assertEqual(self.untouched(), before)

    def test_not_a_terminal_without_yes_is_a_usage_error_and_writes_nothing(self):
        self.run_cli("switch", "home", "--yes")
        before = self.untouched()
        code, out, err = self.run_cli("switch", "--previous")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("switch --previous", err)
        self.assertEqual(self.untouched(), before)
