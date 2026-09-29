"""縫 ②：換字型（票 23）。三種版面來回切換字型，item 數不累積；自填字型不存在時橫幅提示，內建字型不存在時不提示。"""
import tkinter as tk
import tkinter.font as tkfont
import unittest
from dataclasses import replace

from cc_quota_tracker.layout_a import LayoutA
from cc_quota_tracker.layout_b import LayoutB
from cc_quota_tracker.layout_c import LayoutC
from tests.test_layout_a import EXPANDED_BOARDS, visible_texts

MISSING = "NoSuchFontFamilyXYZ"


class LayoutFontTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # 沒有顯示環境
            self.skipTest(f"Tk 無法啟動：{e}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.canvas = tk.Canvas(self.root)

    def for_each_layout(self, check):
        for layout_class in (LayoutA, LayoutB, LayoutC):
            self.canvas.delete("all")
            with self.subTest(layout=layout_class.__name__):
                check(layout_class(self.canvas))

    def other_installed_family(self):
        default = tkfont.Font(self.root, name="TkDefaultFont", exists=True).actual("family").casefold()
        others = [f for f in sorted(tkfont.families(self.root)) if f.casefold() != default and not f.startswith("@")]
        if not others:
            self.skipTest("沒有第二個字型可換")
        return others[0]

    def shown(self):
        return "\n".join(visible_texts(self.canvas))

    def test_switching_fonts_back_and_forth_keeps_the_item_count_of_each_state(self):
        # 換字型會改變折行的行數（多行文字逐行一個 item），找不到時橫幅還多一段提示，所以不同字型的 item 數可以不同；
        # 同一個字型下，不管切換過幾輪都不能累積 item
        family = self.other_installed_family()

        def check(layout):
            for board in EXPANDED_BOARDS:
                for expanded in (False, True):
                    counts = {}
                    for custom in (None, family, MISSING, None, family, MISSING, family, None):
                        layout.set_font(custom)
                        layout.render(board, "light", expanded)
                        counts.setdefault(custom, set()).add(len(self.canvas.find_all()))
                    self.assertEqual({k: len(v) for k, v in counts.items()}, {None: 1, family: 1, MISSING: 1})

        self.for_each_layout(check)

    def test_text_items_follow_the_font_they_were_created_with(self):
        family = self.other_installed_family()

        def check(layout):
            layout.render(EXPANDED_BOARDS[0], "light", True)
            layout.set_font(family)
            layout.render(EXPANDED_BOARDS[0], "light", True)
            texts = [i for i in self.canvas.find_all() if self.canvas.type(i) == "text"
                     and self.canvas.itemcget(i, "state") != "hidden"]
            self.assertTrue(texts)
            for item in texts:
                actual = tkfont.Font(self.root, font=self.canvas.itemcget(item, "font")).actual("family")
                self.assertEqual(actual.casefold(), family.casefold())

        self.for_each_layout(check)

    def test_a_missing_custom_font_is_named_in_the_banner_and_a_missing_builtin_is_not(self):
        def check(layout):
            layout.set_font(MISSING)
            layout.render(EXPANDED_BOARDS[3], "light")
            self.assertIn(MISSING, self.shown())
            self.assertIn("font", self.shown())
            layout.set_font(None)
            layout.render(EXPANDED_BOARDS[3], "light")
            self.assertNotIn("font", self.shown())

        self.for_each_layout(check)

    def test_the_font_hint_sits_beside_the_other_banner_lines(self):
        def check(layout):
            layout.set_font(MISSING)
            layout.render(replace(EXPANDED_BOARDS[3], invalid_settings=("mode",)), "light")
            self.assertIn("mode", self.shown())
            self.assertIn(MISSING, self.shown())

        self.for_each_layout(check)


if __name__ == "__main__":
    unittest.main()
