"""納管帳號與僅監看帳號：納管時保存帳號資訊，看板每張卡片帶「能不能切換」與原因，`list` 為僅監看帳號列出原因與補救。"""
import io
import json
import stat
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from unittest import mock

from cc_quota_tracker import COMMAND
from cc_quota_tracker.__main__ import main
from cc_quota_tracker import managed_directory
from cc_quota_tracker.board import Role, WatchOnlyReason
from cc_quota_tracker.managed_directory import PermissionState
from cc_quota_tracker.render_text import render
from tests.fakehome import NOW, HomeTestCase, WindowsAclAssertions

EMAIL = "someone@example.com"  # fakehome 的 oauthAccount 帶的 email


class SwitchableTestCase(HomeTestCase):
    def manage(self, label, refresh="rt-1", account_uuid="acct-1", expires_in=timedelta(days=30)):
        """在 Claude Code 登入某帳號並納管它；憑證快照的 refreshToken 在 expires_in 之後到期。"""
        self.log_in(refresh=refresh, account_uuid=account_uuid)
        self.write_credentials(refresh=refresh, refresh_expires_at=NOW + expires_in)
        self.core.add(label)

    def cards(self):
        return {card.account_key: card for card in self.core.poll().cards}

    def card(self, label):
        return self.cards()[f"claude:{label}"]

    def managed_dir(self):
        return self.home / ".claude-multi"

    def snapshot(self, label):
        return self.managed_dir() / f"{label}.json"

    def info_files(self):
        """納管目錄底下存帳號資訊的檔案（含 email 的那些）。"""
        return [p for p in self.managed_dir().rglob("*") if p.is_file() and EMAIL.encode() in p.read_bytes()]

    def drop_in(self, label, refresh, expires_in=timedelta(days=30)):
        """像使用者那樣直接把一份憑證檔放進納管目錄。"""
        self.write_credentials(refresh=refresh, refresh_expires_at=NOW + expires_in)
        credential = self.paths.claude_dir / ".credentials.json"
        self.managed_dir().mkdir(exist_ok=True)
        self.snapshot(label).write_bytes(credential.read_bytes())


class ManagedAccountTest(SwitchableTestCase):
    def test_account_added_from_a_login_with_info_is_managed(self):
        self.manage("work")
        card = self.card("work")
        self.assertTrue(card.switchable)
        self.assertIsNone(card.watch_only_reason)

    def test_standby_account_added_with_info_is_managed_too(self):
        self.manage("work", "rt-w", "acct-w")
        self.manage("home", "rt-h", "acct-h")
        cards = self.cards()
        self.assertIs(cards["claude:work"].role, Role.STANDBY)
        self.assertTrue(cards["claude:work"].switchable)
        self.assertTrue(cards["claude:home"].switchable)

    def test_unwatched_account_is_neither_switchable_nor_watch_only(self):
        self.log_in()
        card = self.core.poll().cards[0]
        self.assertIs(card.role, Role.UNWATCHED)
        self.assertFalse(card.switchable)
        self.assertIsNone(card.watch_only_reason)

    def test_expiring_but_not_yet_expired_stays_managed(self):
        self.manage("work", expires_in=timedelta(days=2))
        card = self.card("work")
        self.assertTrue(card.snapshot_expiring)
        self.assertTrue(card.switchable)
        self.assertIsNone(card.watch_only_reason)

    def test_the_whole_account_info_is_stored_with_the_snapshot(self):
        self.manage("work")
        stored = self.info_files()
        self.assertEqual(len(stored), 1)
        self.assertEqual(json.loads(stored[0].read_text(encoding="utf-8"))["emailAddress"], EMAIL)

    def test_account_info_survives_a_restart(self):
        self.manage("work")
        self.start()
        self.assertTrue(self.card("work").switchable)

    def test_account_info_without_a_login_id_is_not_kept(self):
        self.write_credentials()
        self.write_claude_json({"oauthAccount": {"emailAddress": EMAIL}})  # 沒有 accountUuid
        self.core.add("work")
        self.assertEqual(self.info_files(), [])
        self.assertIs(self.card("work").watch_only_reason, WatchOnlyReason.NO_ACCOUNT_INFO)


class WatchOnlyReasonTest(SwitchableTestCase):
    def test_imported_credential_file_is_watch_only_without_account_info(self):
        source = self.home / "work.json"
        source.write_bytes(self.write_credentials().read_bytes())
        self.core.import_snapshot(source, "work")
        card = self.card("work")
        self.assertFalse(card.switchable)
        self.assertIs(card.watch_only_reason, WatchOnlyReason.NO_ACCOUNT_INFO)

    def test_credential_file_dropped_into_the_directory_is_watch_only_without_account_info(self):
        self.drop_in("work", "rt-w")
        card = self.card("work")
        self.assertFalse(card.switchable)
        self.assertIs(card.watch_only_reason, WatchOnlyReason.NO_ACCOUNT_INFO)

    def test_snapshot_from_before_account_info_was_kept_is_watch_only(self):
        self.manage("work")
        for path in self.managed_dir().rglob("*"):  # 舊版納管：只有憑證快照與綁定
            if path.is_file() and EMAIL.encode() in path.read_bytes():
                path.unlink()
        card = self.card("work")
        self.assertFalse(card.switchable)
        self.assertIs(card.watch_only_reason, WatchOnlyReason.NO_ACCOUNT_INFO)

    def test_expired_snapshot_is_watch_only(self):
        self.manage("work", expires_in=timedelta(days=1))
        self.clock.advance(days=2)
        card = self.card("work")
        self.assertFalse(card.switchable)
        self.assertIs(card.watch_only_reason, WatchOnlyReason.EXPIRED)

    def test_expiry_is_judged_by_the_clock_on_every_poll(self):
        self.manage("work", expires_in=timedelta(days=1))
        self.assertTrue(self.card("work").switchable)
        self.clock.advance(days=1)  # 剛好到期那一刻算過期
        self.assertIs(self.card("work").watch_only_reason, WatchOnlyReason.EXPIRED)

    def test_snapshot_without_an_expiry_time_is_not_treated_as_expired(self):
        self.log_in()
        self.write_credentials(refresh_expires_at=None)
        self.core.add("work")
        self.assertTrue(self.card("work").switchable)

    def test_invalidated_snapshot_is_watch_only(self):
        self.manage("work", "rt-1", "acct-1")
        self.log_in(refresh="rt-2", account_uuid="acct-1")  # 同一帳號重新登入：憑證輪替，舊憑證快照作廢
        card = self.card("work")
        self.assertTrue(card.snapshot_invalid)
        self.assertFalse(card.switchable)
        self.assertIs(card.watch_only_reason, WatchOnlyReason.INVALID)

    def test_readding_brings_a_watch_only_account_back(self):
        self.manage("work", "rt-1", "acct-1")
        self.log_in(refresh="rt-2", account_uuid="acct-1")
        self.assertFalse(self.card("work").switchable)
        self.core.add("work")
        card = self.card("work")
        self.assertTrue(card.switchable)
        self.assertIsNone(card.watch_only_reason)

    def test_readding_an_expired_account_with_a_fresh_login_brings_it_back(self):
        self.manage("work", "rt-1", "acct-1", expires_in=timedelta(days=1))
        self.clock.advance(days=2)
        self.assertFalse(self.card("work").switchable)
        self.manage("work", "rt-2", "acct-1", expires_in=timedelta(days=30))
        self.assertTrue(self.card("work").switchable)

    def test_importing_over_a_managed_label_makes_it_watch_only(self):
        self.manage("work")
        source = self.home / "other.json"
        source.write_bytes(self.write_credentials(refresh="rt-9").read_bytes())
        self.core.import_snapshot(source, "work")
        self.assertIs(self.card("work").watch_only_reason, WatchOnlyReason.NO_ACCOUNT_INFO)
        self.assertEqual(self.info_files(), [])

    def test_replacing_a_snapshot_file_by_hand_does_not_inherit_the_old_account_info(self):
        self.manage("work", "rt-1", "acct-1")
        self.manage("home", "rt-2", "acct-2")  # 當前憑證是 home
        self.snapshot("work").write_bytes(self.snapshot("home").read_bytes())  # 把別的帳號的憑證放進 work.json
        self.core.poll()  # 補學綁定
        self.assertIs(self.card("work").watch_only_reason, WatchOnlyReason.NO_ACCOUNT_INFO)

    def test_removing_the_account_removes_its_account_info(self):
        self.manage("work")
        self.core.remove("work")
        self.assertEqual(self.info_files(), [])

    def test_a_snapshot_deleted_by_hand_leaves_no_account_info_for_a_later_drop_in(self):
        self.manage("work", "rt-1", "acct-1")
        self.snapshot("work").unlink()
        self.core.poll()
        self.drop_in("work", "rt-9")
        self.assertIs(self.card("work").watch_only_reason, WatchOnlyReason.NO_ACCOUNT_INFO)


class ReasonPriorityTest(SwitchableTestCase):
    """同時符合多個原因時只帶一個：已過期 > 已失效 > 沒有帳號資訊（使用者 2026-10-06 確認）。"""

    def test_expired_wins_over_no_account_info(self):
        self.drop_in("work", "rt-1", expires_in=timedelta(days=1))
        self.clock.advance(days=2)
        self.assertIs(self.card("work").watch_only_reason, WatchOnlyReason.EXPIRED)

    def test_expired_wins_over_invalid(self):
        self.manage("work", "rt-1", "acct-1", expires_in=timedelta(days=1))
        self.log_in(refresh="rt-2", account_uuid="acct-1")
        self.assertTrue(self.card("work").snapshot_invalid)
        self.clock.advance(days=2)
        self.assertIs(self.card("work").watch_only_reason, WatchOnlyReason.EXPIRED)

    def test_invalid_wins_over_no_account_info(self):
        self.manage("work", "rt-1", "acct-1")
        for path in self.info_files():
            path.unlink()
        self.log_in(refresh="rt-2", account_uuid="acct-1")
        card = self.card("work")
        self.assertTrue(card.snapshot_invalid)
        self.assertIs(card.watch_only_reason, WatchOnlyReason.INVALID)


class AccountInfoNeverShownTest(SwitchableTestCase):
    def test_email_appears_nowhere_on_the_board_or_in_the_list_text(self):
        self.manage("work", "rt-w", "acct-w")
        self.manage("home", "rt-h", "acct-h")
        board = self.core.poll()
        self.assertNotIn(EMAIL, repr(board))
        self.assertNotIn(EMAIL, render(board))
        self.assertNotIn("example.com", repr(board) + render(board))

    def test_email_appears_nowhere_in_the_command_line_output(self):
        self.log_in()
        out, err = io.StringIO(), io.StringIO()
        with self.cli_environment(), redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(main(["add", "work"]), 0)
            self.assertEqual(main(["list"]), 0)
        self.assertNotIn("example.com", out.getvalue() + err.getvalue())


class ListTextTest(SwitchableTestCase):
    def run_list(self, language="zh-TW"):
        """命令列用真實時鐘：憑證快照要到期得夠遠，免得先變成「已過期」。"""
        out = io.StringIO()
        with self.cli_environment(language), redirect_stdout(out):
            main(["list"])
        return out.getvalue()

    def test_managed_account_prints_no_reason(self):
        self.manage("work")
        text = render(self.core.poll())
        self.assertNotIn("僅監看", text)
        self.assertNotIn("重新納管", text)

    def test_each_reason_is_printed_with_the_command_to_manage_again(self):
        self.drop_in("legacy", "rt-1")
        self.manage("old", "rt-2", "acct-2", expires_in=timedelta(days=1))
        self.manage("rotated", "rt-3", "acct-3")
        self.log_in(refresh="rt-4", account_uuid="acct-3")
        self.clock.advance(days=2)
        self.write_credentials(refresh="rt-4", refresh_expires_at=NOW + timedelta(days=31))  # 重新登入：另一次登入
        text = render(self.core.poll())
        for label, reason in (("legacy", "沒有帳號資訊"), ("old", "已過期"), ("rotated", "已失效")):
            with self.subTest(label=label):
                self.assertIn(f"僅監看帳號：{reason}", text)
                self.assertIn(f"重新納管：在 Claude Code 登入這個帳號後，執行 {COMMAND} add {label}", text)

    def test_only_one_reason_is_printed_per_account(self):
        self.manage("work", "rt-1", "acct-1", expires_in=timedelta(days=1))
        self.log_in(refresh="rt-2", account_uuid="acct-1")
        self.clock.advance(days=2)
        text = render(self.core.poll())
        self.assertEqual(text.count("僅監看帳號："), 1)
        self.assertIn("僅監看帳號：已過期", text)

    def test_the_reason_sits_right_under_the_account_header(self):
        self.drop_in("work", "rt-1")
        lines = render(self.core.poll()).splitlines()
        header = next(i for i, line in enumerate(lines) if "work" in line)
        self.assertIn("僅監看帳號：沒有帳號資訊", lines[header + 1])
        self.assertIn(f"{COMMAND} add work", lines[header + 2])

    def test_unwatched_account_prints_no_reason(self):
        self.log_in()
        self.assertNotIn("僅監看帳號：", render(self.core.poll()))

    def test_list_command_prints_the_reason_in_english_too(self):
        self.drop_in("work", "rt-1", expires_in=timedelta(days=3650))
        text = self.run_list("en")
        self.assertIn("Watch-only account: no account info", text)
        self.assertIn(f"To manage it again: sign in to this account in Claude Code, then run {COMMAND} add work", text)

    def test_list_command_prints_the_reason(self):
        self.drop_in("work", "rt-1", expires_in=timedelta(days=3650))
        self.assertIn("僅監看帳號：沒有帳號資訊", self.run_list())


class AccountInfoPermissionCheckTest(SwitchableTestCase):
    """帳號資訊的權限也在納管時事後驗證、也算進 check 的權限狀態（以行為判定，不依平台的權限機制）。"""

    def loose(self, info):
        """假裝 info 這個路徑的權限查回來是鬆的，其餘照實。"""
        real = managed_directory.is_private
        return mock.patch("cc_quota_tracker.managed_directory.is_private", side_effect=lambda p: p != info and real(p))

    def test_adding_again_tightens_a_loose_account_info_file(self):
        self.manage("work")
        info = self.info_files()[0]
        with self.loose(info), mock.patch("cc_quota_tracker.managed_directory.make_private") as make:
            self.core.add("work")
        make.assert_any_call(info)

    def test_check_reports_untightened_when_the_account_info_is_loose(self):
        self.manage("work")
        self.assertIs(self.core_directory().permission_state(), PermissionState.TIGHTENED)
        with self.loose(self.info_files()[0]):
            self.assertIs(self.core_directory().permission_state(), PermissionState.UNTIGHTENED)

    def test_check_reports_untightened_when_the_account_info_directory_is_loose(self):
        self.manage("work")
        with self.loose(self.info_files()[0].parent):
            self.assertIs(self.core_directory().permission_state(), PermissionState.UNTIGHTENED)

    def core_directory(self):
        return managed_directory.ManagedDirectory(self.managed_dir())


@unittest.skipUnless(sys.platform == "win32", "Windows ACL")
class WindowsAccountInfoPermissionTest(WindowsAclAssertions, SwitchableTestCase):
    def test_account_info_and_its_directory_are_as_tight_as_the_snapshot(self):
        self.manage("work")
        self.assert_private(self.snapshot("work"))
        stored = self.info_files()
        self.assertEqual(len(stored), 1)
        self.assert_private(stored[0])
        self.assert_private(stored[0].parent)

    def test_account_info_is_tightened_when_the_managed_directory_was_loose(self):
        self.managed_dir().mkdir()  # 繼承暫存目錄的權限
        self.manage("work")
        for path in self.info_files():
            self.assert_private(path)


@unittest.skipIf(sys.platform == "win32", "POSIX mode bits")
class PosixAccountInfoPermissionTest(SwitchableTestCase):
    def test_account_info_is_600_and_its_directory_700(self):
        self.manage("work")
        stored = self.info_files()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stat.S_IMODE(stored[0].stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(stored[0].parent.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
