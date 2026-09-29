"""字型（票 23）：自填字型套用到所有文字、字級字重仍取自 token；字型不存在時一律改用 TkDefaultFont 的家族。
解析是純函式，另外用真的 Tk 確認字型物件被改的是屬性、數量不變。"""
import tkinter as tk
import tkinter.font as tkfont
import unittest

from cc_quota_tracker.fonts import FontSet, resolve_families
from cc_quota_tracker.tokens import FONTS

INSTALLED = {"microsoft jhenghei ui", "segoe ui semibold", "consolas", "segoe ui"}
DEFAULT = "Segoe UI"


class ResolveFamiliesTest(unittest.TestCase):
    def test_null_uses_the_token_families(self):
        families, missing = resolve_families(None, INSTALLED, DEFAULT)
        self.assertEqual(families, {name: family for name, (family, _, _) in FONTS.items()})
        self.assertIsNone(missing)

    def test_a_custom_family_replaces_every_role(self):
        families, missing = resolve_families("Consolas", INSTALLED, DEFAULT)
        self.assertEqual(set(families.values()), {"Consolas"})
        self.assertEqual(set(families), set(FONTS))
        self.assertIsNone(missing)

    def test_family_names_match_regardless_of_case(self):
        families, missing = resolve_families("CONSOLAS", INSTALLED, DEFAULT)
        self.assertEqual((set(families.values()), missing), ({"CONSOLAS"}, None))

    def test_a_missing_custom_family_falls_back_to_the_default_for_every_role_and_is_reported(self):
        for custom in ("NoSuchFont", ""):
            with self.subTest(custom=custom):
                families, missing = resolve_families(custom, INSTALLED, DEFAULT)
                self.assertEqual((set(families.values()), missing), ({DEFAULT}, custom))

    def test_a_missing_builtin_family_falls_back_per_role_without_a_report(self):
        families, missing = resolve_families(None, INSTALLED - {"microsoft jhenghei ui"}, DEFAULT)
        self.assertEqual({families[name] for name in ("title", "chip", "body", "small")}, {DEFAULT})
        self.assertEqual(families["percent"], "Segoe UI Semibold")
        self.assertIsNone(missing)


class FontSetTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # 沒有顯示環境
            self.skipTest(f"Tk 無法啟動：{e}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.canvas = tk.Canvas(self.root)
        self.default = tkfont.Font(self.root, name="TkDefaultFont", exists=True).actual("family")
        self.fonts = FontSet(self.canvas)

    def other_installed_family(self):
        others = [f for f in sorted(tkfont.families(self.root)) if f.casefold() != self.default.casefold()
                  and not f.startswith("@")]
        if not others:
            self.skipTest("沒有第二個字型可換")
        return others[0]

    def test_starts_on_the_token_fonts(self):
        for name, (family, size, weight) in FONTS.items():
            self.assertEqual((self.fonts[name].cget("size"), self.fonts[name].cget("weight")), (size, weight))

    def test_custom_family_changes_only_the_family(self):
        family = self.other_installed_family()
        self.fonts.configure(family)
        for name, (_, size, weight) in FONTS.items():
            font = self.fonts[name]
            self.assertEqual((font.cget("family"), font.cget("size"), font.cget("weight")), (family, size, weight))
        self.assertIsNone(self.fonts.missing)

    def test_missing_family_becomes_the_system_default_not_what_tk_would_pick(self):
        self.fonts.configure("NoSuchFontFamilyXYZ")
        for name in FONTS:
            self.assertEqual(self.fonts[name].cget("family"), self.default)
        self.assertEqual(self.fonts.missing, "NoSuchFontFamilyXYZ")

    def test_switching_back_to_null_restores_the_token_families_and_clears_the_report(self):
        self.fonts.configure("NoSuchFontFamilyXYZ")
        self.fonts.configure(None)
        self.assertIsNone(self.fonts.missing)
        self.assertEqual(self.fonts["title"].cget("family"), FONTS["title"][0])

    def test_switching_families_reconfigures_the_same_font_objects(self):
        before = {name: self.fonts[name] for name in FONTS}
        self.fonts.configure(self.other_installed_family())
        self.fonts.configure("NoSuchFontFamilyXYZ")
        self.fonts.configure(None)
        self.assertTrue(all(self.fonts[name] is before[name] for name in FONTS))


if __name__ == "__main__":
    unittest.main()
