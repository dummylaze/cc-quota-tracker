import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from cc_quota_tracker import COMMAND
from tests.fakehome import NOW, claude_json, usage_cache
from tests.test_cli import CliTestCase
from tests.test_usage_query import LATER, install_fake_claude


class QueryCliTest(CliTestCase):
    """`query`：用假 claude（settings 的 claudeCommand 指向它）扮演 Claude Code，比對輸出與結束代碼。"""

    def setUp(self):
        super().setUp()
        self.env.update(SYSTEMROOT=os.environ.get("SYSTEMROOT", ""), COMSPEC=os.environ.get("COMSPEC", ""),
                        PATH=str(self.home / "empty-path"))  # 命令列讀真實環境變數：PATH 上沒有任何 claude
        self.fake_dir = self.home / "fake-bin"
        self.command = install_fake_claude(self.fake_dir)
        self.write_settings(providers={"claude": {"claudeCommand": str(self.command)}})
        self.write_cache(fetched_at=NOW)

    def script(self, usage="write", **fields):
        text = json.dumps(claude_json(usage_cache(fetched_at=LATER)))
        (self.fake_dir / "script.json").write_text(
            json.dumps(dict(usage=usage, cache=str(self.paths.claude_json), cache_text=text, **fields)),
            encoding="utf-8")

    def test_success_prints_the_new_observed_time_and_exits_zero(self):
        self.script()
        code, out, err = self.run_cli("query")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "額度已更新，最新觀測時間：" + LATER.astimezone().strftime("%Y-%m-%d %H:%M"))
        self.assertEqual(err, "")

    def test_each_failure_prints_its_reason_and_the_usage_fallback_and_exits_one(self):
        cases = [
            ("not found", dict(usage="write"), "找不到 claude 執行檔。請確認有在 PATH 裡，或在設定檔的 "
                                              "providers.claude.claudeCommand 填入完整路徑。"),
            ("timeout", dict(usage="hang"), "Claude Code 逾時沒有完成查詢。"),
            ("reported error", dict(usage="error", message="Not logged in · Please run /login"),
             "Claude Code 回報錯誤：Not logged in · Please run /login"),
            ("not written", dict(usage="silent"), "Claude Code 已結束，但額度快取沒有更新。"),
        ]
        for name, script, reason in cases:
            with self.subTest(name), mock.patch("cc_quota_tracker.usage_query.TIMEOUT", timedelta(seconds=1)):
                if name == "not found":
                    self.write_settings(providers={"claude": {"claudeCommand": str(self.home / "nowhere" / "claude.cmd")}})
                else:
                    self.write_settings(providers={"claude": {"claudeCommand": str(self.command)}})
                self.script(**script)
                code, out, err = self.run_cli("query")
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                self.assertEqual(err.strip(), f"查詢額度失敗：{reason}\n可改在 Claude Code 執行 /usage。")

    def test_reported_error_without_a_message(self):
        self.script(usage="crash", message="", exit=1)
        err = self.run_cli("query")[2]
        self.assertIn("Claude Code 回報錯誤，沒有附上訊息。", err)

    def test_reported_error_message_is_never_translated(self):
        self.script(usage="error", message="Not logged in · Please run /login")
        for language in ("zh-TW", "en"):
            with self.subTest(language):
                self.write_settings(language=language, providers={"claude": {"claudeCommand": str(self.command)}})
                self.assertIn("Not logged in · Please run /login", self.run_cli("query")[2])

    def test_english_output(self):
        self.write_settings(language="en", providers={"claude": {"claudeCommand": str(self.command)}})
        self.script()
        out = self.run_cli("query")[1]
        self.assertEqual(out.strip(), "Usage updated. Latest observed time: "
                         + LATER.astimezone().strftime("%Y-%m-%d %H:%M"))
        self.script(usage="silent")
        err = self.run_cli("query")[2]
        self.assertEqual(err.strip(), "Usage query failed: Claude Code finished, but the usage cache wasn't updated.\n"
                                      "You can run /usage in Claude Code instead.")
        self.assertNotRegex(out + err, r"[⺀-鿿]")

    def test_unreadable_settings_file_is_reported_before_the_query(self):
        """設定檔壞掉時 claudeCommand 當成沒填：要讓使用者知道自己填的路徑沒生效（比照 add／remove）。"""
        self.write_settings_text("{")
        self.script()
        code, out, err = self.run_cli("query")
        self.assertEqual(code, 1)  # PATH 上沒有 claude
        self.assertTrue(err.startswith("注意：設定檔無法讀取"), err)
        self.assertIn("查詢額度失敗", err)

    def test_takes_no_arguments_and_is_listed_in_the_usage(self):
        code, _, err = self.run_cli("query", "x")
        self.assertEqual(code, 2)
        self.assertIn(f"{COMMAND} query", err)
        self.assertIn("成功結束代碼 0，失敗 1", err)
        self.assertIn("exit code 0 on success, 1 on failure", self.run_cli(system_language="en-US")[2])


class ListQueryHintTest(CliTestCase):
    """`list` 在落後或讀數待更新時，寫出一句完整說明；沒有落後時不出現。"""
    HINT = {"zh-TW": f"讀數落後或待更新：可以執行 {COMMAND} query 查詢最新額度，或在 Claude Code 執行 /usage。",
            "en": f"Reading is lagging or pending: run {COMMAND} query to ask Claude Code for the latest usage, "
                  "or run /usage in Claude Code."}

    def talk(self, at):
        path = self.paths.claude_dir / "projects" / "proj" / "s1.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"type":"user"}\n', encoding="utf-8")
        os.utime(path, (at.timestamp(), at.timestamp()))

    def listed(self, language):
        self.write_settings(language=language)
        return self.run_cli("list")[1]

    def lagging(self):
        self.write_cache(fetched_at=datetime.now(timezone.utc) - timedelta(hours=1))
        self.talk(datetime.now(timezone.utc) - timedelta(minutes=5))

    def pending(self):
        self.write_credentials(refresh="rt-x")
        self.write_claude_json(claude_json(usage_cache(account_uuid="acct-other"), "acct-x"))

    def test_lagging_reading_shows_the_hint_in_both_languages(self):
        self.lagging()
        for language, hint in self.HINT.items():
            with self.subTest(language):
                self.assertEqual(self.listed(language).count(hint), 1)

    def test_pending_reading_shows_the_hint_in_both_languages(self):
        self.pending()
        for language, hint in self.HINT.items():
            with self.subTest(language):
                self.assertEqual(self.listed(language).count(hint), 1)

    def test_hint_comes_after_the_cards_and_before_the_watched_accounts_line(self):
        self.lagging()
        lines = self.listed("zh-TW").splitlines()
        self.assertEqual(lines[-2:], [self.HINT["zh-TW"], "尚未納管任何帳號"])

    def test_no_hint_when_nothing_is_lagging_or_pending(self):
        self.write_cache(fetched_at=datetime.now(timezone.utc))
        for language, hint in self.HINT.items():
            with self.subTest(language):
                self.assertNotIn(hint, self.listed(language))
        self.assertNotIn("query", self.listed("zh-TW"))


if __name__ == "__main__":
    unittest.main()
