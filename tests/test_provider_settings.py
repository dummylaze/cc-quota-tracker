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


class AutoUsageQuerySettingsTest(HomeTestCase):
    """自動查詢的兩個設定：預設值、不合法值、低於下限（不改寫設定檔），改了下一輪生效。"""

    def status(self, **fields):
        self.write_settings(providers=claude(**fields))
        return self.core.poll().usage_query

    def test_off_by_default_with_a_fifteen_minute_interval(self):
        status = self.core.poll().usage_query
        self.assertEqual((status.auto_enabled, status.auto_paused, status.interval_below_floor),
                         (False, False, False))

    def test_the_switch_is_read_from_the_settings_file_and_follows_edits(self):
        self.assertTrue(self.status(autoUsageQuery=True).auto_enabled)
        self.assertFalse(self.status(autoUsageQuery=False).auto_enabled)

    def test_a_non_boolean_switch_is_invalid_and_falls_back_to_off(self):
        for value in (1, 0, "true", None, [True]):
            with self.subTest(value=value):
                self.write_settings(providers=claude(autoUsageQuery=value))
                board = self.core.poll()
                self.assertFalse(board.usage_query.auto_enabled)
                self.assertEqual(board.invalid_settings, ("providers.claude.autoUsageQuery",))

    def test_a_non_positive_integer_interval_is_invalid_and_falls_back_to_the_default(self):
        for value in (0, -3, 7.5, "15", True, None, [15]):
            with self.subTest(value=value):
                self.write_settings(providers=claude(autoUsageQuery=True, autoUsageQueryMinutes=value))
                board = self.core.poll()
                self.assertEqual(board.invalid_settings, ("providers.claude.autoUsageQueryMinutes",))
                self.assertFalse(board.usage_query.interval_below_floor)  # 改用預設 15，不是下限

    def test_an_interval_below_the_floor_is_flagged_only_while_auto_query_is_on(self):
        for minutes in (1, 4):
            with self.subTest(minutes=minutes):
                status = self.status(autoUsageQuery=True, autoUsageQueryMinutes=minutes)
                self.assertTrue(status.interval_below_floor)
                self.assertEqual(self.core.poll().invalid_settings, ())  # 低於下限不是不合法
        self.assertFalse(self.status(autoUsageQuery=False, autoUsageQueryMinutes=1).interval_below_floor)

    def test_the_floor_itself_and_larger_intervals_are_fine(self):
        for minutes in (5, 15, 600):
            with self.subTest(minutes=minutes):
                self.assertFalse(self.status(autoUsageQuery=True, autoUsageQueryMinutes=minutes).interval_below_floor)

    def test_the_tool_never_rewrites_a_value_below_the_floor(self):
        self.write_settings(providers=claude(autoUsageQuery=True, autoUsageQueryMinutes=1))
        before = self.settings_file().read_bytes()
        self.core.poll()
        self.assertEqual(self.settings_file().read_bytes(), before)


class InvalidProviderSettingsAreNamedTest(HomeTestCase):
    """使用者故事 79：providers 底下的值不合法時，和偏好一樣被指名（路徑式名稱），只那一項用預設。"""

    def invalid(self, providers):
        self.write_settings(providers=providers)
        return self.core.poll().invalid_settings

    def test_each_invalid_field_is_named_with_its_path(self):
        for field, value in (("expiryWarningDays", 0), ("expiryWarningDays", "7"), ("expiryWarningDays", None),
                             ("warningPercent", 101), ("criticalPercent", True)):
            with self.subTest(field=field, value=value):
                self.assertEqual(self.invalid(claude(**{field: value})), (f"providers.claude.{field}",))

    def test_missing_fields_and_valid_values_are_not_reported(self):
        self.assertEqual(self.invalid(claude()), ())
        self.assertEqual(self.invalid(claude(expiryWarningDays=10, warningPercent=40, criticalPercent=50)), ())
        self.assertEqual(self.invalid({"other": {"expiryWarningDays": 0}}), ())  # 不認得的供應商：不是這個工具管的

    def test_malformed_containers_are_named_at_their_own_level(self):
        for providers, name in (("claude", "providers"), ([], "providers"), (None, "providers"),
                                ({"claude": 10}, "providers.claude"), ({"claude": None}, "providers.claude"),
                                ({"claude": []}, "providers.claude"), ({"claude": ""}, "providers.claude")):
            with self.subTest(providers=providers):
                self.assertEqual(self.invalid(providers), (name,))

    def test_inverted_thresholds_name_both_fields(self):
        self.assertEqual(self.invalid(claude(warningPercent=90, criticalPercent=80)),
                         ("providers.claude.criticalPercent", "providers.claude.warningPercent"))

    def test_thresholds_that_end_up_reversed_or_equal_name_both_even_the_one_not_written(self):
        both = ("providers.claude.criticalPercent", "providers.claude.warningPercent")
        for fields in ({"warningPercent": 0, "criticalPercent": 50},  # 0 不合法 → 預設 60，高過合法的 50
                       {"warningPercent": 90},  # critical 沒寫 → 預設 85
                       {"warningPercent": 70, "criticalPercent": 70}):
            with self.subTest(fields=fields):
                self.assertEqual(self.invalid(claude(**fields)), both)

    def test_the_root_name_matches_the_settings_file_field(self):
        from cc_quota_tracker.settings import PROVIDERS_FIELD
        self.assertEqual(self.invalid(None), (PROVIDERS_FIELD,))  # 與設定檔欄位名稱脫鉤的話，這裡會變成 ()

    def test_invalid_provider_and_preference_fields_are_listed_together_sorted(self):
        self.write_settings(mode="sideways", providers=claude(expiryWarningDays=0))
        self.assertEqual(self.core.poll().invalid_settings, ("mode", "providers.claude.expiryWarningDays"))

    def test_fixing_the_value_clears_the_report(self):
        self.assertEqual(self.invalid(claude(expiryWarningDays=0)), ("providers.claude.expiryWarningDays",))
        self.assertEqual(self.invalid(claude(expiryWarningDays=10)), ())


if __name__ == "__main__":
    unittest.main()
