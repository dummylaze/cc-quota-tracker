import json
import os
import sys
import unittest
from datetime import timedelta

from cc_quota_tracker import COMMAND
from cc_quota_tracker.board import Role
from cc_quota_tracker.render_text import render
from tests.fakehome import NOW, HomeTestCase, WindowsAclAssertions


class SwitchTestCase(HomeTestCase):
    def manage(self, label, refresh, account_uuid):
        """在 Claude Code 登入某帳號並納管它。"""
        self.log_in(refresh=refresh, account_uuid=account_uuid)
        self.core.add(label)

    def state_dir(self):
        return self.home / ".claude-multi" / ".state"

    def switch_log(self):
        path = self.state_dir() / "switches.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def new_lines(self, action):
        """執行 action 之後，切換紀錄新追加的那幾行。"""
        before = len(self.switch_log())
        action()
        return self.switch_log()[before:]

    def poll_after(self, *steps):
        def run():
            for step in steps:
                step()
            self.core.poll()
        return self.new_lines(run)

    def cards(self):
        return {card.account_key: card for card in self.core.poll().cards}


class NoSwitchTest(SwitchTestCase):
    def setUp(self):
        super().setUp()
        self.manage("work", "rt-w", "acct-w")
        self.core.poll()

    def test_refresh_is_not_a_switch(self):
        self.assertEqual(self.poll_after(lambda: self.write_credentials(refresh="rt-w", access="at-new")), [])

    def test_unchanged_fingerprint_over_many_rounds_records_nothing(self):
        self.assertEqual(self.poll_after(self.core.poll, self.core.poll), [])

    def test_unreadable_current_credential_is_not_a_switch(self):
        path = self.paths.claude_dir / ".credentials.json"
        self.assertEqual(self.poll_after(path.unlink), [])
        self.assertEqual(self.poll_after(lambda: self.write_credentials(refresh="rt-w")), [])


class SwitchLogTest(SwitchTestCase):
    def setUp(self):
        super().setUp()
        self.manage("work", "rt-w", "acct-w")
        self.manage("home", "rt-h", "acct-h")
        self.core.poll()

    def test_switch_to_a_watched_account_records_its_bound_id(self):
        self.clock.advance(minutes=5)
        lines = self.poll_after(lambda: self.log_in(refresh="rt-w", account_uuid="acct-w"))
        self.assertEqual(lines, [{"at": self.clock.now.isoformat(), "accountId": "acct-w",
                                  "source": "observed"}])

    def test_switch_matched_by_fingerprint_does_not_need_oauth_account(self):
        lines = self.poll_after(lambda: self.write_credentials(refresh="rt-w"))  # .claude.json 還沒跟上
        self.assertEqual([line["accountId"] for line in lines], ["acct-w"])

    def test_renamed_snapshot_records_the_same_id(self):
        os.rename(self.home / ".claude-multi" / "work.json", self.home / ".claude-multi" / "office.json")
        lines = self.poll_after(lambda: self.log_in(refresh="rt-w", account_uuid="acct-w"))
        self.assertEqual([line["accountId"] for line in lines], ["acct-w"])
        self.assertNotIn("office", json.dumps(self.switch_log()))

    def test_switch_to_an_unwatched_account_records_the_oauth_id(self):
        lines = self.poll_after(lambda: self.log_in(refresh="rt-x", account_uuid="acct-x"))
        self.assertEqual([line["accountId"] for line in lines], ["acct-x"])

    def test_switch_without_any_id_still_records_a_line(self):
        def log_in_without_claude_json():
            self.paths.claude_json.unlink()
            self.write_credentials(refresh="rt-x")
        lines = self.poll_after(log_in_without_claude_json)
        self.assertEqual([(line["accountId"], line["source"]) for line in lines], [(None, "observed")])

    def test_switch_to_a_snapshot_without_binding_records_null(self):
        self.write_credentials(refresh="rt-s")
        self.paths.claude_json.unlink()
        self.core.add("spare")  # 讀不到識別碼：沒有綁定
        self.log_in(refresh="rt-w", account_uuid="acct-w")
        self.core.poll()
        lines = self.poll_after(lambda: self.write_credentials(refresh="rt-s"))
        self.assertEqual([line["accountId"] for line in lines], [None])

    def test_log_is_append_only(self):
        self.poll_after(lambda: self.log_in(refresh="rt-w", account_uuid="acct-w"))
        path = self.state_dir() / "switches.jsonl"
        before = path.read_bytes()
        self.poll_after(lambda: self.log_in(refresh="rt-h", account_uuid="acct-h"))
        after = path.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertEqual([line["accountId"] for line in self.switch_log()[-2:]], ["acct-w", "acct-h"])

    def test_switch_is_on_the_board_in_the_same_round(self):
        self.log_in(refresh="rt-w", account_uuid="acct-w")
        self.assertEqual(self.cards()["claude:work"].role, Role.ACTIVE)


class RestartTest(SwitchTestCase):
    def test_first_round_ever_records_the_active_account(self):
        self.manage("work", "rt-w", "acct-w")
        self.assertEqual([line["accountId"] for line in self.poll_after()], ["acct-w"])

    def test_restart_without_switch_records_nothing(self):
        self.manage("work", "rt-w", "acct-w")
        self.core.poll()
        self.start()
        self.assertEqual(self.poll_after(), [])

    def test_switch_while_not_running_is_recorded_on_restart(self):
        self.manage("work", "rt-w", "acct-w")
        self.manage("home", "rt-h", "acct-h")
        self.core.poll()
        self.log_in(refresh="rt-w", account_uuid="acct-w")
        self.start()
        self.assertEqual([line["accountId"] for line in self.poll_after()], ["acct-w"])


class RotationTest(SwitchTestCase):
    def setUp(self):
        super().setUp()
        self.manage("home", "rt-h", "acct-h")
        self.manage("work", "rt-w", "acct-w")
        self.core.poll()
        self.snapshot = (self.home / ".claude-multi" / "work.json").read_bytes()

    def rotate(self):
        self.write_credentials(refresh="rt-w2")  # oauthAccount 仍是 acct-w

    def test_rotation_is_not_a_switch(self):
        self.assertEqual(self.poll_after(self.rotate), [])

    def test_rotation_flags_the_snapshot_and_keeps_the_account_active(self):
        self.rotate()
        card = self.core.poll().cards[0]
        self.assertEqual((card.account_key, card.role, card.snapshot_invalid), ("claude:work", Role.ACTIVE, True))

    def test_flag_stays_on_later_rounds_and_after_restart(self):
        self.rotate()
        self.core.poll()
        self.core.poll()
        self.start()
        self.assertTrue(self.cards()["claude:work"].snapshot_invalid)

    def test_rotation_leaves_the_snapshot_file_unchanged(self):
        self.rotate()
        self.core.poll()
        self.core.poll()
        self.assertEqual((self.home / ".claude-multi" / "work.json").read_bytes(), self.snapshot)

    def test_managing_again_clears_the_flag_without_a_switch(self):
        self.rotate()
        self.core.poll()
        lines = self.poll_after(lambda: self.core.add("work"))
        self.assertEqual(lines, [])
        self.assertFalse(self.cards()["claude:work"].snapshot_invalid)

    def test_oauth_account_catching_up_later_turns_it_into_a_switch(self):
        """Claude Code 先寫憑證、後寫 .claude.json：第一輪看起來像輪替，oauthAccount 一換就改判為切換。"""
        self.rotate()
        self.core.poll()
        lines = self.poll_after(lambda: self.log_in(refresh="rt-w2", account_uuid="acct-x"))
        self.assertEqual([line["accountId"] for line in lines], ["acct-x"])
        cards = self.cards()
        self.assertEqual(cards[None].role, Role.UNWATCHED)
        self.assertFalse(cards["claude:work"].snapshot_invalid)

    def test_switch_to_another_snapshot_after_rotation(self):
        self.rotate()
        self.core.poll()
        lines = self.poll_after(lambda: self.log_in(refresh="rt-h", account_uuid="acct-h"))
        self.assertEqual([line["accountId"] for line in lines], ["acct-h"])
        self.assertFalse(self.cards()["claude:work"].snapshot_invalid)

    def test_different_oauth_account_is_a_switch_to_unwatched(self):
        lines = self.poll_after(lambda: self.log_in(refresh="rt-x", account_uuid="acct-x"))
        self.assertEqual([line["accountId"] for line in lines], ["acct-x"])

    def test_render_tells_how_to_manage_again(self):
        self.rotate()
        text = render(self.core.poll())
        self.assertIn("憑證快照已失效", text)
        self.assertIn(f"{COMMAND} add work", text)


class ReloginTest(SwitchTestCase):
    """先登入別的帳號、再以新的 refreshToken 重新登入已納管的帳號：指紋對不上任何憑證快照，識別碼卻綁著 B。"""
    def setUp(self):
        super().setUp()
        self.manage("a", "rt-a", "acct-a")
        self.manage("b", "rt-b", "acct-b")
        self.log_in(refresh="rt-a", account_uuid="acct-a")
        self.core.poll()
        self.snapshot = (self.home / ".claude-multi" / "b.json").read_bytes()

    def relogin_b(self):
        self.log_in(refresh="rt-b2", account_uuid="acct-b")

    def test_active_card_is_the_bound_account_flagged_invalid(self):
        self.relogin_b()
        board = self.core.poll()
        self.assertEqual([(c.account_key, c.role, c.snapshot_invalid) for c in board.cards],
                         [("claude:b", Role.ACTIVE, True), ("claude:a", Role.STANDBY, False)])

    def test_list_shows_invalid_and_how_to_manage_again(self):
        self.relogin_b()
        text = render(self.core.poll())
        self.assertIn("憑證快照已失效", text)
        self.assertIn(f"{COMMAND} add b", text)

    def test_logs_one_switch_for_the_bound_id_and_not_again(self):
        lines = self.poll_after(self.relogin_b)
        self.assertEqual([line["accountId"] for line in lines], ["acct-b"])
        self.assertEqual(self.poll_after(self.core.poll, self.core.poll), [])

    def test_flag_stays_on_later_rounds_and_after_restart(self):
        self.relogin_b()
        self.core.poll()
        self.start()
        self.assertEqual(self.new_lines(self.core.poll), [])
        self.assertTrue(self.cards()["claude:b"].snapshot_invalid)

    def test_rotation_of_the_active_account_is_still_not_a_switch(self):
        self.relogin_b()
        self.core.poll()
        self.assertEqual(self.poll_after(lambda: self.write_credentials(refresh="rt-b3")), [])
        self.assertTrue(self.cards()["claude:b"].snapshot_invalid)

    def test_credential_written_before_oauth_account_is_treated_as_rotation(self):
        """空窗：憑證先寫、oauthAccount 還是 acct-a，這一輪當作 A 被輪替；跟上的下一輪改判為切換、旗標移到 B。"""
        self.write_credentials(refresh="rt-b2")
        self.assertEqual(self.poll_after(), [])
        self.assertTrue(self.cards()["claude:a"].snapshot_invalid)
        lines = self.poll_after(lambda: self.write_claude_json(
            {"oauthAccount": {"accountUuid": "acct-b", "emailAddress": "someone@example.com"}}))
        self.assertEqual([line["accountId"] for line in lines], ["acct-b"])
        cards = self.cards()
        self.assertEqual((cards["claude:b"].role, cards["claude:b"].snapshot_invalid), (Role.ACTIVE, True))
        self.assertFalse(cards["claude:a"].snapshot_invalid)

    def test_unreadable_oauth_account_adds_no_flag(self):
        self.write_credentials(refresh="rt-x")
        self.paths.claude_json.unlink()
        cards = self.cards()
        self.assertEqual(cards[None].role, Role.UNWATCHED)
        self.assertFalse(any(c.snapshot_invalid for c in cards.values()))

    def test_unbound_oauth_account_is_still_unwatched(self):
        self.log_in(refresh="rt-x", account_uuid="acct-x")
        cards = self.cards()
        self.assertEqual(cards[None].role, Role.UNWATCHED)
        self.assertFalse(any(c.snapshot_invalid for c in cards.values()))

    def test_managing_again_clears_the_flag_without_a_switch(self):
        self.relogin_b()
        self.core.poll()
        self.assertEqual(self.poll_after(lambda: self.core.add("b")), [])
        card = self.cards()["claude:b"]
        self.assertEqual((card.role, card.snapshot_invalid), (Role.ACTIVE, False))

    def test_snapshot_file_is_not_written(self):
        self.relogin_b()
        self.core.poll()
        self.core.poll()
        self.assertEqual((self.home / ".claude-multi" / "b.json").read_bytes(), self.snapshot)

    def test_state_left_by_the_old_version_is_judged_without_a_switch(self):
        """舊版把這個情境存成「沒有旗標、當前指紋是新的」：升級後下一輪就改判，不補寫紀錄。"""
        self.relogin_b()
        observed = self.state_dir() / "observed.json"
        self.core.poll()
        data = json.loads(observed.read_text(encoding="utf-8"))
        data.pop("invalidSnapshot", None)
        observed.write_text(json.dumps(data), encoding="utf-8")
        self.start()
        self.assertEqual(self.new_lines(self.core.poll), [])
        self.assertTrue(self.cards()["claude:b"].snapshot_invalid)


class ReloginManySnapshotsTest(SwitchTestCase):
    """同一個識別碼綁了多份憑證快照：只標到期最晚的那份。"""
    def manage_expiring(self, label, refresh, account_uuid, days):
        self.write_credentials(refresh=refresh, refresh_expires_at=NOW + timedelta(days=days))
        self.write_claude_json({"oauthAccount": {"accountUuid": account_uuid, "emailAddress": "someone@example.com"}})
        self.core.add(label)

    def relogin(self):
        self.log_in(refresh="rt-new", account_uuid="acct-b")
        return self.core.poll()

    def flagged(self, board):
        return [c.account_key for c in board.cards if c.snapshot_invalid]

    def test_only_the_latest_expiry_is_flagged_and_the_other_stays_standby(self):
        self.manage_expiring("b-old", "rt-b1", "acct-b", 10)
        self.manage_expiring("b-new", "rt-b2", "acct-b", 25)
        self.manage_expiring("a", "rt-a", "acct-a", 20)
        self.log_in(refresh="rt-a", account_uuid="acct-a")
        self.core.poll()
        board = self.relogin()
        self.assertEqual(self.flagged(board), ["claude:b-new"])
        self.assertEqual(board.cards[0].account_key, "claude:b-new")
        self.assertEqual({c.account_key: c.role for c in board.cards[1:]},
                         {"claude:a": Role.STANDBY, "claude:b-old": Role.STANDBY})
        self.assertIn(f"{COMMAND} add b-new", render(board))

    def test_tie_goes_to_the_label_that_sorts_first(self):
        self.manage_expiring("b-2", "rt-b2", "acct-b", 25)
        self.manage_expiring("b-1", "rt-b1", "acct-b", 25)
        self.assertEqual(self.flagged(self.relogin()), ["claude:b-1"])

    def test_one_with_an_expiry_beats_one_without(self):
        self.manage_expiring("b-1", "rt-b1", "acct-b", 25)
        self.write_credentials(refresh="rt-b2", refresh_expires_at=None)
        self.core.add("b-0")
        self.assertEqual(self.flagged(self.relogin()), ["claude:b-1"])


class LastRunTest(SwitchTestCase):
    def last_run(self):
        return json.loads((self.state_dir() / "observed.json").read_text(encoding="utf-8"))["lastRunAt"]

    def test_every_round_updates_last_run(self):
        self.core.poll()
        self.assertEqual(self.last_run(), self.clock.now.isoformat())
        self.clock.advance(seconds=5)
        self.core.poll()
        self.assertEqual(self.last_run(), self.clock.now.isoformat())


class ReadOnlyTest(SwitchTestCase):
    def test_polling_never_touches_claude_code_files(self):
        self.manage("work", "rt-w", "acct-w")
        self.manage("home", "rt-h", "acct-h")
        settings = self.paths.claude_dir / "settings.json"
        settings.write_text("{}", encoding="utf-8")
        files = [self.paths.claude_json, self.paths.claude_dir / ".credentials.json", settings]
        before = [os.stat(p).st_mtime_ns for p in files]
        for _ in range(3):
            self.core.poll()
        self.write_credentials(refresh="rt-h2")  # 輪替之後同樣不寫
        before[1] = os.stat(files[1]).st_mtime_ns
        for _ in range(3):
            self.core.poll()
        self.assertEqual([os.stat(p).st_mtime_ns for p in files], before)


@unittest.skipUnless(sys.platform == "win32", "Windows ACL")
class SwitchLogPermissionTest(SwitchTestCase, WindowsAclAssertions):
    def test_tool_state_files_are_private(self):
        self.manage("work", "rt-w", "acct-w")
        self.core.poll()
        self.manage("home", "rt-h", "acct-h")
        self.core.poll()  # 第二行是追加的，不是重建
        self.assert_private(self.state_dir() / "switches.jsonl")
        self.assert_private(self.state_dir() / "observed.json")


if __name__ == "__main__":
    unittest.main()
