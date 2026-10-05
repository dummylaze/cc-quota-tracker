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

    def test_standby_account_ignores_conversation_after_the_switch(self):
        self.read_cache()
        self.core.poll()  # 讀數歸屬給 work 後存進工具狀態
        self.log_in(refresh="rt-h", account_uuid="acct-h")
        self.core.add("home")
        self.write_claude_json(claude_json(usage_cache(account_uuid="acct-h", resets_at=FAR), "acct-h"))
        self.core.poll()  # 偵測到切換：這時 work 的讀數還沒落後
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

    def test_unwatched_active_account_can_lag(self):
        self.write_credentials(refresh="rt-new")
        self.write_claude_json(claude_json(usage_cache(account_uuid="acct-new", resets_at=FAR), "acct-new"))
        self.talk(NOW + timedelta(minutes=1))
        card = self.core.poll().cards[0]
        self.assertEqual((card.role, card.reading_state), (Role.UNWATCHED, ReadingState.HAS_READING))
        self.assertTrue(card.lagging)

    def test_list_shows_the_lagging_hint(self):
        self.read_cache()
        self.talk(NOW + timedelta(minutes=1))
        self.assertIn("有新對話，額度尚未更新", render(self.core.poll()))


class LaggingBeforeTheSwitchTest(HomeTestCase):
    """縫 ①：使用者在工具外切換帳號，切換前已落後的讀數，成為待命讀數後仍然落後。"""

    def setUp(self):
        super().setUp()
        for label, refresh, uuid in (("work", "rt-w", "acct-w"), ("home", "rt-h", "acct-h")):
            self.log_in(refresh=refresh, account_uuid=uuid)
            self.core.add(label)
        self.log_in(refresh="rt-w", account_uuid="acct-w")
        self.core.poll()  # 第一次運作，當前憑證帳號是 work

    def talk(self, at, session="s1"):
        path = self.paths.claude_dir / "projects" / "proj" / f"{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"type":"user"}\n', encoding="utf-8")
        os.utime(path, (at.timestamp(), at.timestamp()))

    def read_cache(self, owner="acct-w", fetched_at=NOW):
        """額度快取更新，工具跟著 poll 到：這份讀數歸屬給 work，也存進待命讀數。"""
        self.write_claude_json(claude_json(usage_cache(account_uuid=owner, fetched_at=fetched_at, resets_at=FAR), owner))
        self.core.poll()

    def switch_to(self, label):
        refresh, uuid = {"work": ("rt-w", "acct-w"), "home": ("rt-h", "acct-h")}[label]
        self.log_in(refresh=refresh, account_uuid=uuid)

    def work_card(self):
        card = {c.account_key: c for c in self.core.poll().cards}["claude:work"]
        self.assertEqual((card.role, card.reading_state), (Role.STANDBY, ReadingState.HAS_READING))
        return card

    def test_a_reading_that_was_lagging_stays_lagging_on_the_standby_card(self):
        self.read_cache()
        self.talk(NOW + timedelta(minutes=1))
        self.clock.advance(minutes=2)
        self.assertTrue(self.core.poll().cards[0].lagging)
        self.switch_to("home")
        self.assertTrue(self.work_card().lagging)

    def test_the_mark_stays_while_nothing_new_arrives(self):
        self.read_cache()
        self.talk(NOW + timedelta(minutes=1))
        self.switch_to("home")
        self.assertTrue(self.work_card().lagging)
        self.clock.advance(days=1)
        self.assertTrue(self.work_card().lagging)

    def test_conversation_in_the_last_minute_before_the_switch_counts(self):
        """沒落後的判定每分鐘才掃一次：切換前才有的對話，偵測到切換的那一輪要重新掃。"""
        self.read_cache()
        self.assertFalse(self.core.poll().cards[0].lagging)  # 這一輪掃過，結果是沒落後
        self.talk(NOW + timedelta(seconds=10))
        self.clock.advance(seconds=15)  # 離上次掃描不到一個掃描間隔
        self.switch_to("home")
        self.assertTrue(self.work_card().lagging)

    def test_a_reading_that_was_not_lagging_is_not_marked(self):
        self.read_cache()
        self.switch_to("home")
        self.assertFalse(self.work_card().lagging)
        self.talk(NOW + timedelta(minutes=1))  # 切換之後的對話是別的帳號的
        self.assertFalse(self.work_card().lagging)

    def test_the_mark_survives_a_restart(self):
        self.read_cache()
        self.talk(NOW + timedelta(minutes=1))
        self.switch_to("home")
        self.assertTrue(self.work_card().lagging)
        self.start()
        self.assertTrue(self.work_card().lagging)

    def test_a_new_reading_for_that_account_clears_it(self):
        self.read_cache()
        self.talk(NOW + timedelta(minutes=1))
        self.switch_to("home")
        self.assertTrue(self.work_card().lagging)
        self.switch_to("work")
        self.read_cache(fetched_at=NOW + timedelta(minutes=10))  # 查詢或 /usage 之後的新讀數
        card = self.core.poll().cards[0]
        self.assertEqual((card.role, card.lagging), (Role.ACTIVE, False))
        self.switch_to("home")
        self.assertFalse(self.work_card().lagging)

    def test_an_unreadable_readings_file_at_the_switch_is_retried_not_forgotten(self):
        """切換只偵測一次：那一輪讀數檔剛好被鎖住，標記不能就此漏掉，要等讀得到的下一輪補上。"""
        self.read_cache()
        self.talk(NOW + timedelta(minutes=1))
        self.start()  # 重新啟動後第一次讀讀數檔就被鎖住
        self.switch_to("home")
        with self.locked("readings.json"):
            self.core.poll()
        self.assertTrue(self.work_card().lagging)

    def test_the_list_says_so_without_offering_a_query_the_account_cannot_take(self):
        self.read_cache()
        self.talk(NOW + timedelta(minutes=1))
        self.switch_to("home")
        shown = render(self.core.poll())
        self.assertIn("切換前已落後", shown)
        self.assertNotIn("可以執行", shown)  # 查詢只能查當前憑證帳號，待命帳號落後時不提示

    def test_the_list_shows_the_english_text(self):
        self.read_cache()
        self.talk(NOW + timedelta(minutes=1))
        self.switch_to("home")
        self.assertIn("Lagging before the switch", render(self.core.poll(), "en"))


if __name__ == "__main__":
    unittest.main()
