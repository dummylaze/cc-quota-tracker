"""縫 ③：路徑解析（ADR-0008）。啟動時由 resolve_paths 解析一次，命令列與 GUI 共用。"""
import json
import unittest

from cc_quota_tracker.settings import InvalidPathSetting, PathProblem, PathSource, resolve_paths
from tests.fakehome import HomeTestCase


class SettingsFileTest(HomeTestCase):
    def test_first_launch_writes_complete_settings_file(self):
        self.settings_file().unlink()  # 測試骨架建立核心時已經啟動過一次
        resolve_paths(self.home, self.env)
        self.assertEqual(json.loads(self.settings_file().read_text(encoding="utf-8")), {
            "layout": "cards", "alwaysOnTop": True, "mode": "compact",
            "language": "system", "theme": "system", "opacity": 100, "countdownFormat": "twoUnits",
            "providers": {"claude": {"expiryWarningDays": 7, "warningPercent": 60, "criticalPercent": 85}},
            "claudeConfigDir": None, "managedDir": None,
        })

    def test_existing_settings_file_is_not_overwritten(self):
        self.settings_file().write_text('{"theme": "dark"}', encoding="utf-8")
        resolve_paths(self.home, self.env)
        self.assertEqual(self.settings_file().read_text(encoding="utf-8"), '{"theme": "dark"}')

    def test_settings_file_lives_under_appdata(self):
        self.assertEqual(resolve_paths(self.home, self.env).settings_file, self.settings_file())
        without_appdata = resolve_paths(self.home, {})
        self.assertEqual(without_appdata.settings_file,
                         self.home / "AppData" / "Roaming" / "cc-quota-tracker" / "settings.json")

    def test_readable_settings_file_is_not_flagged(self):
        self.assertFalse(resolve_paths(self.home, self.env).settings_unreadable)

    def test_file_that_is_not_a_json_object_counts_as_no_path_fields_and_is_kept(self):
        from_env = self.make_dir("from-env")
        for broken in ('{"claudeConfigDir": "C:/x", ', "[]", ""):
            with self.subTest(content=broken):
                self.settings_file().write_text(broken, encoding="utf-8")
                paths = resolve_paths(self.home, dict(self.env, CLAUDE_CONFIG_DIR=str(from_env)))
                self.assertTrue(paths.settings_unreadable)
                self.assertEqual((paths.claude_dir, paths.claude_source), (from_env, PathSource.ENV))
                self.assertEqual(paths.managed_source, PathSource.DEFAULT)
                self.assertEqual(self.settings_file().read_text(encoding="utf-8"), broken)


class ClaudeDirTest(HomeTestCase):
    def test_defaults_to_home(self):
        paths = resolve_paths(self.home, self.env)
        self.assertEqual((paths.claude_json, paths.claude_dir, paths.claude_source),
                         (self.home / ".claude.json", self.home / ".claude", PathSource.DEFAULT))

    def test_empty_claude_config_dir_counts_as_unset(self):
        paths = resolve_paths(self.home, dict(self.env, CLAUDE_CONFIG_DIR=""))
        self.assertEqual((paths.claude_dir, paths.claude_source), (self.home / ".claude", PathSource.DEFAULT))

    def test_claude_config_dir_moves_both_usage_cache_and_credentials_into_it(self):
        # 實測：設了 CLAUDE_CONFIG_DIR 之後，.claude.json 寫在該目錄「裡面」，不是它的上一層
        moved = self.make_dir("elsewhere")
        paths = resolve_paths(self.home, dict(self.env, CLAUDE_CONFIG_DIR=str(moved)))
        self.assertEqual((paths.claude_json, paths.claude_dir, paths.claude_source),
                         (moved / ".claude.json", moved, PathSource.ENV))

    def test_settings_field_wins_over_env_and_means_the_same_thing(self):
        # 開機自動啟動拿不到只設在 shell 裡的 CLAUDE_CONFIG_DIR，所以設定檔欄位排第一
        configured, from_env = self.make_dir("configured"), self.make_dir("from-env")
        self.write_settings(claudeConfigDir=str(configured))
        paths = resolve_paths(self.home, dict(self.env, CLAUDE_CONFIG_DIR=str(from_env)))
        self.assertEqual((paths.claude_json, paths.claude_dir, paths.claude_source),
                         (configured / ".claude.json", configured, PathSource.SETTINGS_FILE))

    def test_null_or_missing_field_falls_through_to_next_layer(self):
        from_env = self.make_dir("from-env")
        for fields in ({"claudeConfigDir": None}, {}):
            with self.subTest(fields=fields):
                self.settings_file().write_text(json.dumps(fields), encoding="utf-8")
                paths = resolve_paths(self.home, dict(self.env, CLAUDE_CONFIG_DIR=str(from_env)))
                self.assertEqual((paths.claude_dir, paths.claude_source), (from_env, PathSource.ENV))


class ManagedDirTest(HomeTestCase):
    def test_defaults_to_home(self):
        paths = resolve_paths(self.home, self.env)
        self.assertEqual((paths.managed_dir, paths.managed_source),
                         (self.home / ".claude-multi", PathSource.DEFAULT))

    def test_settings_field_moves_it(self):
        other_disk = self.make_dir("other-disk")
        self.write_settings(managedDir=str(other_disk))
        paths = resolve_paths(self.home, self.env)
        self.assertEqual((paths.managed_dir, paths.managed_source), (other_disk, PathSource.SETTINGS_FILE))


class InvalidPathFieldTest(HomeTestCase):
    """有填但不能用：直接報錯、指出欄位，不回退——回退會讀到另一組帳號，畫面還看起來一切正常。"""

    def assert_rejected(self, field, value, problem, env=None):
        self.write_settings(**{field: value})
        with self.assertRaises(InvalidPathSetting) as caught:
            resolve_paths(self.home, dict(self.env, **(env or {})))
        self.assertEqual((caught.exception.field, caught.exception.problem), (field, problem))

    def test_directory_that_does_not_exist(self):
        # 環境變數與 home 預設都能用，仍然不回退
        from_env = self.make_dir("from-env")
        self.log_in()
        missing = str(self.home / "unplugged-drive")
        self.assert_rejected("claudeConfigDir", missing, PathProblem.NOT_A_DIRECTORY,
                             env={"CLAUDE_CONFIG_DIR": str(from_env)})
        self.assert_rejected("managedDir", missing, PathProblem.NOT_A_DIRECTORY)

    def test_managed_dir_inside_claude_code_dir(self):
        # 本工具永不寫入 Claude Code 目錄底下的任何檔案
        claude_dir = self.make_dir("claude-config")
        (claude_dir / "sub").mkdir()
        (self.home / ".claude").mkdir()
        cases = [(str(claude_dir), {"CLAUDE_CONFIG_DIR": str(claude_dir)}),
                 (str(claude_dir / "sub"), {"CLAUDE_CONFIG_DIR": str(claude_dir)}),
                 (str(self.home / ".claude"), {})]
        for managed, env in cases:
            with self.subTest(managed=managed):
                self.assert_rejected("managedDir", managed, PathProblem.INSIDE_CLAUDE_DIR, env=env)

    def test_value_that_is_not_an_absolute_path(self):
        # 相對路徑跟著工作目錄走，開機自動啟動時的工作目錄不同，會靜默讀到別處；空字串則等於工作目錄
        self.make_dir("relative")
        for field in ("claudeConfigDir", "managedDir"):
            for value in ("relative", "", 5, True, ["C:/"]):
                with self.subTest(field=field, value=value):
                    self.assert_rejected(field, value, PathProblem.NOT_ABSOLUTE)


if __name__ == "__main__":
    unittest.main()
