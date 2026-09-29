"""設計 token：spec〈畫面層〉配色規則中可機械判定的部分。每一組「前景＋它實際畫在上面的底色」，兩套主題各量一次。"""
import unittest

from cc_quota_tracker.tokens import RADIUS, SPACE, THEMES

SEVERITIES = ("normal", "warning", "critical")

# 門檻：(WCAG 2 對比下限, APCA |Lc| 目標)。WCAG 是下限，APCA 是設計目標，兩者都要過
TEXT = (4.5, 60)  # 非內文文字：標籤、數值、附註。百分比 13pt 粗體小於大字門檻（14pt 粗體），照一般文字算
GRAPHIC = (3, 30)  # 進度條填色、色點、外框等 UI 元件
VISIBLE = (1, 15)  # 只要看得見的元素（空的進度條底軌）：WCAG 沒有要求，APCA 不低於 15

# (前景, 它實際畫在上面的底色, 門檻, 畫在哪裡)
PAIRS = [
    ("fg", "card", TEXT, "帳號標籤、提示文字、用量去向"),
    ("sub", "card", TEXT, "窗口名稱、附註、讀數年齡"),
    *((s, "card", TEXT, "百分比數值、嚴重度提示文字與色點") for s in SEVERITIES),
    *((s, "track", GRAPHIC, "進度條填色") for s in SEVERITIES),
    ("neutral", "track", GRAPHIC, "中性進度條填色：週窗口已過 %、額外用量"),
    ("track", "card", VISIBLE, "空的進度條底軌"),
    ("accent", "card", GRAPHIC, "使用中帳號的外框、未納管提示的色點"),
    ("accent", "panel", GRAPHIC, "使用中帳號的外框（外半邊落在底板上）"),
    ("chip_active_fg", "accent", TEXT, "使用中標籤文字"),
    ("chip_standby_fg", "chip_standby", TEXT, "待命標籤文字"),
    ("banner_fg", "banner", TEXT, "橫幅文字"),
    # 版面 B 使用中帳號那一列：文字與圖形實際畫在淡色底上
    ("fg", "active_row", TEXT, "使用中列的帳號標籤、提示文字"),
    ("sub", "active_row", TEXT, "使用中列的讀數年齡、附註"),
    *((s, "active_row", TEXT, "使用中列的百分比數值、嚴重度提示文字與色點") for s in SEVERITIES),
    ("accent", "active_row", GRAPHIC, "使用中列的使用中標籤、未納管提示的色點"),
]
# 使用者決定的例外（票 17）：淡色底本身對卡片、以及空底軌對淡色底，都低於「看得見」的 Lc 15。
# 淡色底要淡才不壓過內容；使用中列另有使用中標籤，不只靠底色辨認


def _channel(hex2):
    v = int(hex2, 16) / 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def luminance(color):
    """WCAG 2 的相對亮度。"""
    r, g, b = (_channel(color[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _apca_y(color):
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    y = 0.2126729 * r ** 2.4 + 0.7151522 * g ** 2.4 + 0.0721750 * b ** 2.4
    return y + (0.022 - y) ** 1.414 if y < 0.022 else y  # 近黑色的軟鉗制


def apca(text, background):
    """APCA-W3 0.0.98G 的 Lc：深字淺底為正、淺字深底為負。"""
    yt, yb = _apca_y(text), _apca_y(background)
    if abs(yb - yt) < 0.0005:
        return 0.0
    if yb > yt:
        s = (yb ** 0.56 - yt ** 0.57) * 1.14
        return 0.0 if s < 0.1 else (s - 0.027) * 100
    s = (yb ** 0.65 - yt ** 0.62) * 1.14
    return 0.0 if s > -0.1 else (s + 0.027) * 100


class ApcaTest(unittest.TestCase):
    def test_matches_reference_values(self):
        # APCA-W3 文件的參考值：黑字白底 Lc 106.04、白字黑底 Lc -107.88、#888 字白底 Lc 63.06
        self.assertAlmostEqual(apca("#000000", "#ffffff"), 106.04, places=1)
        self.assertAlmostEqual(apca("#ffffff", "#000000"), -107.88, places=1)
        self.assertAlmostEqual(apca("#888888", "#ffffff"), 63.06, places=1)


class ColorPairTest(unittest.TestCase):
    def test_every_pair_meets_the_wcag_floor_in_both_themes(self):
        for theme, c in THEMES.items():
            for fore, back, (ratio, _), where in PAIRS:
                with self.subTest(theme=theme, pair=f"{fore}/{back}", where=where):
                    self.assertGreaterEqual(contrast(c[fore], c[back]), ratio)

    def test_every_pair_meets_the_apca_target_in_both_themes(self):
        for theme, c in THEMES.items():
            for fore, back, (_, lc), where in PAIRS:
                with self.subTest(theme=theme, pair=f"{fore}/{back}", where=where):
                    self.assertGreaterEqual(abs(apca(c[fore], c[back])), lc)

    def test_both_themes_define_the_same_roles(self):
        self.assertEqual(set(THEMES["light"]), set(THEMES["dark"]))


class ColorMeaningTest(unittest.TestCase):
    def test_severity_colors_differ_from_each_other(self):
        for theme, c in THEMES.items():
            with self.subTest(theme=theme):
                self.assertEqual(len({c[s] for s in SEVERITIES}), len(SEVERITIES))

    def test_neutral_information_uses_neither_accent_nor_a_severity_color(self):
        for theme, c in THEMES.items():
            with self.subTest(theme=theme):
                self.assertNotIn(c["neutral"], {c["accent"], *(c[s] for s in SEVERITIES)})

    def test_standby_chip_has_its_own_colors(self):
        for theme, c in THEMES.items():
            with self.subTest(theme=theme):
                self.assertNotIn(c["chip_standby"], {c["track"], c["accent"]})


class RadiusTest(unittest.TestCase):
    def test_nested_corners_are_concentric(self):
        # 外層圓角＝內層圓角＋兩者之間的內距
        self.assertEqual(RADIUS["panel"], RADIUS["card"] + SPACE["panel_pad"])
        self.assertEqual(RADIUS["card"], RADIUS["row"] + SPACE["row_inset"])  # 版面 B 使用中列的底色
        self.assertEqual(RADIUS["card"], RADIUS["cell"] + SPACE["row_inset"])  # 版面 C 使用中格的外框


if __name__ == "__main__":
    unittest.main()
