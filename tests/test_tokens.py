"""設計 token：嚴重度配色在淺色與深色主題下都要清楚可辨。"""
import unittest

from cc_quota_tracker.tokens import THEMES

SEVERITIES = ("normal", "warning", "critical")


def luminance(color):
    """WCAG 的相對亮度。"""
    def channel(hex2):
        v = int(hex2, 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(color[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class SeverityColorTest(unittest.TestCase):
    def test_severity_colors_stand_out_from_what_they_are_drawn_on_in_both_themes(self):
        # 進度條填色畫在底軌上、百分比與色點畫在卡片上；WCAG 2.1 SC 1.4.11 要求圖形元件對相鄰顏色 3:1
        for theme, c in THEMES.items():
            for severity in SEVERITIES:
                for background in ("card", "track"):
                    with self.subTest(theme=theme, severity=severity, background=background):
                        self.assertGreaterEqual(contrast(c[severity], c[background]), 3)

    def test_severity_colors_differ_from_each_other(self):
        for theme, c in THEMES.items():
            with self.subTest(theme=theme):
                self.assertEqual(len({c[s] for s in SEVERITIES}), len(SEVERITIES))


if __name__ == "__main__":
    unittest.main()
