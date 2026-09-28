import unittest
from datetime import timedelta

from cc_quota_tracker.board import Severity
from cc_quota_tracker.render_text import render
from tests.fakehome import MISSING, NOW, HomeTestCase, claude_json, limit, limit_field, usage_cache

SOON = NOW + timedelta(hours=1)


def by_kind(limits):
    return {lim.kind: lim for lim in limits}


class OpenWindowTest(HomeTestCase):
    def test_future_reset_shows_percent_even_when_not_headline(self):
        # 實測：計時中的工作階段窗口 is_active 也可能是 false，它只代表「頭條列」
        card = self.poll_card(limits=[limit("session", 63, SOON, is_active=False),
                                      limit("weekly_all", 83, is_active=True)])
        session, weekly = by_kind(card.limits)["session"], by_kind(card.limits)["weekly_all"]
        self.assertEqual((session.percent, session.resets_at, session.headline), (63, SOON, False))
        self.assertTrue(weekly.headline)

    def test_null_reset_is_no_open_window(self):
        card = self.poll_card(limits=[limit("session", 0, resets_at=None)])
        session = card.limits[0]
        self.assertIsNone(session.percent)
        self.assertIsNone(session.resets_at)

    def test_past_reset_is_no_open_window_without_new_reading(self):
        self.poll_card(limits=[limit("session", 70, SOON)])
        self.clock.advance(hours=2)
        session = self.core.poll().cards[0].limits[0]
        self.assertIsNone(session.percent)
        self.assertIsNone(session.resets_at)
        self.assertEqual(session.severity, Severity.NORMAL)

    def test_weekly_window_past_reset_is_marked_reset(self):
        # 週窗口固定 7 天：舊的一週結束時新的一週已開始，只是用量與下次重置時間未知
        self.poll_card(limits=[limit("session", 70, SOON), limit("weekly_all", 83, SOON)])
        self.clock.advance(hours=2)
        limits = by_kind(self.core.poll().cards[0].limits)
        self.assertEqual((limits["weekly_all"].percent, limits["weekly_all"].resets_at, limits["weekly_all"].reset),
                         (None, None, True))
        self.assertFalse(limits["session"].reset)

    def test_weekly_window_without_reset_time_is_not_marked_reset(self):
        weekly = self.poll_card(limits=[limit("weekly_all", 0, resets_at=None)]).limits[0]
        self.assertIsNone(weekly.percent)
        self.assertFalse(weekly.reset)

    def test_reset_exactly_now_is_no_open_window(self):
        self.poll_card(limits=[limit("session", 70, SOON)])
        self.clock.advance(hours=1)
        self.assertIsNone(self.core.poll().cards[0].limits[0].percent)


class SeverityTest(HomeTestCase):
    def severity_of(self, percent, severity):
        return self.poll_card(limits=[limit("session", percent, severity=severity)]).limits[0].severity

    def test_provider_severity_wins_over_percent(self):
        self.assertEqual(self.severity_of(10, "critical"), Severity.CRITICAL)
        self.assertEqual(self.severity_of(95, "normal"), Severity.NORMAL)
        self.assertEqual(self.severity_of(83, "warning"), Severity.WARNING)

    def test_unknown_severity_is_normal(self):
        self.assertEqual(self.severity_of(95, "purple"), Severity.NORMAL)

    def test_missing_severity_falls_back_to_thresholds(self):
        expected = {0: Severity.NORMAL, 59: Severity.NORMAL, 60: Severity.WARNING,
                    84: Severity.WARNING, 85: Severity.CRITICAL, 100: Severity.CRITICAL}
        for percent, severity in expected.items():
            with self.subTest(percent=percent):
                self.assertEqual(self.severity_of(percent, MISSING), severity)

    def test_null_severity_falls_back_to_thresholds(self):
        self.assertEqual(self.severity_of(90, None), Severity.CRITICAL)


class LockedReasonTest(HomeTestCase):
    def test_locked_reason_is_carried(self):
        card = self.poll_card(five_hour=limit_field(100, SOON, locked_reason="session_limit_reached"),
                              seven_day=limit_field(40, SOON))
        self.assertEqual(card.locked_reason, "session_limit_reached")

    def test_no_lock_is_none(self):
        card = self.poll_card(five_hour=limit_field(10, SOON), seven_day=limit_field(40, SOON))
        self.assertIsNone(card.locked_reason)


class OtherLimitsTest(HomeTestCase):
    def test_unknown_kind_goes_to_other_limits_with_raw_name(self):
        card = self.poll_card(limits=[limit("session", 10), limit("weekly_all", 40),
                                      limit("lunar_meter", 20, severity="warning")])
        self.assertEqual(set(by_kind(card.limits)), {"session", "weekly_all"})
        other = by_kind(card.other_limits)["lunar_meter"]
        self.assertEqual((other.percent, other.severity), (20, Severity.WARNING))

    def test_unknown_limit_shaped_field_goes_to_other_limits(self):
        card = self.poll_card(nimbus_quill=limit_field(72, SOON))
        other = by_kind(card.other_limits)["nimbus_quill"]
        self.assertEqual((other.percent, other.resets_at, other.severity), (72, SOON, Severity.WARNING))

    def test_null_known_and_non_limit_fields_are_not_other_limits(self):
        card = self.poll_card(five_hour=limit_field(10, SOON), seven_day=limit_field(40, SOON),
                              cinder_cove=None, member_dashboard_available=True,
                              extra_usage={"is_enabled": False, "utilization": None},
                              spend={"enabled": False, "percent": 0},
                              seven_day_breakdown={"as_of": NOW.isoformat(), "rows": []})
        self.assertEqual(card.other_limits, ())


class ScopedLimitsTest(HomeTestCase):
    def test_weekly_scoped_limit_carries_scope_name(self):
        scope = {"model": {"display_name": "Opus"}}
        card = self.poll_card(limits=[limit("session", 10), limit("weekly_scoped", 55, scope=scope)])
        self.assertEqual(set(by_kind(card.limits)), {"session"})
        scoped = card.scoped_limits[0]
        self.assertEqual((scoped.kind, scoped.scope, scoped.percent), ("weekly_scoped", "Opus", 55))

    def test_no_scoped_limits_when_plan_has_none(self):
        card = self.poll_card(seven_day_opus=None, seven_day_sonnet=None)
        self.assertEqual(card.scoped_limits, ())

    def test_model_weekly_fields_are_scoped_limits_when_limits_have_none(self):
        card = self.poll_card(seven_day_sonnet=limit_field(30, SOON))
        self.assertEqual([(s.kind, s.percent) for s in card.scoped_limits], [("seven_day_sonnet", 30)])
        self.assertEqual(card.other_limits, ())

    def test_model_weekly_fields_are_not_duplicated_beside_weekly_scoped(self):
        card = self.poll_card(limits=[limit("weekly_scoped", 30)], seven_day_sonnet=limit_field(30, SOON))
        self.assertEqual([s.kind for s in card.scoped_limits], ["weekly_scoped"])


class ExpandedExtrasTest(HomeTestCase):
    def test_disabled_extras_are_absent(self):
        card = self.poll_card(extra_usage={"is_enabled": False, "monthly_limit": None, "used_credits": None,
                                           "utilization": None, "currency": None, "decimal_places": None},
                              spend={"used": {"amount_minor": 0, "currency": "USD", "exponent": 2},
                                     "limit": None, "percent": 0, "severity": "normal", "enabled": False},
                              five_hour=limit_field(10, SOON))
        self.assertIsNone(card.extra_usage)
        self.assertIsNone(card.spend)
        self.assertIsNone(by_kind(card.limits)["session"].dollars)

    def test_enabled_extra_usage(self):
        card = self.poll_card(extra_usage={"is_enabled": True, "monthly_limit": 5000, "used_credits": 1250,
                                           "utilization": 25, "currency": "USD", "decimal_places": 2})
        extra = card.extra_usage
        self.assertEqual((extra.used.minor, extra.limit.minor, extra.used.currency, extra.used.exponent),
                         (1250, 5000, "USD", 2))
        self.assertEqual(extra.percent, 25)

    def test_enabled_spend(self):
        card = self.poll_card(spend={"used": {"amount_minor": 1999, "currency": "USD", "exponent": 2},
                                     "limit": {"amount_minor": 10000, "currency": "USD", "exponent": 2},
                                     "percent": 20, "severity": "warning", "enabled": True})
        spend = card.spend
        self.assertEqual((spend.used.minor, spend.limit.minor, spend.percent, spend.severity),
                         (1999, 10000, 20, Severity.WARNING))

    def test_dollar_amounts_attach_to_their_limit(self):
        card = self.poll_card(five_hour=limit_field(10, SOON, dollars=(50.0, 5.0, 45.0)))
        dollars = by_kind(card.limits)["session"].dollars
        self.assertEqual((dollars.limit, dollars.used, dollars.remaining), (50.0, 5.0, 45.0))

    def test_weekly_breakdown_with_window_bounds(self):
        week_end = NOW + timedelta(days=4)
        card = self.poll_card(limits=[limit("weekly_all", 40, week_end)],
                              seven_day_breakdown={"as_of": NOW.isoformat(),
                                                   "window_started_at": (week_end - timedelta(days=7)).isoformat(),
                                                   "rows": [{"key": "claude_code", "display_name": "Claude Code",
                                                             "percent": 80},
                                                            {"key": "chat", "display_name": "Chats", "percent": 20}]})
        breakdown = card.weekly_breakdown
        self.assertEqual((breakdown.started_at, breakdown.ends_at), (week_end - timedelta(days=7), week_end))
        self.assertEqual([(r.key, r.label, r.percent) for r in breakdown.rows],
                         [("claude_code", "Claude Code", 80), ("chat", "Chats", 20)])

    def test_breakdown_is_dropped_once_weekly_window_resets(self):
        self.poll_card(limits=[limit("weekly_all", 40, SOON)],
                       seven_day_breakdown={"as_of": NOW.isoformat(), "window_started_at": NOW.isoformat(),
                                            "rows": [{"key": "claude_code", "display_name": "Claude Code",
                                                      "percent": 100}]})
        self.clock.advance(hours=2)
        self.assertIsNone(self.core.poll().cards[0].weekly_breakdown)

    def test_no_breakdown_is_absent(self):
        self.assertIsNone(self.poll_card(seven_day_breakdown=None).weekly_breakdown)


class RenderTest(HomeTestCase):
    def test_render_limit_semantics(self):
        self.write_claude_json(claude_json(usage_cache(
            limits=[limit("session", 0, resets_at=None), limit("weekly_all", 83, severity="warning")],
            five_hour=limit_field(100, None, locked_reason="session_limit_reached"),
            nimbus_quill=limit_field(12, SOON))))
        text = render(self.core.poll())
        self.assertIn("工作階段窗口  無計時中窗口  重置：未知", text)
        self.assertIn("週窗口  83%", text)
        self.assertIn("nimbus_quill  12%", text)
        self.assertIn("session_limit_reached", text)

    def test_render_weekly_reset(self):
        self.poll_card(limits=[limit("weekly_all", 83, SOON)])
        self.clock.advance(hours=2)
        self.assertIn("週窗口  已重置，下次重置時間未知", render(self.core.poll()))


if __name__ == "__main__":
    unittest.main()
