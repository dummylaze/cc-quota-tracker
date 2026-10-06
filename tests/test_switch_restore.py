"""還原上一次切換：用切換前憑證把當前憑證與帳號資訊一起回到切換之前。還原本身也是一次切換，
拒絕時當前憑證與 Claude Code 設定檔的位元組完全不變。"""
import json
from datetime import timedelta

from cc_quota_tracker.board import Role, SwitchOutcome, SwitchRefusal, SwitchStep
from cc_quota_tracker.core import Core
from tests.fakehome import NOW
from tests.test_credential_sync import HOME, WORK
from tests.test_switch import SwitchTestCase, info


class RestoreTest(SwitchTestCase):
    def test_restore_returns_credential_and_account_info_to_before_the_switch(self):
        before = self.untouched()
        self.core.switch("home")
        result = self.core.restore_previous()
        self.assertIs(result.outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(self.current().read_bytes(), before[0])
        self.assertEqual(self.oauth_account(), info("acct-w"))
        cards = self.core.poll().cards
        self.assertEqual((cards[0].account_key, cards[0].role), ("claude:work", Role.ACTIVE))

    def test_only_the_account_info_key_of_the_settings_file_changes(self):
        self.queries_write_nothing()
        head = '{\n  "numStartups": 1.0,\n  "oauthAccount": '
        tail = ',\n  "名字": "\\u00fc",\n  "projects": {}\n}\n'
        self.claude_json().write_text(head + json.dumps(info("acct-w"), indent=2) + tail, encoding="utf-8")
        self.core.switch("home")
        self.core.restore_previous()
        text = self.claude_json().read_text(encoding="utf-8")
        self.assertTrue(text.startswith(head), text)
        self.assertTrue(text.endswith(tail), text)
        self.assertEqual(self.oauth_account(), info("acct-w"))

    def test_restoring_twice_goes_back_to_the_account_before_the_restore(self):
        self.core.switch("home")
        self.core.restore_previous()
        result = self.core.restore_previous()
        self.assertIs(result.outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(self.current().read_bytes(), self.snapshot("home").read_bytes())
        self.assertEqual(self.oauth_account(), info("acct-h"))

    def test_restore_saves_the_credential_it_replaces_as_the_new_pre_switch_credential(self):
        self.core.switch("home")
        home_credential = self.current().read_bytes()
        self.core.restore_previous()
        saved = json.loads(self.pre_switch().read_text(encoding="utf-8"))
        self.assertEqual(saved["credentials"].encode("utf-8"), home_credential)
        self.assertEqual(saved["accountInfo"], info("acct-h"))

    def test_restore_syncs_the_current_credential_first(self):
        """命令列不在 poll 同步：還原前同步，刷新過的當前憑證才不會隨還原丟掉。"""
        cli = Core(self.paths, self.clock, auto_query=False, sync_credentials=False)
        cli.switch("home")
        self.refresh("rt-h2", HOME)
        refreshed = self.current().read_bytes()
        self.assertIs(cli.restore_previous().outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(self.snapshot("home").read_bytes(), refreshed)
        self.assertIs(cli.restore_previous().outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(self.current().read_bytes(), refreshed)

    def test_an_unwatched_account_before_the_switch_can_be_restored(self):
        self.log_in_at("rt-x", "acct-x", NOW + timedelta(days=10))
        unwatched = self.current().read_bytes()
        self.core.poll()
        self.core.switch("home")
        result = self.core.restore_previous()
        self.assertIs(result.outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(json.loads(self.switch_log()[-1])["accountId"], "acct-x")  # 回到未監看帳號也記紀錄
        self.assertEqual(self.current().read_bytes(), unwatched)
        self.assertEqual(self.oauth_account(), info("acct-x"))
        board = self.core.poll()
        self.assertIs(board.cards[0].role, Role.UNWATCHED)
        self.assertEqual(len(board.cards), 3)  # 它沒有因為還原而變成監看帳號

    def test_restore_is_logged_once_with_the_restored_account_id(self):
        self.core.switch("home")
        before = len(self.switch_log())
        self.clock.advance(minutes=5)
        self.core.restore_previous()
        self.clock.advance(minutes=5)
        self.core.poll()
        self.core.poll()
        lines = self.switch_log()[before:]
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual((entry["accountId"], entry["at"]), ("acct-w", (NOW + timedelta(minutes=5)).isoformat()))

    def test_queries_the_restored_account_like_a_normal_switch(self):
        self.core.switch("home")
        starts = self.starts()
        steps = []
        self.core.restore_previous(on_step=steps.append)
        self.assertEqual(self.starts(), starts + 1)
        self.assertEqual(steps, [SwitchStep.SYNC, SwitchStep.WRITE, SwitchStep.QUERY_NEW])

    def test_failed_verification_leaves_the_restore_written(self):
        self.core.switch("home")
        self.queries_write_nothing()
        result = self.core.restore_previous()
        self.assertIs(result.outcome, SwitchOutcome.VERIFY_FAILED)
        self.assertIsNotNone(result.verify_failure)
        self.assertEqual(self.oauth_account(), info("acct-w"))


class RestoreRefusalTest(SwitchTestCase):
    def assert_refused(self, refusal):
        before = self.untouched()
        saved = self.pre_switch().read_bytes() if self.pre_switch().exists() else None
        result = self.core.restore_previous()
        self.assertEqual((result.outcome, result.refusal), (SwitchOutcome.REFUSED, refusal))
        self.assertEqual(self.untouched(), before)
        self.assertEqual(self.pre_switch().read_bytes() if self.pre_switch().exists() else None, saved)

    def test_no_pre_switch_credential(self):
        self.assert_refused(SwitchRefusal.NO_PREVIOUS)

    def test_expired_pre_switch_credential(self):
        self.core.switch("home")  # 切換前憑證是 work 那一次登入，到期時間 WORK
        self.clock.now = WORK + timedelta(seconds=1)
        self.assert_refused(SwitchRefusal.PREVIOUS_EXPIRED)

    def test_pre_switch_credential_about_to_expire_is_still_restored(self):
        self.core.switch("home")
        self.clock.now = WORK - timedelta(seconds=1)
        self.assertIs(self.core.restore_previous().outcome, SwitchOutcome.SWITCHED)

    def test_pre_switch_credential_without_account_info(self):
        """切換前的帳號資訊是空的：只還原憑證會讓帳號資訊錯配，所以視同沒有可還原的。"""
        self.core.switch("home")
        saved = json.loads(self.pre_switch().read_text(encoding="utf-8"))
        self.pre_switch().write_text(json.dumps({**saved, "accountInfo": None}), encoding="utf-8")
        self.assert_refused(SwitchRefusal.NO_PREVIOUS)

    def test_unreadable_pre_switch_file(self):
        self.core.switch("home")
        self.pre_switch().write_text("{not json", encoding="utf-8")
        self.assert_refused(SwitchRefusal.NO_PREVIOUS)

    def test_logged_out(self):
        self.core.switch("home")
        self.current().unlink()
        settings = self.claude_json().read_bytes()
        result = self.core.restore_previous()
        self.assertEqual((result.outcome, result.refusal), (SwitchOutcome.REFUSED, SwitchRefusal.UNREADABLE))
        self.assertFalse(self.current().exists())
        self.assertEqual(self.claude_json().read_bytes(), settings)

    def test_refusal_asks_no_step_callback(self):
        steps = []
        self.core.restore_previous(on_step=steps.append)
        self.assertEqual(steps, [])
