import unittest
from datetime import timedelta

from cc_quota_tracker import COMMAND
from cc_quota_tracker.board import CountdownFormat, Role
from cc_quota_tracker.render_text import render
from tests.fakehome import NOW, HomeTestCase


def local(when, fmt):
    """畫面上的絕對時間一律是本機時區。"""
    return when.astimezone().strftime(fmt)


class ExpiryTestCase(HomeTestCase):
    def manage(self, label, refresh, account_uuid, expires_in):
        """在 Claude Code 登入某帳號並納管它；憑證快照的 refreshToken 在 expires_in 之後到期。"""
        self.log_in(refresh=refresh, account_uuid=account_uuid)
        self.write_credentials(refresh=refresh, refresh_expires_at=NOW + expires_in)
        self.core.add(label)

    def cards(self):
        return {card.account_key: card for card in self.core.poll().cards}

    def card(self, expires_in):
        self.manage("work", "rt-w", "acct-w", expires_in)
        return self.cards()["claude:work"]


class CredentialExpiryTest(ExpiryTestCase):
    def test_snapshot_expiring_in_five_days_warns(self):
        card = self.card(timedelta(days=5))
        self.assertEqual(card.snapshot_expires_at, NOW + timedelta(days=5))
        self.assertTrue(card.snapshot_expiring)

    def test_every_card_carries_its_expiry_even_without_warning(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=30))
        self.manage("home", "rt-h", "acct-h", timedelta(days=20))
        cards = self.cards()
        self.assertEqual(cards["claude:home"].role, Role.ACTIVE)
        self.assertEqual(cards["claude:work"].role, Role.STANDBY)
        self.assertEqual((cards["claude:work"].snapshot_expires_at, cards["claude:work"].snapshot_expiring),
                         (NOW + timedelta(days=30), False))
        self.assertEqual((cards["claude:home"].snapshot_expires_at, cards["claude:home"].snapshot_expiring),
                         (NOW + timedelta(days=20), False))

    def test_standby_card_warns_too(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=3))
        self.manage("home", "rt-h", "acct-h", timedelta(days=30))
        card = self.cards()["claude:work"]
        self.assertEqual(card.role, Role.STANDBY)
        self.assertTrue(card.snapshot_expiring)

    def test_exactly_seven_days_does_not_warn_yet(self):
        """剩不到 7 天才警示：畫面顯示「7天0小時」時一律不警示，「6天23小時」起才警示。"""
        self.assertFalse(self.card(timedelta(days=7)).snapshot_expiring)

    def test_just_under_seven_days_warns(self):
        self.assertTrue(self.card(timedelta(days=7) - timedelta(seconds=1)).snapshot_expiring)

    def test_warning_follows_the_clock_without_file_changes(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=10))
        self.assertFalse(self.cards()["claude:work"].snapshot_expiring)
        self.clock.advance(days=4)
        self.assertTrue(self.cards()["claude:work"].snapshot_expiring)

    def test_expired_snapshot_warns(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=1))
        self.clock.advance(days=2)
        self.assertTrue(self.cards()["claude:work"].snapshot_expiring)

    def test_readding_the_same_label_clears_the_warning(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=5))
        self.manage("work", "rt-w2", "acct-w", timedelta(days=30))
        card = self.cards()["claude:work"]
        self.assertEqual((card.snapshot_expires_at, card.snapshot_expiring), (NOW + timedelta(days=30), False))

    def test_snapshot_without_expiry_time_is_left_alone(self):
        """沒有 refreshTokenExpiresAt 的憑證快照暫當無效資料：沒有到期時間，也不警示。"""
        self.log_in(refresh="rt-w", account_uuid="acct-w")
        path = self.paths.claude_dir / ".credentials.json"
        path.write_text('{"claudeAiOauth": {"refreshToken": "rt-w"}, "organizationUuid": "org-1"}', encoding="utf-8")
        self.core.add("work")
        card = self.cards()["claude:work"]
        self.assertEqual((card.snapshot_expires_at, card.snapshot_expiring), (None, False))

    def test_unmanaged_card_has_no_expiry(self):
        self.log_in(refresh="rt-x", account_uuid="acct-x")
        card = self.core.poll().cards[0]
        self.assertEqual(card.role, Role.UNMANAGED)
        self.assertEqual((card.snapshot_expires_at, card.snapshot_expiring), (None, False))


class CountdownFormatSettingTest(ExpiryTestCase):
    def test_two_units_is_the_default(self):
        self.assertIs(self.core.poll().countdown_format, CountdownFormat.TWO_UNITS)

    def test_decimal_days_from_the_settings_file_takes_effect_without_restart(self):
        self.core.poll()
        self.write_settings(countdownFormat="decimalDays")
        self.assertIs(self.core.poll().countdown_format, CountdownFormat.DECIMAL_DAYS)

    def test_unknown_value_falls_back_to_two_units(self):
        self.write_settings(countdownFormat="weeks")
        self.assertIs(self.core.poll().countdown_format, CountdownFormat.TWO_UNITS)


class ExpiryTextTest(ExpiryTestCase):
    def test_warning_carries_the_full_remedy(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=5))
        text = render(self.core.poll())
        self.assertIn("憑證快照 5天0小時後到期", text)
        self.assertIn("重新登入", text)
        self.assertIn(f"{COMMAND} add work", text)

    def test_expiry_shows_two_units_and_the_absolute_time_without_warning(self):
        expires = NOW + timedelta(days=28, minutes=33)
        self.manage("work", "rt-w", "acct-w", expires - NOW)
        text = render(self.core.poll())
        self.assertIn(f"憑證快照 28天0小時後到期（{local(expires, '%m-%d %H:%M')}）", text)
        self.assertNotIn(f"{COMMAND} add work", text)

    def test_lower_unit_is_truncated_not_rounded_up(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=6, hours=23, minutes=59))
        self.assertIn("6天23小時後到期", render(self.core.poll()))

    def test_decimal_days_shows_one_truncated_decimal(self):
        self.write_settings(countdownFormat="decimalDays")
        self.manage("work", "rt-w", "acct-w", timedelta(days=6, hours=23, minutes=50))
        self.assertIn("憑證快照 6.9天後到期", render(self.core.poll()))

    def test_expired_snapshot_says_expired_with_its_time(self):
        expires = NOW + timedelta(days=1)
        self.manage("work", "rt-w", "acct-w", expires - NOW)
        self.clock.advance(days=2)
        text = render(self.core.poll())
        self.assertIn(f"憑證快照已過期（{local(expires, '%m-%d %H:%M')}）", text)
        self.assertIn(f"{COMMAND} add work", text)


class WindowCountdownTextTest(HomeTestCase):
    def test_window_shows_hours_minutes_and_clock_time_within_a_day(self):
        resets = NOW + timedelta(hours=2, minutes=15)
        self.write_cache(resets_at=resets)
        text = render(self.core.poll())
        self.assertIn(f"工作階段窗口  10%  重置：2小時15分後（{local(resets, '%H:%M')}）", text)

    def test_under_an_hour_shows_minutes_only(self):
        self.write_cache(resets_at=NOW + timedelta(minutes=45, seconds=30))
        self.assertIn("重置：45分後（", render(self.core.poll()))

    def test_days_away_shows_days_hours_and_date(self):
        resets = NOW + timedelta(days=3, hours=4)
        self.write_cache(resets_at=resets)
        self.assertIn(f"週窗口  40%  重置：3天4小時後（{local(resets, '%m-%d %H:%M')}）", render(self.core.poll()))

    def test_decimal_days_under_a_day_switches_to_hours_minutes(self):
        self.write_settings(countdownFormat="decimalDays")
        self.write_cache(resets_at=NOW + timedelta(hours=2, minutes=15))
        self.assertIn("重置：2小時15分後（", render(self.core.poll()))

    def test_decimal_days_applies_to_windows_too(self):
        self.write_settings(countdownFormat="decimalDays")
        self.write_cache(resets_at=NOW + timedelta(days=3, hours=4))
        self.assertIn("週窗口  40%  重置：3.1天後（", render(self.core.poll()))


if __name__ == "__main__":
    unittest.main()
