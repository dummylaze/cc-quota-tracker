"""縫 ①：不經過 add 的綁定維護——直接放檔補學綁定、改檔名保留綁定、刪檔清孤兒。"""
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from cc_quota_tracker.board import ReadingState, Role
from tests.fakehome import HomeTestCase, claude_json, usage_cache

KEY_RT1 = "a33d8c625833429d"  # refreshToken "rt-1" 的憑證指紋，事先算好的字面值
KEY_RT2 = "1f23b7dadfb229cb"  # refreshToken "rt-2"


class BindingTestCase(HomeTestCase):
    def snapshot(self, label):
        return self.home / ".claude-multi" / f"{label}.json"

    def bindings(self):
        path = self.home / ".claude-multi" / ".state" / "bindings.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def drop_in(self, label):
        """把當前憑證直接複製進納管目錄，不經過 add。"""
        self.snapshot(label).parent.mkdir(exist_ok=True)
        self.snapshot(label).write_bytes((self.paths.claude_dir / ".credentials.json").read_bytes())

    def card(self, key):
        return {c.account_key: c for c in self.core.poll().cards}[key]


class LearnBindingTest(BindingTestCase):
    def test_active_snapshot_dropped_in_learns_its_binding_when_all_three_conditions_hold(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.drop_in("work")
        self.write_cache(oauth="acct-1", account_uuid="acct-1")
        card = self.card("claude:work")
        self.assertEqual((card.role, card.reading_state), (Role.ACTIVE, ReadingState.HAS_READING))
        self.assertEqual(self.bindings(), {KEY_RT1: {"accountId": "acct-1"}})

    def test_learned_binding_survives_a_restart(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.drop_in("work")
        self.write_cache(oauth="acct-1", account_uuid="acct-1")
        self.core.poll()
        self.log_in(refresh="rt-2", account_uuid="acct-2")  # 換成別的帳號，work 變待命
        self.start()
        card = self.card("claude:work")
        self.assertEqual((card.role, card.reading_state), (Role.STANDBY, ReadingState.HAS_READING))

    def test_not_learned_when_the_cache_belongs_to_another_account(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.drop_in("work")
        self.write_cache(oauth="acct-1", account_uuid="acct-other")
        card = self.card("claude:work")
        self.assertEqual(card.reading_state, ReadingState.PENDING)
        self.assertFalse((self.home / ".claude-multi" / ".state" / "bindings.json").exists())

    def test_not_learned_when_oauth_account_is_unreadable(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.drop_in("work")
        self.write_claude_json({"cachedUsageUtilization": usage_cache(account_uuid="acct-1")})
        self.assertEqual(self.card("claude:work").reading_state, ReadingState.PENDING)
        self.assertFalse((self.home / ".claude-multi" / ".state" / "bindings.json").exists())

    def test_not_learned_when_the_snapshot_is_not_the_active_account(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.drop_in("work")
        self.log_in(refresh="rt-2", account_uuid="acct-2")  # 使用中的是另一個帳號
        self.write_cache(oauth="acct-2", account_uuid="acct-2")
        board = self.core.poll()
        self.assertEqual([c.role for c in board.cards], [Role.UNMANAGED, Role.STANDBY])
        self.assertEqual(board.cards[1].reading_state, ReadingState.NO_READING)
        self.assertFalse((self.home / ".claude-multi" / ".state" / "bindings.json").exists())

    def test_not_learned_when_the_id_is_already_bound_to_another_account(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.core.add("work")
        self.write_credentials(refresh="rt-2")  # 另一份憑證，oauthAccount 仍是 acct-1
        self.drop_in("other")
        self.write_cache(oauth="acct-1", account_uuid="acct-1")
        cards = {c.account_key: c for c in self.core.poll().cards}
        self.assertEqual((cards["claude:other"].role, cards["claude:other"].reading_state),
                         (Role.ACTIVE, ReadingState.PENDING))
        self.assertEqual(self.bindings(), {KEY_RT1: {"accountId": "acct-1"}})

    def test_unreadable_bindings_file_is_not_overwritten_by_learning(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.core.add("work")
        self.log_in(refresh="rt-2", account_uuid="acct-2")
        self.drop_in("home")
        self.write_cache(oauth="acct-2", account_uuid="acct-2")
        before = (self.home / ".claude-multi" / ".state" / "bindings.json").read_bytes()
        real = Path.read_text

        def locked(path, *args, **kwargs):
            if path.name == "bindings.json":
                raise PermissionError("locked by another process")
            return real(path, *args, **kwargs)
        with mock.patch.object(Path, "read_text", locked):
            self.core.poll()
        self.assertEqual((self.home / ".claude-multi" / ".state" / "bindings.json").read_bytes(), before)
        self.assertEqual(self.card("claude:home").reading_state, ReadingState.HAS_READING)  # 下一輪補上


class RenameTest(BindingTestCase):
    def test_renaming_a_snapshot_keeps_its_binding(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.core.add("work")
        self.write_cache(oauth="acct-1", account_uuid="acct-1")
        before = self.bindings()
        os.rename(self.snapshot("work"), self.snapshot("office"))
        card = self.card("claude:office")
        self.assertEqual((card.role, card.reading_state), (Role.ACTIVE, ReadingState.HAS_READING))
        self.assertEqual(self.bindings(), before)


class OrphanCleanupTest(BindingTestCase):
    def setUp(self):
        super().setUp()
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.core.add("work")
        self.log_in(refresh="rt-2", account_uuid="acct-2")
        self.core.add("home")
        self.write_cache(oauth="acct-2", account_uuid="acct-2")
        self.core.poll()

    def readings(self):
        path = self.home / ".claude-multi" / ".state" / "readings.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_binding_of_a_deleted_snapshot_is_removed(self):
        self.snapshot("work").unlink()
        self.core.poll()
        self.assertEqual(self.bindings(), {KEY_RT2: {"accountId": "acct-2"}})

    def test_reading_of_a_deleted_snapshot_is_removed_with_its_binding(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.write_cache(oauth="acct-1", account_uuid="acct-1")
        self.core.poll()
        self.assertEqual(set(self.readings()), {"acct-1", "acct-2"})
        self.snapshot("work").unlink()
        self.core.poll()
        self.assertEqual(set(self.readings()), {"acct-2"})

    def test_no_binding_is_dropped_while_a_snapshot_cannot_be_read(self):
        self.snapshot("work").write_text('{"claudeAiOauth": {"acc', encoding="utf-8")  # 寫到一半或被防毒鎖住
        self.core.poll()
        self.assertEqual(set(self.bindings()), {KEY_RT1, KEY_RT2})


if __name__ == "__main__":
    unittest.main()
