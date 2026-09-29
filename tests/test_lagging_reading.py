import os
import unittest
from datetime import timedelta

from cc_quota_tracker.board import ReadingState, Role
from cc_quota_tracker.core import LAG_SCAN_INTERVAL
from cc_quota_tracker.render_text import render
from tests.fakehome import NOW, HomeTestCase, claude_json, usage_cache

FAR = NOW + timedelta(days=30)


class LaggingReadingTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.log_in(refresh="rt-w", account_uuid="acct-w")
        self.core.add("work")

    def talk(self, at, project="proj", session="s1"):
        """Claude Code 在某個專案的對話紀錄寫了一筆；修改時間由測試指定。"""
        path = self.paths.claude_dir / "projects" / project / f"{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"type":"user"}\n', encoding="utf-8")
        os.utime(path, (at.timestamp(), at.timestamp()))

    def read_cache(self, owner="acct-w", fetched_at=NOW):
        self.write_claude_json(claude_json(usage_cache(account_uuid=owner, fetched_at=fetched_at,
                                                       resets_at=FAR), "acct-w"))

    def active_card(self):
        card = self.core.poll().cards[0]
        self.assertEqual((card.role, card.reading_state), (Role.ACTIVE, ReadingState.HAS_READING))
        return card

    def test_idle_old_reading_is_not_lagging(self):
        self.talk(NOW - timedelta(minutes=5))
        self.read_cache()
        self.clock.advance(days=2)
        card = self.active_card()
        self.assertEqual(card.reading_age, timedelta(days=2))
        self.assertFalse(card.lagging)

    def test_conversation_after_the_reading_makes_it_lagging(self):
        self.read_cache()
        self.talk(NOW + timedelta(minutes=1))
        self.clock.advance(minutes=2)
        self.assertTrue(self.active_card().lagging)

    def test_any_project_counts(self):
        self.talk(NOW - timedelta(hours=1), project="a")
        self.talk(NOW + timedelta(seconds=1), project="b", session="s9")
        self.read_cache()
        self.assertTrue(self.active_card().lagging)

    def test_no_transcripts_at_all_is_not_lagging(self):
        self.read_cache()
        self.assertFalse(self.active_card().lagging)

    def test_new_reading_clears_lagging(self):
        self.read_cache()
        self.talk(NOW + timedelta(minutes=1))
        self.assertTrue(self.active_card().lagging)
        self.read_cache(fetched_at=NOW + timedelta(minutes=2))
        self.assertFalse(self.active_card().lagging)

    def test_standby_account_is_never_lagging(self):
        self.read_cache()
        self.core.poll()  # 讀數歸屬給 work 後存進工具狀態
        self.log_in(refresh="rt-h", account_uuid="acct-h")
        self.core.add("home")
        self.write_claude_json(claude_json(usage_cache(account_uuid="acct-h", resets_at=FAR), "acct-h"))
        self.talk(NOW + timedelta(minutes=1))
        cards = {c.account_key: c for c in self.core.poll().cards}
        self.assertEqual(cards["claude:work"].role, Role.STANDBY)
        self.assertEqual(cards["claude:work"].reading_state, ReadingState.HAS_READING)
        self.assertFalse(cards["claude:work"].lagging)

    def test_scans_less_often_than_poll(self):
        """沒落後時，掃描間隔內的新對話要等下一次掃描才看得到；過了間隔一定看得到。"""
        self.read_cache()
        self.assertFalse(self.active_card().lagging)
        self.talk(NOW + timedelta(seconds=1))
        self.clock.advance(seconds=1)
        self.assertFalse(self.active_card().lagging)
        self.clock.advance(seconds=LAG_SCAN_INTERVAL.total_seconds())
        self.assertTrue(self.active_card().lagging)

    def test_clock_going_back_does_not_freeze_the_scan(self):
        self.read_cache()
        self.clock.advance(minutes=5)
        self.assertFalse(self.active_card().lagging)
        self.talk(NOW + timedelta(seconds=1))
        self.clock.advance(minutes=-2)
        self.assertTrue(self.active_card().lagging)

    def test_unmanaged_active_account_can_lag(self):
        self.write_credentials(refresh="rt-new")
        self.write_claude_json(claude_json(usage_cache(account_uuid="acct-new", resets_at=FAR), "acct-new"))
        self.talk(NOW + timedelta(minutes=1))
        card = self.core.poll().cards[0]
        self.assertEqual((card.role, card.reading_state), (Role.UNMANAGED, ReadingState.HAS_READING))
        self.assertTrue(card.lagging)

    def test_list_shows_the_lagging_hint(self):
        self.read_cache()
        self.talk(NOW + timedelta(minutes=1))
        self.assertIn("有新對話，額度尚未更新", render(self.core.poll()))


if __name__ == "__main__":
    unittest.main()
