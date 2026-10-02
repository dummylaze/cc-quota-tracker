import ctypes
import json
import os
import subprocess
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from cc_quota_tracker.board import QueryFailure
from tests.fakehome import NOW, HomeTestCase, claude_json, usage_cache

FAKE_CLAUDE = Path(__file__).with_name("fake_claude.py")
LATER = NOW + timedelta(minutes=30)


def claude(**fields):
    return {"claude": fields}


def install_fake_claude(directory: Path) -> Path:
    """在 directory 放一支 claude.cmd：跟 npm 裝的 claude 一樣是批次檔，背後再開一個行程（這裡是 Python）。"""
    directory.mkdir(parents=True, exist_ok=True)
    command = directory / "claude.cmd"
    command.write_text(f'@setlocal\r\n@set "FAKE_CLAUDE_DIR={directory}"\r\n'
                       f'@"{sys.executable}" "{FAKE_CLAUDE}" %*\r\n', encoding="utf-8")
    return command


class UsageQueryTestCase(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.fake_dir = self.home / "fake-bin"
        self.command = install_fake_claude(self.fake_dir)
        self.write_settings(providers=claude(claudeCommand=str(self.command)))
        self.write_cache(fetched_at=NOW)
        self.core.poll()

    def script(self, usage="write", fetched_at=LATER, directory=None, **fields):
        """假 claude 的劇本：write 會把額度快取的觀測時間改成 fetched_at。"""
        cache = self.paths.claude_json
        text = json.dumps(claude_json(usage_cache(fetched_at=fetched_at)))
        (directory or self.fake_dir).joinpath("script.json").write_text(
            json.dumps(dict(usage=usage, cache=str(cache), cache_text=text, **fields)), encoding="utf-8")

    def record(self, directory=None):
        path = (directory or self.fake_dir) / "record.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def query(self, path=None):
        """查詢讀的是真實的環境變數：換成測試給定的，PATH 只留 path（預設沒有任何 claude）。"""
        env = dict(self.env, SYSTEMROOT=os.environ.get("SYSTEMROOT", ""), COMSPEC=os.environ.get("COMSPEC", ""),
                   PATH=str(path or self.home / "empty-path"))
        with mock.patch.dict(os.environ, env, clear=True):
            return self.core.query_usage()


class SuccessTest(UsageQueryTestCase):
    def test_success_moves_the_observed_time_forward(self):
        self.script()
        result = self.query()
        self.assertIsNone(result.failure)
        self.assertEqual(result.observed_at, LATER)
        self.assertEqual(self.core.poll().last_reading_at, LATER)


class FailureTest(UsageQueryTestCase):
    def assert_reading_unchanged(self):
        self.assertEqual(self.core.poll().last_reading_at, NOW)

    def test_claude_code_reports_an_error_with_its_original_message(self):
        self.script(usage="error", message="Not logged in · Please run /login")
        result = self.query()
        self.assertEqual(result.failure, QueryFailure.REPORTED_ERROR)
        self.assertEqual(result.message, "Not logged in · Please run /login")
        self.assert_reading_unchanged()

    def test_exiting_with_an_error_reports_what_it_printed(self):
        self.script(usage="crash", message="error: unknown option '--input-format'", exit=1)
        result = self.query()
        self.assertEqual((result.failure, result.message),
                         (QueryFailure.REPORTED_ERROR, "error: unknown option '--input-format'"))
        self.assert_reading_unchanged()

    def test_finishing_without_writing_the_usage_cache(self):
        self.script(usage="silent")
        self.assertEqual(self.query().failure, QueryFailure.NOT_WRITTEN)
        self.assert_reading_unchanged()

    def test_writing_the_same_observed_time_again_is_not_a_success(self):
        self.script(fetched_at=NOW)
        self.assertEqual(self.query().failure, QueryFailure.NOT_WRITTEN)

    def test_configured_command_that_does_not_exist(self):
        self.write_settings(providers=claude(claudeCommand=str(self.home / "nowhere" / "claude.cmd")))
        self.assertEqual(self.query().failure, QueryFailure.COMMAND_NOT_FOUND)
        self.assert_reading_unchanged()

    def test_timeout_is_measured_on_the_core_clock_and_ends_claude_code(self):
        self.script(usage="hang")
        self.clock.step = timedelta(seconds=1)  # 核心每看一次時鐘就過 1 秒：不必真的等 20 秒
        result = self.query()
        self.assertEqual(result.failure, QueryFailure.TIMEOUT)
        self.assertFalse(process_alive(self.record()["pid"]))  # 批次檔背後的行程也一起結束
        self.assert_reading_unchanged()


class CommandLookupTest(UsageQueryTestCase):
    def setUp(self):
        super().setUp()
        self.on_path = self.home / "on-path"
        install_fake_claude(self.on_path)
        self.script(directory=self.on_path)

    def test_null_finds_claude_on_path(self):
        self.write_settings(providers=claude(claudeCommand=None))
        self.assertIsNone(self.query(path=self.on_path).failure)
        self.assertIsNotNone(self.record(self.on_path))

    def test_configured_path_that_does_not_exist_does_not_fall_back_to_path(self):
        self.write_settings(providers=claude(claudeCommand=str(self.home / "nowhere" / "claude.cmd")))
        self.assertEqual(self.query(path=self.on_path).failure, QueryFailure.COMMAND_NOT_FOUND)
        self.assertIsNone(self.record(self.on_path))  # PATH 上那支從沒被叫起來

    def test_nothing_on_path(self):
        self.write_settings(providers=claude(claudeCommand=None))
        self.assertEqual(self.query().failure, QueryFailure.COMMAND_NOT_FOUND)


class SubprocessTest(UsageQueryTestCase):
    """假 claude 把收到的參數、環境與工作目錄寫出來。"""

    def queried(self):
        self.script()
        self.assertIsNone(self.query().failure)
        return self.record()

    def test_hooks_are_disabled(self):
        argv = self.queried()["argv"]
        self.assertEqual(json.loads(argv[argv.index("--settings") + 1]), {"disableAllHooks": True})

    def test_home_default_removes_claude_config_dir(self):
        self.env["CLAUDE_CONFIG_DIR"] = ""  # 空字串在本工具算沒設，但 Claude Code 未必這樣看：一律拿掉
        self.assertFalse(self.queried()["has_config_dir"])

    def test_settings_field_sets_claude_config_dir_to_the_resolved_directory(self):
        moved = self.make_dir("moved-claude")
        self.write_settings(claudeConfigDir=str(moved), providers=claude(claudeCommand=str(self.command)))
        self.start(CLAUDE_CONFIG_DIR=str(self.make_dir("ignored-env-dir")))
        self.write_cache(fetched_at=NOW)
        self.assertEqual(Path(self.queried()["config_dir"]), moved)

    def test_env_source_keeps_the_resolved_directory(self):
        moved = self.make_dir("env-claude")
        self.start(CLAUDE_CONFIG_DIR=str(moved))
        self.write_cache(fetched_at=NOW)
        self.assertEqual(Path(self.queried()["config_dir"]), moved)

    def test_working_directory_is_not_this_project(self):
        cwd = Path(self.queried()["cwd"]).resolve()
        self.assertNotIn(Path.cwd().resolve(), (cwd, *cwd.parents))

    @unittest.skipUnless(os.name == "nt" and ctypes.windll.kernel32.GetConsoleWindow(),
                         "只在 Windows、且測試本身有主控台視窗時有意義：沒有的話，子行程不加旗標也偵測不到視窗")
    def test_no_console_window_on_windows(self):
        self.assertFalse(self.queried()["console_window"])


class NoTranscriptTest(UsageQueryTestCase):
    def test_query_leaves_the_reading_up_to_date(self):
        """假 claude 跟真的查詢一樣不寫對話紀錄：查詢後的讀數不會因為查詢本身而落後。"""
        self.log_in(refresh="rt-w", account_uuid="acct-1")
        self.core.add("work")
        talk = self.paths.claude_dir / "projects" / "proj" / "s1.jsonl"
        talk.parent.mkdir(parents=True)
        talk.write_text('{"type":"user"}\n', encoding="utf-8")
        at = (NOW + timedelta(minutes=10)).timestamp()
        os.utime(talk, (at, at))
        self.write_cache(fetched_at=NOW)
        self.clock.advance(minutes=20)
        self.assertTrue(self.core.poll().cards[0].lagging)
        self.script()
        self.assertIsNone(self.query().failure)
        card = self.core.poll().cards[0]
        self.assertEqual(card.reading_age, timedelta(minutes=-10))  # LATER 比假時鐘晚 10 分鐘
        self.assertFalse(card.lagging)
        self.assertEqual(list(talk.parent.parent.rglob("*.jsonl")), [talk])


class ClaudeCommandSettingTest(UsageQueryTestCase):
    def test_invalid_values_are_named_and_never_fall_back_to_path(self):
        on_path = self.home / "on-path"
        install_fake_claude(on_path)
        self.script(directory=on_path)
        for value in ("claude", "", 123, True, [], {"path": "x"}, str(self.fake_dir)):
            with self.subTest(value=value):
                (on_path / "record.json").unlink(missing_ok=True)
                self.write_settings(providers=claude(claudeCommand=value))
                self.assertEqual(self.query(path=on_path).failure, QueryFailure.COMMAND_NOT_FOUND)
                self.assertIsNone(self.record(on_path))
                expected = () if value == str(self.fake_dir) else ("providers.claude.claudeCommand",)
                self.assertEqual(self.core.poll().invalid_settings, expected)  # 目錄是合法的絕對路徑，只是不是檔案

    def test_valid_values_are_not_named(self):
        for value in (None, str(self.command), str(self.home / "nowhere" / "claude.exe")):
            with self.subTest(value=value):
                self.write_settings(providers=claude(claudeCommand=value))
                self.assertEqual(self.core.poll().invalid_settings, ())

    def test_change_takes_effect_on_the_next_query_without_restarting(self):
        self.write_settings(providers=claude(claudeCommand=str(self.home / "nowhere" / "claude.cmd")))
        self.assertEqual(self.query().failure, QueryFailure.COMMAND_NOT_FOUND)
        self.write_settings(providers=claude(claudeCommand=str(self.command)))
        self.script()
        self.assertIsNone(self.query().failure)


def process_alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


if __name__ == "__main__":
    unittest.main()
