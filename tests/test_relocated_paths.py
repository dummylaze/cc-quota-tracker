"""縫 ①：核心在解析出的路徑上讀寫（ADR-0008），以及路徑相關的看板提示。"""
import json
import os
import sys
import unittest

from cc_quota_tracker.core import AddWarning
from cc_quota_tracker.settings import DEFAULTS
from tests.fakehome import HomeTestCase, WindowsAclAssertions, usage_cache

KEY_RT1 = "a33d8c625833429d"  # refreshToken "rt-1" 的憑證指紋，事先算好的字面值


class RelocatedDirectoriesTest(WindowsAclAssertions, HomeTestCase):
    def setUp(self):
        super().setUp()
        self.claude_dir = self.make_dir("claude-config")
        self.managed = self.make_dir("other-disk/managed")
        self.write_settings(managedDir=str(self.managed))
        self.start(CLAUDE_CONFIG_DIR=str(self.claude_dir))

    def test_add_and_poll_use_the_resolved_directories(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.core.add("work")
        self.assertTrue((self.managed / "work.json").is_file())
        self.assertFalse((self.home / ".claude-multi").exists())
        bindings = json.loads((self.managed / ".state" / "bindings.json").read_text(encoding="utf-8"))
        self.assertEqual(bindings, {KEY_RT1: {"accountUuid": "acct-1"}})
        (self.claude_dir / ".claude.json").write_text(
            json.dumps({"cachedUsageUtilization": usage_cache(weekly=61)}), encoding="utf-8")
        weekly = [lim for lim in self.core.poll().cards[0].limits if lim.kind == "weekly_all"]
        self.assertEqual(weekly[0].percent, 61)

    @unittest.skipUnless(sys.platform == "win32", "Windows ACL")
    def test_permissions_are_tightened_in_the_moved_managed_dir(self):
        # 架設者自己建的目錄靠繼承取得權限：add 照樣收緊並告警（ADR-0007）
        self.log_in()
        result = self.core.add("work")
        state = self.managed / ".state"
        for path in (self.managed, self.managed / "work.json", state, state / "bindings.json"):
            self.assert_private(path)
        self.assertIn(AddWarning.PERMISSIONS_FIXED, result.warnings)

    def test_nothing_under_the_claude_code_dir_is_written(self):
        self.log_in()
        (self.claude_dir / "settings.json").write_text("{}", encoding="utf-8")

        def state():
            return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.claude_dir.rglob("*") if p.is_file()}
        before = state()
        self.core.poll()
        self.core.add("work")
        self.core.poll()
        self.core.remove("work")
        self.core.poll()
        self.assertEqual(state(), before)


class WrongLocationHintTest(HomeTestCase):
    """三層都沒指定、home 預設也沒有額度快取：可能讀錯位置，不能只當成尚無讀數。"""

    def test_no_usage_cache_at_home_default_is_suspicious(self):
        board = self.core.poll()
        self.assertTrue(board.wrong_location_suspected)
        self.assertEqual(board.cards[0].reading_state.value, "no_reading")

    def test_usage_cache_file_without_reading_is_not_suspicious(self):
        self.log_in()  # .claude.json 存在，只是還沒有 cachedUsageUtilization
        self.assertFalse(self.core.poll().wrong_location_suspected)

    def test_explicit_location_is_trusted(self):
        by_env, by_settings = self.make_dir("by-env"), self.make_dir("by-settings")
        self.start(CLAUDE_CONFIG_DIR=str(by_env))
        self.assertFalse(self.core.poll().wrong_location_suspected)
        self.write_settings(claudeConfigDir=str(by_settings))
        self.start()
        self.assertFalse(self.core.poll().wrong_location_suspected)


class RestartHintTest(HomeTestCase):
    """路徑只在啟動時解析；執行中改了路徑欄位，看板提示需重新啟動，改前的路徑繼續用。"""

    def test_changing_a_path_field_asks_for_restart_and_keeps_old_paths(self):
        self.log_in()
        self.assertFalse(self.core.poll().restart_required)
        for field in ("managedDir", "claudeConfigDir"):
            with self.subTest(field=field):
                self.write_settings(**{field: str(self.make_dir(f"new-{field}"))})
                self.assertTrue(self.core.poll().restart_required)
                self.assertTrue(self.core.poll().restart_required)
                self.write_settings()  # 改回來就不必重新啟動
                self.assertFalse(self.core.poll().restart_required)
        self.write_settings(managedDir=str(self.home / "new-managedDir"))
        self.core.add("work")
        self.assertTrue((self.home / ".claude-multi" / "work.json").is_file())

    def test_unreadable_settings_file_is_flagged_until_fixed(self):
        self.write_settings_text("{")
        self.start()
        self.assertTrue(self.core.poll().settings_unreadable)
        self.write_settings()
        board = self.core.poll()
        self.assertFalse(board.settings_unreadable)
        self.assertFalse(board.restart_required)  # 修好後路徑欄位仍是 null，與啟動時當成沒填的結果相同
        self.write_settings_text("not json")
        board = self.core.poll()
        self.assertTrue(board.settings_unreadable)
        self.assertFalse(board.restart_required)

    def test_fix_landing_in_the_same_time_tick_is_still_picked_up(self):
        # 讀到寫到一半的設定檔：修改時間不能記下，否則寫完落在同一個時間刻度時永遠卡在無法讀取
        path = self.settings_file()
        mtime = path.stat().st_mtime_ns + 1_000_000_000
        path.write_text("{", encoding="utf-8")
        os.utime(path, ns=(mtime, mtime))
        self.assertTrue(self.core.poll().settings_unreadable)
        path.write_text(json.dumps(DEFAULTS), encoding="utf-8")
        os.utime(path, ns=(mtime, mtime))
        self.assertFalse(self.core.poll().settings_unreadable)

    def test_changing_only_a_preference_needs_no_restart(self):
        self.write_settings(theme="dark", opacity=70)
        self.assertFalse(self.core.poll().restart_required)


if __name__ == "__main__":
    unittest.main()
