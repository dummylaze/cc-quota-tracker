"""偏好（票 14）：每輪依設定檔的修改時間重讀，單一欄位不合法只那一欄用預設；GUI 合併寫入不蓋掉手改的內容。
讀取從縫 ① 的看板觀察，寫入從縫 ③ 的設定檔觀察。"""
import json
import unittest

from cc_quota_tracker.board import Preferences
from cc_quota_tracker.settings import DEFAULTS, write_preference
from tests.fakehome import HomeTestCase


class ReadPreferencesTest(HomeTestCase):
    def test_defaults_from_first_launch(self):
        board = self.core.poll()
        self.assertEqual(board.preferences, Preferences())
        self.assertEqual(board.invalid_settings, ())
        self.assertEqual(Preferences(), Preferences(layout="cards", always_on_top=True, mode="compact",
                                                    language="system", theme="system", opacity=100))

    def test_hand_edit_takes_effect_on_next_poll(self):
        self.core.poll()
        self.write_settings(layout="table", alwaysOnTop=False, mode="expanded", language="en", theme="dark", opacity=70)
        self.assertEqual(self.core.poll().preferences,
                         Preferences(layout="table", always_on_top=False, mode="expanded", language="en", theme="dark",
                                     opacity=70))

    def test_every_layout_is_a_valid_value(self):
        for layout in ("cards", "table", "ring"):
            with self.subTest(layout=layout):
                self.write_settings(layout=layout)
                board = self.core.poll()
                self.assertEqual((board.preferences.layout, board.invalid_settings), (layout, ()))

    def test_invalid_value_falls_back_for_that_field_only_and_is_named(self):
        self.write_settings(mode="huge", opacity=50, theme="dark", alwaysOnTop=1, countdownFormat="weeks", layout="rings")
        board = self.core.poll()
        self.assertEqual(board.preferences, Preferences(theme="dark"))
        self.assertEqual(board.invalid_settings, ("alwaysOnTop", "countdownFormat", "layout", "mode", "opacity"))

    def test_values_of_the_wrong_type_are_invalid(self):
        # JSON 的 true 等於 1、100.0 等於 100：只比值會放過型別不對的值
        for field, value in (("opacity", 100.0), ("opacity", True), ("alwaysOnTop", 0), ("layout", None)):
            with self.subTest(field=field, value=value):
                self.write_settings(**{field: value})
                self.assertEqual(self.core.poll().invalid_settings, (field,))

    def test_missing_field_uses_default_without_complaint(self):
        self.write_settings_text(json.dumps({"theme": "dark"}))
        board = self.core.poll()
        self.assertEqual(board.preferences, Preferences(theme="dark"))
        self.assertEqual(board.invalid_settings, ())

    def test_unreadable_file_means_all_defaults(self):
        self.write_settings(theme="dark")
        self.core.poll()
        self.write_settings_text("{broken")
        board = self.core.poll()
        self.assertTrue(board.settings_unreadable)
        self.assertEqual(board.preferences, Preferences())
        self.assertEqual(board.invalid_settings, ())


class WritePreferenceTest(HomeTestCase):
    def read_file(self):
        return json.loads(self.settings_file().read_text(encoding="utf-8"))

    def test_changes_only_that_field_and_keeps_hand_edits(self):
        # 使用者剛手改了主題與路徑之外的欄位，GUI 接著改透明度：手改的內容不能被蓋掉
        self.core.poll()
        self.write_settings(theme="dark", note="使用者自己加的欄位")
        self.assertTrue(write_preference(self.settings_file(), "opacity", 85))
        self.assertEqual(self.read_file(), dict(DEFAULTS, opacity=85, theme="dark", note="使用者自己加的欄位"))
        self.assertEqual(self.core.poll().preferences, Preferences(theme="dark", opacity=85))

    def test_unreadable_file_is_not_written(self):
        self.write_settings_text("{broken")
        self.assertFalse(write_preference(self.settings_file(), "opacity", 85))
        self.assertEqual(self.settings_file().read_text(encoding="utf-8"), "{broken")

    def test_missing_file_is_recreated_with_defaults(self):
        self.settings_file().unlink()
        self.assertTrue(write_preference(self.settings_file(), "mode", "expanded"))
        self.assertEqual(self.read_file()["mode"], "expanded")
        self.assertEqual(self.read_file()["layout"], "cards")

    def test_leaves_no_temp_file_behind(self):
        write_preference(self.settings_file(), "opacity", 70)
        self.assertEqual([p.name for p in self.settings_file().parent.iterdir()], ["settings.json"])


if __name__ == "__main__":
    unittest.main()
