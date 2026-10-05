"""切換本體：切換到某個帳號標籤，寫入它的憑證快照，Claude Code 設定檔只改帳號資訊那一個鍵。
拒絕時當前憑證與 Claude Code 設定檔的位元組完全不變。"""
import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from cc_quota_tracker import atomic
from cc_quota_tracker.board import Role, SwitchOutcome, SwitchRefusal, WatchOnlyReason
from cc_quota_tracker.core import Core
from tests.fakehome import NOW, WindowsAclAssertions, usage_cache
from tests.test_credential_sync import HOME, WORK, SyncTestCase
from tests.test_usage_query import claude, install_fake_claude


def info(account_uuid):
    return {"accountUuid": account_uuid, "emailAddress": "someone@example.com"}


def fetched(n):
    """假 claude 第 n 次（從 0 起算）被啟動時寫回的觀測時間：一次比一次晚，都在時鐘之前。"""
    return NOW - timedelta(hours=1) + timedelta(minutes=10 * n)


class SwitchTestCase(SyncTestCase):
    """切換會替新帳號查詢額度：預設有一支每次都寫回新讀數的假 claude，查詢一律成功。"""

    def setUp(self):
        super().setUp()
        self.manage("home", "rt-h", "acct-h", HOME)
        self.manage("work", "rt-w", "acct-w", WORK)
        self.fake_dir = self.home / "fake-bin"
        self.write_settings(providers=claude(claudeCommand=str(install_fake_claude(self.fake_dir))))
        self.script_queries()
        self.core.poll()

    def script_queries(self, runs=None):
        """假 claude 的劇本：第 n 次被啟動時寫回 fetched(n)，runs 是 {n: 那一次要蓋掉的欄位}。
        每次都記下被啟動當下的當前憑證（credential-at-start-<n>.txt）。"""
        runs = runs or {}
        fixed = {"usage": "write", "cache": str(self.paths.claude_json), "credential_path": str(self.current())}
        script = {**fixed, "runs": [{"usage_cache": usage_cache(fetched_at=fetched(n)), **runs.get(n, {})}
                                    for n in range(max([4, *runs]) + 1)]}
        (self.fake_dir / "script.json").write_text(json.dumps(script), encoding="utf-8")

    def queries_write_nothing(self):
        """假 claude 不碰額度快取：驗證會失敗，但 Claude Code 設定檔的內容只剩切換自己寫的，位元組逐字比對才有意義。"""
        self.script_queries({n: {"usage": "silent"} for n in range(5)})

    def starts(self):
        log = self.fake_dir / "starts.log"
        return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0

    def credential_at_start(self, n):
        """假 claude 第 n 次被啟動當下的當前憑證。"""
        return (self.fake_dir / f"credential-at-start-{n}.txt").read_bytes()

    def claude_json(self):
        return self.paths.claude_json

    def oauth_account(self):
        return json.loads(self.claude_json().read_text(encoding="utf-8"))["oauthAccount"]

    def pre_switch(self):
        return self.home / ".claude-multi" / ".state" / "pre-switch.json"

    def untouched(self):
        """當前憑證與 Claude Code 設定檔的位元組。"""
        return self.current().read_bytes(), self.claude_json().read_bytes()


class SwitchTest(SwitchTestCase):
    def test_switch_writes_the_target_snapshot_and_its_account_info(self):
        result = self.core.switch("home")
        self.assertIs(result.outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(self.current().read_bytes(), self.snapshot("home").read_bytes())
        self.assertEqual(self.oauth_account(), info("acct-h"))
        cards = self.core.poll().cards
        self.assertEqual((cards[0].account_key, cards[0].role), ("claude:home", Role.ACTIVE))

    def test_other_keys_of_the_claude_code_settings_file_are_kept_byte_for_byte(self):
        self.queries_write_nothing()
        head = '{\n  "numStartups": 1.0,\n  "tipsHistory": {\n    "x": 1e-07\n  },\n  "oauthAccount": '
        tail = ',\n  "名字": "\\u00fc",\n  "projects": {}\n}\n'
        self.claude_json().write_text(head + json.dumps(info("acct-w"), indent=2) + tail, encoding="utf-8")
        self.core.switch("home")
        text = self.claude_json().read_text(encoding="utf-8")
        self.assertTrue(text.startswith(head), text)
        self.assertTrue(text.endswith(tail), text)
        self.assertEqual(self.oauth_account(), info("acct-h"))

    def test_settings_written_after_the_switch_started_are_kept(self):
        """Claude Code 在切換寫入當前憑證時剛好也寫了設定檔：不得用先前讀到的版本整份蓋掉。"""
        real = atomic.write_atomic

        def write(path, *args, **kwargs):
            real(path, *args, **kwargs)
            if Path(path).name == ".credentials.json":
                data = json.loads(self.claude_json().read_text(encoding="utf-8"))
                self.claude_json().write_text(json.dumps({**data, "late": True}), encoding="utf-8")
        with mock.patch.object(atomic, "write_atomic", write):
            self.core.switch("home")
        data = json.loads(self.claude_json().read_text(encoding="utf-8"))
        self.assertIs(data["late"], True)
        self.assertEqual(data["oauthAccount"], info("acct-h"))

    def test_crlf_line_endings_are_kept(self):
        self.queries_write_nothing()
        head = b'{\r\n  "numStartups": 1,\r\n  "oauthAccount": '
        tail = b',\r\n  "projects": {}\r\n}\r\n'
        self.claude_json().write_bytes(head + json.dumps(info("acct-w")).encode() + tail)
        self.core.switch("home")
        data = self.claude_json().read_bytes()
        self.assertTrue(data.startswith(head), data)
        self.assertTrue(data.endswith(tail), data)
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))  # 換進去的帳號資訊也用同一種換行

    def test_the_poll_before_the_switch_starts_no_automatic_query(self):
        """看板開著時，切換前那一輪不自動查詢：切換的查詢只有切換前後那兩次（ADR-0010 修訂段）。"""
        self.write_settings(providers=claude(autoUsageQuery=True, claudeCommand=str(self.fake_dir / "claude.cmd")))
        self.write_cache(oauth="acct-w", account_uuid="acct-h")  # 額度快取還是別的帳號的：讀數待更新
        self.clock.advance(hours=1)
        with mock.patch.object(Core, "_launch") as launch:
            self.core.poll()
            self.assertEqual(launch.call_count, 1)  # 對照：一般的 poll 這時會自動查詢
            self.core.switch("home")
        self.assertEqual(launch.call_count, 1)

    def test_settings_file_without_account_info_gets_the_key(self):
        self.queries_write_nothing()
        self.claude_json().write_text('{"projects": {}}', encoding="utf-8")
        self.core.switch("home")
        data = json.loads(self.claude_json().read_text(encoding="utf-8"))
        self.assertEqual(data, {"projects": {}, "oauthAccount": info("acct-h")})

    def test_switch_is_logged_once_with_the_target_account_id(self):
        before = len(self.switch_log())
        self.core.switch("home")
        self.clock.advance(minutes=5)
        self.core.poll()
        self.core.poll()
        lines = self.switch_log()[before:]
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual((entry["accountId"], entry["at"]), ("acct-h", NOW.isoformat()))

    def test_switch_from_a_new_core_is_not_logged_again_by_the_window(self):
        """命令列與看板是兩個程序：看板下一輪偵測到同一次切換時不重複追加。"""
        before = len(self.switch_log())
        cli = Core(self.paths, self.clock, auto_query=False, sync_credentials=False)
        cli.switch("home")
        self.clock.advance(minutes=5)
        self.core.poll()
        lines = self.switch_log()[before:]
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["at"], NOW.isoformat())

    def test_switching_back_and_forth(self):
        self.core.switch("home")
        result = self.core.switch("work")
        self.assertIs(result.outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(self.current().read_bytes(), self.snapshot("work").read_bytes())
        self.assertEqual(self.oauth_account(), info("acct-w"))

    def test_leaving_account_keeps_no_invalid_flag(self):
        self.core.switch("home")
        cards = {c.account_key: c for c in self.core.poll().cards}
        self.assertFalse(cards["claude:work"].snapshot_invalid)
        self.assertTrue(cards["claude:work"].switchable)


class PreSwitchCredentialTest(SwitchTestCase):
    def test_current_credential_and_account_info_are_saved_before_writing(self):
        current, _ = self.untouched()
        self.core.switch("home")
        saved = json.loads(self.pre_switch().read_text(encoding="utf-8"))
        self.assertEqual(saved["credentials"].encode("utf-8"), current)
        self.assertEqual(saved["accountInfo"], info("acct-w"))

    def test_only_the_latest_one_is_kept(self):
        self.core.switch("home")
        home_credential = self.current().read_bytes()
        self.core.switch("work")
        saved = json.loads(self.pre_switch().read_text(encoding="utf-8"))
        self.assertEqual(saved["credentials"].encode("utf-8"), home_credential)
        self.assertEqual(saved["accountInfo"], info("acct-h"))

    def test_saving_an_unwatched_login_makes_no_card(self):
        self.log_in_at("rt-x", "acct-x", NOW + timedelta(days=10))
        board = self.core.poll()
        self.assertIs(board.cards[0].role, Role.UNWATCHED)
        self.core.switch("home")
        board = self.core.poll()
        self.assertEqual(board.watched_accounts, ("claude:home", "claude:work"))
        self.assertEqual(len(board.cards), 2)


@unittest.skipUnless(sys.platform == "win32", "ACL 只在 Windows 驗證")
class PreSwitchPermissionTest(SwitchTestCase, WindowsAclAssertions):
    def test_pre_switch_credential_is_tightened(self):
        self.core.switch("home")
        self.assert_private(self.pre_switch())


class RefusalTest(SwitchTestCase):
    def assert_refused(self, label, refusal, reason=None):
        before = self.untouched()
        result = self.core.switch(label)
        self.assertEqual((result.outcome, result.refusal, result.watch_only_reason),
                         (SwitchOutcome.REFUSED, refusal, reason))
        self.assertEqual(self.untouched(), before)
        self.assertFalse(self.pre_switch().exists())

    def test_unknown_label(self):
        self.assert_refused("nobody", SwitchRefusal.UNKNOWN_LABEL)

    def test_label_that_is_not_a_file_name(self):
        self.assert_refused("../work", SwitchRefusal.UNKNOWN_LABEL)

    def test_target_is_the_current_credential_account(self):
        self.assert_refused("work", SwitchRefusal.ALREADY_ACTIVE)

    def test_target_without_account_info(self):
        self.write_credentials(refresh="rt-d", refresh_expires_at=NOW + timedelta(days=5))
        (self.home / ".claude-multi" / "dropped.json").write_bytes(self.current().read_bytes())
        self.log_in_at("rt-w", "acct-w", WORK)
        self.core.poll()
        self.assert_refused("dropped", SwitchRefusal.WATCH_ONLY, WatchOnlyReason.NO_ACCOUNT_INFO)

    def test_expired_target(self):
        self.clock.now = HOME + timedelta(seconds=1)
        self.assert_refused("home", SwitchRefusal.WATCH_ONLY, WatchOnlyReason.EXPIRED)

    def test_unreadable_claude_code_settings_file(self):
        real = Path.read_bytes

        def read_bytes(path):
            if path == self.claude_json():
                raise PermissionError("locked by another process")
            return real(path)
        before = self.untouched()
        with self.locked(self.claude_json().name), mock.patch.object(Path, "read_bytes", read_bytes):
            result = self.core.switch("home")
        self.assertEqual((result.outcome, result.refusal), (SwitchOutcome.REFUSED, SwitchRefusal.UNREADABLE))
        self.assertEqual(self.untouched(), before)
        self.assertFalse(self.pre_switch().exists())

    def test_unparseable_claude_code_settings_file(self):
        self.claude_json().write_text("{not json", encoding="utf-8")
        self.assert_refused("home", SwitchRefusal.UNREADABLE)

    def test_logged_out(self):
        self.current().unlink()
        settings = self.claude_json().read_bytes()
        result = self.core.switch("home")
        self.assertEqual((result.outcome, result.refusal), (SwitchOutcome.REFUSED, SwitchRefusal.UNREADABLE))
        self.assertFalse(self.current().exists())
        self.assertEqual(self.claude_json().read_bytes(), settings)

    def test_locked_current_credential_writes_nothing(self):
        real = atomic.write_atomic

        def write(path, *args, **kwargs):
            if Path(path).name == ".credentials.json":
                raise PermissionError("locked")
            return real(path, *args, **kwargs)
        before = self.untouched()
        with mock.patch.object(atomic, "write_atomic", write):
            result = self.core.switch("home")
        self.assertEqual((result.outcome, result.refusal), (SwitchOutcome.REFUSED, SwitchRefusal.UNWRITABLE))
        self.assertEqual(self.untouched(), before)
        self.assertFalse(self.pre_switch().exists())

    def test_refused_write_keeps_the_previous_pre_switch_credential(self):
        """拒絕不丟掉上一次切換的還原點。"""
        self.core.switch("home")
        saved = self.pre_switch().read_bytes()
        real = atomic.write_atomic

        def write(path, *args, **kwargs):
            if Path(path).name == ".credentials.json":
                raise PermissionError("locked")
            return real(path, *args, **kwargs)
        with mock.patch.object(atomic, "write_atomic", write):
            self.core.switch("work")
        self.assertEqual(self.pre_switch().read_bytes(), saved)

    def test_current_credential_without_a_refresh_token(self):
        self.current().write_text(json.dumps({"claudeAiOauth": {"accessToken": "at-x"}}), encoding="utf-8")
        self.assert_refused("home", SwitchRefusal.UNREADABLE)


class WriteFailedTest(SwitchTestCase):
    def test_settings_file_write_failure_after_the_credential_is_reported_as_written(self):
        real = atomic.write_atomic

        def write(path, *args, **kwargs):
            if Path(path) == self.claude_json():
                raise PermissionError("locked")
            return real(path, *args, **kwargs)
        with mock.patch.object(atomic, "write_atomic", write):
            result = self.core.switch("home")
        self.assertIs(result.outcome, SwitchOutcome.WRITE_FAILED)
        self.assertEqual(self.current().read_bytes(), self.snapshot("home").read_bytes())


class SyncBeforeSwitchTest(SwitchTestCase):
    """命令列不在 poll 同步，但 switch 在寫入前同步一次。"""

    def setUp(self):
        super().setUp()
        self.cli = Core(self.paths, self.clock, auto_query=False, sync_credentials=False)

    def test_refreshed_credential_is_synced_back_before_switching_away(self):
        self.refresh("rt-w2", WORK)
        refreshed = self.current().read_bytes()
        self.assertIs(self.cli.switch("home").outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(self.snapshot("work").read_bytes(), refreshed)
        self.assertIs(self.cli.switch("work").outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(self.current().read_bytes(), refreshed)

    def test_failed_sync_of_a_watched_account_refuses(self):
        self.refresh("rt-w2", WORK)
        real = atomic.write_atomic

        def write(path, *args, **kwargs):
            if Path(path).name == "work.json":
                raise OSError("disk full")
            return real(path, *args, **kwargs)
        before = self.untouched()
        with mock.patch.object(atomic, "write_atomic", write):
            result = self.cli.switch("home")
        self.assertEqual((result.outcome, result.refusal), (SwitchOutcome.REFUSED, SwitchRefusal.SYNC_FAILED))
        self.assertEqual(self.untouched(), before)
        self.assertFalse(self.pre_switch().exists())

    def test_unwatched_current_account_needs_no_sync(self):
        self.log_in_at("rt-x", "acct-x", NOW + timedelta(days=10))
        self.assertIs(self.cli.switch("home").outcome, SwitchOutcome.SWITCHED)

    def test_invalid_current_snapshot_does_not_block_switching_away(self):
        """對同一個帳號重新登入：快照失效，沒有可同步的；切走照常，靠切換前憑證回來。"""
        self.log_in_at("rt-w9", "acct-w", NOW + timedelta(days=40))
        self.cli.poll()
        self.assertIs(self.cli.switch("home").outcome, SwitchOutcome.SWITCHED)


if __name__ == "__main__":
    unittest.main()
