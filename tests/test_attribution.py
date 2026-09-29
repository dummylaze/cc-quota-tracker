import json
import sys
import unittest
from datetime import timedelta

from cc_quota_tracker import COMMAND
from cc_quota_tracker.board import ReadingState, Role, Severity
from cc_quota_tracker.render_text import render
from tests.fakehome import NOW, HomeTestCase, WindowsAclAssertions, claude_json, usage_cache

FAR = NOW + timedelta(days=30)  # 重置時間夠遠：時鐘往後推幾天，窗口仍在計時


class AttributionTestCase(HomeTestCase):
    def manage(self, label, refresh, account_uuid):
        """在 Claude Code 登入某帳號並納管它；納管後它就是使用中帳號。"""
        self.log_in(refresh=refresh, account_uuid=account_uuid)
        self.core.add(label)

    def switch_to(self, refresh, oauth, cache_owner, **cache):
        """切換：當前憑證與 oauthAccount 換成新帳號，額度快取還是 cache_owner 的。"""
        self.write_credentials(refresh=refresh)
        self.write_claude_json(claude_json(usage_cache(account_uuid=cache_owner, resets_at=FAR, **cache), oauth))

    def cards(self):
        return {card.account_key: card for card in self.core.poll().cards}

    def readings_file(self):
        return self.home / ".claude-multi" / ".state" / "readings.json"


class ActiveAccountTest(AttributionTestCase):
    def test_fingerprint_matching_a_snapshot_makes_it_the_active_account(self):
        self.manage("work", "rt-w", "acct-w")
        self.manage("home", "rt-h", "acct-h")
        self.switch_to("rt-w", oauth="acct-w", cache_owner="acct-w")
        board = self.core.poll()
        self.assertEqual([(c.account_key, c.role) for c in board.cards],
                         [("claude:work", Role.ACTIVE), ("claude:home", Role.STANDBY)])

    def test_fingerprint_matching_no_snapshot_is_an_unmanaged_account(self):
        self.manage("work", "rt-w", "acct-w")
        self.switch_to("rt-x", oauth="acct-x", cache_owner="acct-x")
        board = self.core.poll()
        self.assertEqual([(c.account_key, c.role) for c in board.cards],
                         [(None, Role.UNMANAGED), ("claude:work", Role.STANDBY)])

    def test_without_current_credential_the_active_account_is_unmanaged(self):
        self.assertEqual([c.role for c in self.core.poll().cards], [Role.UNMANAGED])


class AttributionTest(AttributionTestCase):
    def test_reading_belongs_to_the_account_bound_to_its_id(self):
        self.manage("work", "rt-w", "acct-w")
        self.switch_to("rt-w", oauth="acct-w", cache_owner="acct-w", session=33)
        card = self.cards()["claude:work"]
        self.assertEqual(card.reading_state, ReadingState.HAS_READING)
        self.assertEqual(card.limits[0].percent, 33)

    def test_first_round_after_switch_is_pending_and_old_reading_stays_with_old_account(self):
        self.manage("work", "rt-w", "acct-w")
        self.manage("home", "rt-h", "acct-h")
        self.switch_to("rt-w", oauth="acct-w", cache_owner="acct-w", session=33)
        self.core.poll()
        self.switch_to("rt-h", oauth="acct-h", cache_owner="acct-w", session=34)  # 快取還是 work 的
        cards = self.cards()
        self.assertEqual(cards["claude:home"].role, Role.ACTIVE)
        self.assertEqual(cards["claude:home"].reading_state, ReadingState.PENDING)
        self.assertEqual(cards["claude:home"].limits, ())
        self.assertEqual(cards["claude:work"].role, Role.STANDBY)
        self.assertEqual(cards["claude:work"].limits[0].percent, 34)

    def test_pending_ends_once_the_cache_id_matches(self):
        self.manage("work", "rt-w", "acct-w")
        self.manage("home", "rt-h", "acct-h")
        self.switch_to("rt-h", oauth="acct-h", cache_owner="acct-w")
        self.core.poll()
        self.switch_to("rt-h", oauth="acct-h", cache_owner="acct-h", session=5)
        card = self.cards()["claude:home"]
        self.assertEqual(card.reading_state, ReadingState.HAS_READING)
        self.assertEqual(card.limits[0].percent, 5)

    def test_active_account_without_binding_stays_pending(self):
        self.write_credentials(refresh="rt-w")  # ~/.claude.json 不存在：納管了，但沒有綁定
        self.core.add("work")
        self.switch_to("rt-w", oauth="acct-w", cache_owner="acct-other")  # 快取不是它的：不補學
        self.assertEqual(self.cards()["claude:work"].reading_state, ReadingState.PENDING)

    def test_active_account_without_usage_cache_has_no_reading(self):
        self.manage("work", "rt-w", "acct-w")
        self.assertEqual(self.cards()["claude:work"].reading_state, ReadingState.NO_READING)

    def test_unmanaged_account_gets_the_reading_of_the_logged_in_id(self):
        self.switch_to("rt-x", oauth="acct-x", cache_owner="acct-x", session=21)
        card = self.core.poll().cards[0]
        self.assertEqual((card.role, card.reading_state), (Role.UNMANAGED, ReadingState.HAS_READING))
        self.assertEqual(card.limits[0].percent, 21)

    def test_unmanaged_account_is_pending_while_cache_holds_another_account(self):
        self.manage("work", "rt-w", "acct-w")
        self.switch_to("rt-x", oauth="acct-x", cache_owner="acct-w")
        cards = self.cards()
        self.assertEqual(cards[None].reading_state, ReadingState.PENDING)
        self.assertEqual(cards["claude:work"].reading_state, ReadingState.HAS_READING)


class StandbyTest(AttributionTestCase):
    def setUp(self):
        super().setUp()
        self.manage("work", "rt-w", "acct-w")
        self.manage("home", "rt-h", "acct-h")
        self.switch_to("rt-w", oauth="acct-w", cache_owner="acct-w", session=70)
        self.core.poll()
        self.switch_to("rt-h", oauth="acct-h", cache_owner="acct-h", session=5)

    def test_standby_shows_last_observed_reading_with_its_age(self):
        self.clock.advance(days=3)
        card = self.cards()["claude:work"]
        self.assertEqual(card.reading_state, ReadingState.HAS_READING)
        self.assertEqual(card.limits[0].percent, 70)
        self.assertEqual(card.reading_age, timedelta(days=3))

    def test_old_standby_reading_is_not_flagged(self):
        self.clock.advance(days=3)
        card = self.cards()["claude:work"]
        self.assertEqual({lim.severity for lim in card.limits}, {Severity.NORMAL})

    def test_standby_reading_survives_restart(self):
        self.core.poll()
        self.start()
        self.assertEqual(self.cards()["claude:work"].limits[0].percent, 70)

    def test_standby_never_seen_has_no_reading(self):
        self.manage("spare", "rt-s", "acct-s")
        self.switch_to("rt-h", oauth="acct-h", cache_owner="acct-h")
        self.assertEqual(self.cards()["claude:spare"].reading_state, ReadingState.NO_READING)

    def test_active_reading_age_is_on_the_board(self):
        self.clock.advance(minutes=7)
        self.assertEqual(self.cards()["claude:home"].reading_age, timedelta(minutes=7))

    def test_removed_account_reading_is_dropped_from_tool_state(self):
        self.core.poll()
        self.core.remove("work")
        stored = json.loads(self.readings_file().read_text(encoding="utf-8"))
        self.assertEqual(set(stored), {"acct-h"})


@unittest.skipUnless(sys.platform == "win32", "Windows ACL")
class ReadingsPermissionTest(AttributionTestCase, WindowsAclAssertions):
    def test_readings_file_is_private(self):
        self.manage("work", "rt-w", "acct-w")
        self.switch_to("rt-w", oauth="acct-w", cache_owner="acct-w")
        self.core.poll()
        self.assert_private(self.readings_file())


class RenderTest(AttributionTestCase):
    def test_pending_explains_when_reading_appears(self):
        self.manage("work", "rt-w", "acct-w")
        self.switch_to("rt-w", oauth="acct-w", cache_owner="acct-other")
        text = render(self.core.poll())
        self.assertIn("讀數待更新", text)
        self.assertIn("Claude Code 更新額度快取後就會出現", text)

    def test_unmanaged_card_shows_how_to_manage(self):
        self.switch_to("rt-x", oauth="acct-x", cache_owner="acct-x")
        self.assertIn(f"{COMMAND} add", render(self.core.poll()))

    def test_standby_card_shows_relative_age_and_observation_caveat(self):
        self.manage("work", "rt-w", "acct-w")
        self.manage("home", "rt-h", "acct-h")
        self.switch_to("rt-h", oauth="acct-h", cache_owner="acct-w")
        self.core.poll()
        self.clock.advance(days=3)
        text = render(self.core.poll())
        self.assertIn("3 天前", text)
        self.assertIn("觀測值", text)


if __name__ == "__main__":
    unittest.main()
