"""縫 ①：語系。語系的解析（設定 × 系統語系）與兩份語系檔的一致性；不碰畫面。"""
import re
import string
import unittest
from pathlib import Path
from unittest import mock

from cc_quota_tracker import i18n
from cc_quota_tracker.languages import en, zh_tw

SOURCE = Path(i18n.__file__).parent


def placeholders(template):
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


class LanguageOfTest(unittest.TestCase):
    def test_traditional_chinese_tags_are_zh_tw(self):
        for tag in ("zh-TW", "zh_TW", "zh_TW.UTF-8", "zh-Hant", "zh-Hant-TW", "zh-HK", "zh-MO", "ZH-tw"):
            self.assertEqual(i18n.language_of(tag), "zh-TW", tag)

    def test_english_tags_are_en(self):
        for tag in ("en", "en-US", "en_GB", "en_US.UTF-8"):
            self.assertEqual(i18n.language_of(tag), "en", tag)

    def test_anything_else_is_not_supported(self):
        for tag in ("zh-CN", "zh-SG", "zh-Hans", "zh", "ja-JP", "fr_FR", "C", "", None):
            self.assertIsNone(i18n.language_of(tag), tag)


class ResolveTest(unittest.TestCase):
    def test_follow_system_takes_the_system_language(self):
        self.assertEqual(i18n.resolve("system", "zh-TW"), "zh-TW")
        self.assertEqual(i18n.resolve("system", "en-US"), "en")

    def test_unsupported_system_language_falls_back_to_english(self):
        for tag in ("ja-JP", "zh-CN", "", None):
            self.assertEqual(i18n.resolve("system", tag), "en", tag)

    def test_a_chosen_language_ignores_the_system(self):
        self.assertEqual(i18n.resolve("en", "zh-TW"), "en")
        self.assertEqual(i18n.resolve("zh-TW", "ja-JP"), "zh-TW")


class CatalogTest(unittest.TestCase):
    def test_both_files_have_the_same_keys(self):
        self.assertEqual(set(zh_tw.STRINGS) - set(en.STRINGS), set(), "英文缺少")
        self.assertEqual(set(en.STRINGS) - set(zh_tw.STRINGS), set(), "正體中文缺少")

    def test_both_files_take_the_same_placeholders(self):
        for key, template in zh_tw.STRINGS.items():
            self.assertEqual(placeholders(template), placeholders(en.STRINGS[key]), key)

    def test_no_text_is_empty(self):
        for catalog in (zh_tw.STRINGS, en.STRINGS):
            for key, template in catalog.items():
                self.assertTrue(template.strip(), key)

    def test_english_text_has_no_han_characters(self):
        # 英文檔漏翻最常見的樣子：整條還是中文，或中文標點混進去
        han = re.compile(r"[⺀-鿿＀-￯]")
        for key, template in en.STRINGS.items():
            self.assertIsNone(han.search(template), (key, template))

    def test_text_fills_the_placeholders_in_the_chosen_language(self):
        self.assertEqual(i18n.text("zh-TW", "age.minutes", n=5), "5 分鐘前")
        self.assertEqual(i18n.text("en", "age.minutes", n=5), "5 min ago")

    def test_menu_hint_names_the_menu_entry_it_points_to(self):
        # 提示文字叫使用者在右鍵選單選某一項：兩個語系各自的選單項名稱要對得上
        for lang in i18n.SUPPORTED:
            entry = i18n.text(lang, "menu.add").rstrip("…")
            self.assertIn(entry, i18n.text(lang, "note.how_to_manage", command="x"), lang)
            self.assertIn(entry, i18n.text(lang, "add_warning.not_bound.menu"), lang)


class SystemTagTest(unittest.TestCase):
    def test_a_failing_windows_call_means_unknown_instead_of_an_error(self):
        # 視窗每輪 poll 都會問系統語系：API 出錯不能讓那一輪跟著出錯
        windll = mock.Mock()
        windll.kernel32.GetUserDefaultUILanguage.side_effect = OSError
        with mock.patch("sys.platform", "win32"), mock.patch("ctypes.windll", windll, create=True):
            self.assertIsNone(i18n.system_tag())


class KeyUsageTest(unittest.TestCase):
    """語系鍵一律寫成字面值：這樣才查得出用到但沒定義、與定義了但沒人用的鍵。"""

    @classmethod
    def setUpClass(cls):
        cls.sources = {p.name: p.read_text(encoding="utf-8") for p in SOURCE.glob("*.py")}

    def test_every_key_used_in_code_is_defined(self):
        used = {(name, key) for name, source in self.sources.items()
                for key in re.findall(r"\btext\([^,()]+(?:\([^()]*\))?,\s*\"([^\"]+)\"", source)}
        self.assertTrue(used)
        missing = {(name, key) for name, key in used if key not in zh_tw.STRINGS}
        self.assertEqual(missing, set())

    def test_keys_kept_in_tables_and_conditionals_are_defined_too(self):
        # 表格與三元式裡的鍵不在 text() 的引數位置，上一條抓不到：把所有長得像語系鍵的字面值都對一次
        prefixes = {key.split(".")[0] for key in zh_tw.STRINGS if "." in key}
        not_keys = {"window.json"}  # 視窗位置的檔名，剛好與語系鍵同一個前綴
        keyish = re.compile(r"\"([a-z_]+(?:\.[a-z0-9_\-]+)+)\"")
        wrong = {(name, key) for name, source in self.sources.items() if "i18n import" in source
                 for key in keyish.findall(source)
                 if key.split(".")[0] in prefixes and key not in not_keys and key not in zh_tw.STRINGS}
        self.assertEqual(wrong, set())

    def test_every_defined_key_is_used_somewhere(self):
        code = "\n".join(self.sources.values())
        unused = [key for key in zh_tw.STRINGS if f'"{key}"' not in code]
        self.assertEqual(unused, [])


if __name__ == "__main__":
    unittest.main()
