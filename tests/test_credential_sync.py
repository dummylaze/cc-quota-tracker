"""憑證同步與持久的失效旗標（ADR-0011）：當前憑證被刷新後，看板每輪把它寫回出自同一次登入的那份憑證快照；
找不到同一次登入的證據時才標失效，旗標保留到重新納管為止。"""
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from unittest import mock

from cc_quota_tracker import atomic
from cc_quota_tracker.__main__ import main
from cc_quota_tracker.board import Role, WatchOnlyReason
from cc_quota_tracker.core import Core
from cc_quota_tracker.credstore import FileCredentialStore
from cc_quota_tracker.render_text import render
from tests.fakehome import NOW, HomeTestCase, WindowsAclAssertions

WORK = NOW + timedelta(days=30)  # work 那一次登入的 refreshToken 到期時間
HOME = NOW + timedelta(days=20)


class SyncTestCase(HomeTestCase):
    def log_in_at(self, refresh, account_uuid, expires_at):
        """在 Claude Code 登入某帳號：當前憑證與帳號資訊一起換；expires_at 是這一次登入的到期時間。"""
        self.write_credentials(refresh=refresh, refresh_expires_at=expires_at)
        self.write_claude_json({"oauthAccount": {"accountUuid": account_uuid, "emailAddress": "someone@example.com"}})

    def manage(self, label, refresh, account_uuid, expires_at):
        self.log_in_at(refresh, account_uuid, expires_at)
        self.core.add(label)

    def refresh(self, refresh, expires_at, jitter=timedelta(seconds=1.2)):
        """Claude Code 刷新：換一組 refreshToken，到期時間只有一兩秒的抖動；帳號資訊不動。"""
        self.write_credentials(refresh=refresh, refresh_expires_at=expires_at + jitter)

    def snapshot(self, label):
        return self.home / ".claude-multi" / f"{label}.json"

    def current(self):
        return self.paths.claude_dir / ".credentials.json"

    def cards(self, core=None):
        return {card.account_key: card for card in (core or self.core).poll().cards}

    def switch_log(self):
        path = self.home / ".claude-multi" / ".state" / "switches.jsonl"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


class SyncTest(SyncTestCase):
    def setUp(self):
        super().setUp()
        self.manage("home", "rt-h", "acct-h", HOME)
        self.manage("work", "rt-w", "acct-w", WORK)
        self.core.poll()

    def test_refresh_is_written_back_to_the_snapshot_of_the_same_login(self):
        self.refresh("rt-w2", WORK)
        self.core.poll()
        self.assertEqual(self.snapshot("work").read_bytes(), self.current().read_bytes())

    def test_other_snapshots_are_left_alone(self):
        before = self.snapshot("home").read_bytes()
        self.refresh("rt-w2", WORK)
        self.core.poll()
        self.assertEqual(self.snapshot("home").read_bytes(), before)

    def test_sixty_seconds_apart_still_counts_as_the_same_login(self):
        self.refresh("rt-w2", WORK, jitter=timedelta(seconds=60))
        self.core.poll()
        self.assertEqual(self.snapshot("work").read_bytes(), self.current().read_bytes())

    def test_more_than_sixty_seconds_apart_is_another_login(self):
        before = self.snapshot("work").read_bytes()
        self.refresh("rt-w2", WORK, jitter=timedelta(seconds=61))
        self.core.poll()
        self.assertEqual(self.snapshot("work").read_bytes(), before)

    def test_unchanged_credential_is_not_rewritten(self):
        mtime = self.snapshot("work").stat().st_mtime_ns
        self.write_credentials(refresh="rt-w", access="at-new", refresh_expires_at=WORK)  # 只換 accessToken
        self.core.poll()
        self.assertEqual(self.snapshot("work").stat().st_mtime_ns, mtime)

    def test_refresh_does_not_light_the_invalid_flag(self):
        self.refresh("rt-w2", WORK)
        cards = self.cards()
        self.assertEqual(cards["claude:work"].role, Role.ACTIVE)
        self.assertFalse(any(c.snapshot_invalid for c in cards.values()))
        self.assertNotIn("憑證快照已失效", render(self.core.poll()))

    def test_refresh_is_not_a_switch(self):
        before = self.switch_log()
        self.refresh("rt-w2", WORK)
        self.core.poll()
        self.refresh("rt-w3", WORK)
        self.core.poll()
        self.assertEqual(self.switch_log(), before)

    def test_synced_account_stays_managed(self):
        """寫回之後綁定跟著換到新的憑證指紋：帳號資訊仍算附有，帳號仍是納管帳號。"""
        self.refresh("rt-w2", WORK)
        card = self.cards()["claude:work"]
        self.assertEqual((card.switchable, card.watch_only_reason), (True, None))

    def test_old_fingerprint_binding_is_cleaned_up(self):
        old = FileCredentialStore(self.snapshot("work")).fingerprint()
        self.refresh("rt-w2", WORK)
        self.core.poll()
        bindings = json.loads((self.home / ".claude-multi" / ".state" / "bindings.json").read_text(encoding="utf-8"))
        new = FileCredentialStore(self.snapshot("work")).fingerprint()
        self.assertEqual(bindings.get(new), {"accountId": "acct-w"})
        self.assertNotIn(old, bindings)

    def test_refresh_while_not_running_is_caught_up_on_start(self):
        self.refresh("rt-w2", WORK)
        self.refresh("rt-w3", WORK, jitter=timedelta(seconds=-0.8))
        before = self.switch_log()
        self.start()
        cards = self.cards()
        self.assertEqual(self.snapshot("work").read_bytes(), self.current().read_bytes())
        self.assertEqual(self.switch_log(), before)
        self.assertFalse(cards["claude:work"].snapshot_invalid)

    def test_switched_away_account_stays_usable_once_synced(self):
        """用 /login 換到別的帳號：被換走的帳號在當前憑證帳號期間同步過，快照仍可以用。"""
        self.refresh("rt-w2", WORK)
        self.core.poll()
        rotated = self.current().read_bytes()
        self.log_in_at("rt-h", "acct-h", HOME)
        cards = self.cards()
        self.assertEqual(self.snapshot("work").read_bytes(), rotated)
        work = cards["claude:work"]
        self.assertEqual((work.role, work.snapshot_invalid, work.switchable), (Role.STANDBY, False, True))

    def test_failed_write_is_retried_next_round(self):
        before = self.snapshot("work").read_bytes()
        self.refresh("rt-w2", WORK)
        with mock.patch.object(atomic, "write_atomic", side_effect=OSError("disk full")):
            self.core.poll()
        self.assertEqual(self.snapshot("work").read_bytes(), before)
        self.core.poll()
        self.assertEqual(self.snapshot("work").read_bytes(), self.current().read_bytes())

    def test_refresh_held_back_without_account_info_is_not_a_switch(self):
        """寫回被擋、帳號資訊也讀不到：靠上一輪當前憑證的到期時間認出是同一次登入，不算切換。"""
        before = self.switch_log()
        self.paths.claude_json.unlink()
        self.refresh("rt-w2", WORK)
        with self.locked("bindings.json"):
            self.core.poll()
        self.assertEqual(self.switch_log(), before)

    def test_locked_bindings_file_holds_the_write_back(self):
        """綁定檔讀不到：寫回之後綁定換不過去，帳號會失去帳號資訊，所以這一輪不寫。"""
        before = self.snapshot("work").read_bytes()
        self.refresh("rt-w2", WORK)
        with self.locked("bindings.json"):
            self.core.poll()
        self.assertEqual(self.snapshot("work").read_bytes(), before)


class AmbiguousSyncTest(SyncTestCase):
    def test_two_matching_snapshots_get_neither(self):
        self.manage("work", "rt-w", "acct-w", WORK)
        self.manage("work-copy", "rt-c", "acct-w", WORK + timedelta(seconds=30))
        self.log_in_at("rt-w", "acct-w", WORK)
        self.core.poll()
        before = (self.snapshot("work").read_bytes(), self.snapshot("work-copy").read_bytes())
        self.refresh("rt-w2", WORK)
        cards = self.cards()
        self.assertEqual((self.snapshot("work").read_bytes(), self.snapshot("work-copy").read_bytes()), before)
        self.assertFalse(any(c.snapshot_invalid for c in cards.values()))  # 有同一次登入的證據，只是不確定是哪份


class CommandLineTest(SyncTestCase):
    """只有看板的 poll 會同步；命令列的 list、query、add、remove 不改寫任何憑證快照。"""
    def setUp(self):
        super().setUp()
        self.manage("home", "rt-h", "acct-h", HOME)
        self.manage("work", "rt-w", "acct-w", WORK)
        self.core.poll()
        self.refresh("rt-w2", WORK)
        self.before = self.snapshot("work").read_bytes()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with self.cli_environment(), redirect_stdout(out), redirect_stderr(err), \
                mock.patch("cc_quota_tracker.usage_query.find_command", return_value=None):
            code = main(list(args))
        return code, out.getvalue()

    def test_commands_leave_snapshots_alone(self):
        for args in (("list",), ("query",), ("add", "spare"), ("remove", "spare")):
            self.run_cli(*args)
            self.assertEqual(self.snapshot("work").read_bytes(), self.before, args)

    def test_list_after_a_refresh_shows_the_account_without_the_invalid_flag(self):
        _, out = self.run_cli("list")
        self.assertIn("work", out.splitlines()[0])
        self.assertNotIn("已失效", out)

    def test_board_after_list_still_sees_no_switch(self):
        """命令列先看到刷新後的憑證、看板之後才寫回：不算切換。"""
        self.run_cli("list")
        self.refresh("rt-w3", WORK)
        self.run_cli("list")
        before = self.switch_log()
        self.start()
        self.core.poll()
        self.assertEqual(self.switch_log(), before)
        self.assertEqual(self.snapshot("work").read_bytes(), self.current().read_bytes())


class StaleFlagTest(SyncTestCase):
    """對同一個帳號重新登入：當前憑證跟它綁定的快照不是同一次登入，標為失效，一直保留到重新納管。"""
    def setUp(self):
        super().setUp()
        self.manage("home", "rt-h", "acct-h", HOME)
        self.manage("work", "rt-w", "acct-w", WORK)
        self.core.poll()
        self.snapshot_bytes = self.snapshot("work").read_bytes()

    def relogin_work(self):
        self.log_in_at("rt-w9", "acct-w", NOW + timedelta(days=31))

    def test_relogin_flags_the_snapshot(self):
        self.relogin_work()
        card = self.cards()["claude:work"]
        self.assertEqual((card.role, card.snapshot_invalid, card.watch_only_reason),
                         (Role.ACTIVE, True, WatchOnlyReason.INVALID))

    def test_snapshot_is_not_rewritten_by_guessing_from_the_account_id(self):
        self.relogin_work()
        self.core.poll()
        self.core.poll()
        self.assertEqual(self.snapshot("work").read_bytes(), self.snapshot_bytes)

    def test_flag_stays_after_switching_to_another_account(self):
        self.relogin_work()
        self.core.poll()
        self.log_in_at("rt-h", "acct-h", HOME)
        cards = self.cards()
        self.assertEqual(cards["claude:home"].role, Role.ACTIVE)
        work = cards["claude:work"]
        self.assertEqual((work.role, work.snapshot_invalid, work.switchable), (Role.STANDBY, True, False))

    def test_flag_stays_after_restart(self):
        self.relogin_work()
        self.core.poll()
        self.log_in_at("rt-h", "acct-h", HOME)
        self.core.poll()
        self.start()
        self.assertTrue(self.cards()["claude:work"].snapshot_invalid)

    def test_standby_list_line_does_not_claim_the_account_is_signed_in(self):
        self.relogin_work()
        self.core.poll()
        self.log_in_at("rt-h", "acct-h", HOME)
        text = render(self.core.poll())
        self.assertNotIn("目前登入的就是這個帳號", text)
        self.assertIn("僅監看帳號：已失效", text)

    def test_managing_again_clears_the_flag(self):
        self.relogin_work()
        self.core.poll()
        self.log_in_at("rt-h", "acct-h", HOME)
        self.core.poll()
        self.log_in_at("rt-w9", "acct-w", NOW + timedelta(days=31))
        self.core.add("work")
        self.log_in_at("rt-h", "acct-h", HOME)
        work = self.cards()["claude:work"]
        self.assertEqual((work.snapshot_invalid, work.switchable), (False, True))
        observed = json.loads((self.home / ".claude-multi" / ".state" / "observed.json").read_text(encoding="utf-8"))
        self.assertEqual(observed["invalidSnapshots"], [])  # 重新納管換掉的舊憑證指紋不留在工具狀態裡

    def test_relogin_is_a_change_of_fingerprint_on_the_same_account_not_a_switch(self):
        before = self.switch_log()
        self.relogin_work()
        self.core.poll()
        self.assertEqual(self.switch_log(), before)

    def test_refresh_of_the_new_login_keeps_the_flag(self):
        self.relogin_work()
        self.core.poll()
        self.refresh("rt-w10", NOW + timedelta(days=31))
        self.assertTrue(self.cards()["claude:work"].snapshot_invalid)
        self.assertEqual(self.snapshot("work").read_bytes(), self.snapshot_bytes)

    def test_flag_survives_a_later_write_back_to_the_same_snapshot(self):
        """旗標只有重新納管才熄滅：之後就算又找到同一次登入、寫回了快照，旗標仍跟著它。"""
        self.relogin_work()
        self.core.poll()
        self.log_in_at("rt-h", "acct-h", HOME)
        self.core.poll()
        self.log_in_at("rt-w5", "acct-w", WORK)  # 別的工具還原了原本那次登入（輪替過的）
        cards = self.cards()
        self.assertEqual(self.snapshot("work").read_bytes(), self.current().read_bytes())
        self.assertTrue(cards["claude:work"].snapshot_invalid)

    def test_login_race_does_not_leave_a_flag_on_the_previous_account(self):
        """/login 先寫憑證、後寫帳號資訊：空窗那一輪暫時算在原帳號，跟上之後旗標移到新帳號，原帳號不留旗標。"""
        self.write_credentials(refresh="rt-h9", refresh_expires_at=NOW + timedelta(days=21))
        self.core.poll()
        self.write_claude_json({"oauthAccount": {"accountUuid": "acct-h", "emailAddress": "someone@example.com"}})
        self.core.poll()
        self.log_in_at("rt-w", "acct-w", WORK)
        cards = self.cards()
        self.assertFalse(cards["claude:work"].snapshot_invalid)
        self.assertTrue(cards["claude:home"].snapshot_invalid)


class OldStateFileTest(SyncTestCase):
    def test_flag_left_by_the_old_version_after_a_refresh_goes_out(self):
        """舊版在刷新後把快照標成失效（observed.json 只有一個 invalidSnapshot）：升級後第一輪寫回、旗標熄滅。"""
        self.manage("work", "rt-w", "acct-w", WORK)
        self.core.poll()
        old = FileCredentialStore(self.snapshot("work")).fingerprint()
        self.refresh("rt-w2", WORK)
        rotated = FileCredentialStore(self.current()).fingerprint()
        observed = self.home / ".claude-multi" / ".state" / "observed.json"
        observed.write_text(json.dumps({"lastRunAt": NOW.isoformat(), "fingerprint": rotated,
                                        "invalidSnapshot": old}), encoding="utf-8")
        self.refresh("rt-w3", WORK)
        before = self.switch_log()
        self.start()
        self.assertFalse(self.cards()["claude:work"].snapshot_invalid)
        self.assertEqual(self.switch_log(), before)


@unittest.skipUnless(sys.platform == "win32", "Windows ACL")
class SyncPermissionTest(SyncTestCase, WindowsAclAssertions):
    def test_written_back_snapshot_is_private(self):
        self.manage("work", "rt-w", "acct-w", WORK)
        self.core.poll()
        self.refresh("rt-w2", WORK)
        self.core.poll()
        self.assertEqual(self.snapshot("work").read_bytes(), self.current().read_bytes())
        self.assert_private(self.snapshot("work"))


if __name__ == "__main__":
    unittest.main()
