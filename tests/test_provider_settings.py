import unittest
from datetime import timedelta

from cc_quota_tracker.board import Severity
from tests.fakehome import MISSING, HomeTestCase, limit
from tests.test_credential_expiry import ExpiryTestCase


def claude(**fields):
    """設定檔裡按供應商分開的欄位：providers.claude。"""
    return {"claude": fields}


class ExpiryWarningSettingTest(ExpiryTestCase):
    def expiring(self, days_left):
        return self.card(timedelta(days=days_left) - timedelta(seconds=1)).snapshot_expiring

    def test_configured_days_move_the_threshold(self):
        self.write_settings(providers=claude(expiryWarningDays=10))
        self.assertTrue(self.expiring(10))

    def test_default_is_seven_days(self):
        self.assertFalse(self.expiring(8))
        self.assertTrue(self.expiring(7))

    def test_change_takes_effect_on_the_next_round(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=9))
        self.assertFalse(self.cards()["claude:work"].snapshot_expiring)
        self.write_settings(providers=claude(expiryWarningDays=10))
        self.assertTrue(self.cards()["claude:work"].snapshot_expiring)

    def test_invalid_values_fall_back_to_the_provider_default(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=9))
        for value in (0, -1, 3.5, "10", True, None, [10]):
            with self.subTest(value=value):
                self.write_settings(providers=claude(expiryWarningDays=value))
                self.assertFalse(self.cards()["claude:work"].snapshot_expiring)

    def test_malformed_providers_fall_back_to_the_provider_default(self):
        self.manage("work", "rt-w", "acct-w", timedelta(days=9))
        for providers in ("claude", [], {"claude": 10}, {"other": {"expiryWarningDays": 10}}):
            with self.subTest(providers=providers):
                self.write_settings(providers=providers)
                self.assertFalse(self.cards()["claude:work"].snapshot_expiring)


class PercentThresholdSettingTest(HomeTestCase):
    def severity_of(self, percent, severity=MISSING):
        return self.poll_card(limits=[limit("session", percent, severity=severity)]).limits[0].severity

    def test_configured_thresholds_replace_60_and_85(self):
        self.write_settings(providers=claude(warningPercent=40, criticalPercent=50))
        expected = {39: Severity.NORMAL, 40: Severity.WARNING, 49: Severity.WARNING, 50: Severity.CRITICAL}
        for percent, severity in expected.items():
            with self.subTest(percent=percent):
                self.assertEqual(self.severity_of(percent), severity)

    def test_provider_severity_still_wins(self):
        self.write_settings(providers=claude(warningPercent=40, criticalPercent=50))
        self.assertEqual(self.severity_of(95, "normal"), Severity.NORMAL)

    def test_change_takes_effect_without_a_new_reading(self):
        self.assertEqual(self.severity_of(50), Severity.NORMAL)
        self.write_settings(providers=claude(warningPercent=40, criticalPercent=50))
        self.assertEqual(self.core.poll().cards[0].limits[0].severity, Severity.CRITICAL)

    def test_spend_without_severity_uses_the_same_thresholds(self):
        self.write_settings(providers=claude(warningPercent=40, criticalPercent=50))
        card = self.poll_card(spend={"used": {"amount_minor": 50, "currency": "USD", "exponent": 2},
                                     "limit": {"amount_minor": 100, "currency": "USD", "exponent": 2},
                                     "percent": 50, "enabled": True})
        self.assertEqual(card.spend.severity, Severity.CRITICAL)

    def test_invalid_percent_falls_back_to_the_provider_default(self):
        for value in (0, 101, "40", 40.5, True):
            with self.subTest(value=value):
                self.write_settings(providers=claude(warningPercent=value))
                self.assertEqual(self.severity_of(59), Severity.NORMAL)
                self.assertEqual(self.severity_of(60), Severity.WARNING)

    def test_warning_not_below_critical_falls_back_to_both_defaults(self):
        self.write_settings(providers=claude(warningPercent=90, criticalPercent=80))
        self.assertEqual(self.severity_of(60), Severity.WARNING)
        self.assertEqual(self.severity_of(85), Severity.CRITICAL)


if __name__ == "__main__":
    unittest.main()
