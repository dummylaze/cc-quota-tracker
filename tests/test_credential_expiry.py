import unittest
from datetime import timedelta

from cc_quota_tracker import COMMAND
from cc_quota_tracker.board import Role
from cc_quota_tracker.render_text import render
from tests.fakehome import NOW, HomeTestCase


class ExpiryTestCase(HomeTestCase):
    def manage(self, label, refresh, account_uuid, expires_in):
        """在 Claude Code 登入某帳號並納管它；憑證快照的 refreshToken 在 expires_in 之後到期。"""
        self.log_in(refresh=refresh, account_uuid=account_uuid)
        self.write_credentials(refresh=refresh, refresh_expires_at=NOW + expires_in)
        self.core.add(label)

    def cards(self):
        return {card.account_key: card for card in self.core.poll().cards}


class CredentialExpiryTest(ExpiryTestCase):
    def test_snapshot_expiring_in_five_days_warns(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=5))
        card = self.cards()["claude:work"]
        self.assertEqual(card.snapshot_days_left, 5)
        self.assertTrue(card.snapshot_expiring)

    def test_every_card_carries_days_left_even_without_warning(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=30))
        self.manage("home", "rt-h", "acct-h", timedelta(days=20))
        cards = self.cards()
        self.assertEqual(cards["claude:home"].role, Role.ACTIVE)
        self.assertEqual(cards["claude:work"].role, Role.STANDBY)
        self.assertEqual((cards["claude:work"].snapshot_days_left, cards["claude:work"].snapshot_expiring), (30, False))
        self.assertEqual((cards["claude:home"].snapshot_days_left, cards["claude:home"].snapshot_expiring), (20, False))

    def test_standby_card_warns_too(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=3))
        self.manage("home", "rt-h", "acct-h", timedelta(days=30))
        card = self.cards()["claude:work"]
        self.assertEqual(card.role, Role.STANDBY)
        self.assertTrue(card.snapshot_expiring)

    def test_exactly_seven_days_warns(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=7))
        card = self.cards()["claude:work"]
        self.assertEqual((card.snapshot_days_left, card.snapshot_expiring), (7, True))

    def test_partial_day_counts_as_a_whole_day(self):
        """剩 7 天又 1 小時還不到警示範圍，顯示 8 天；剩餘天數與警示用同一條界線。"""
        self.manage("work", "rt-w", "acct-w", timedelta(days=7, hours=1))
        card = self.cards()["claude:work"]
        self.assertEqual((card.snapshot_days_left, card.snapshot_expiring), (8, False))

    def test_days_left_follow_the_clock_without_file_changes(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=10))
        self.assertFalse(self.cards()["claude:work"].snapshot_expiring)
        self.clock.advance(days=4)
        card = self.cards()["claude:work"]
        self.assertEqual((card.snapshot_days_left, card.snapshot_expiring), (6, True))

    def test_expired_snapshot_warns_with_no_days_left(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=1))
        self.clock.advance(days=2)
        card = self.cards()["claude:work"]
        self.assertLessEqual(card.snapshot_days_left, 0)
        self.assertTrue(card.snapshot_expiring)

    def test_readding_the_same_label_clears_the_warning(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=5))
        self.manage("work", "rt-w2", "acct-w", timedelta(days=30))
        card = self.cards()["claude:work"]
        self.assertEqual((card.snapshot_days_left, card.snapshot_expiring), (30, False))

    def test_snapshot_without_expiry_time_has_no_days_left(self):
        self.log_in(refresh="rt-w", account_uuid="acct-w")
        path = self.paths.claude_dir / ".credentials.json"
        path.write_text('{"claudeAiOauth": {"refreshToken": "rt-w"}}', encoding="utf-8")
        self.core.add("work")
        card = self.cards()["claude:work"]
        self.assertEqual((card.snapshot_days_left, card.snapshot_expiring), (None, False))

    def test_unmanaged_card_has_no_days_left(self):
        self.log_in(refresh="rt-x", account_uuid="acct-x")
        card = self.core.poll().cards[0]
        self.assertEqual(card.role, Role.UNMANAGED)
        self.assertEqual((card.snapshot_days_left, card.snapshot_expiring), (None, False))


class ExpiryTextTest(ExpiryTestCase):
    def test_warning_carries_the_full_remedy(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=5))
        text = render(self.core.poll())
        self.assertIn("5 天", text)
        self.assertIn("work", text)
        self.assertIn(f"{COMMAND} add work", text)
        self.assertIn("重新登入", text)

    def test_days_left_are_shown_without_warning(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=30))
        text = render(self.core.poll())
        self.assertIn("30 天", text)
        self.assertNotIn(f"{COMMAND} add work", text)

    def test_expired_snapshot_says_expired(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=1))
        self.clock.advance(days=2)
        text = render(self.core.poll())
        self.assertIn("已過期", text)
        self.assertIn(f"{COMMAND} add work", text)


if __name__ == "__main__":
    unittest.main()
