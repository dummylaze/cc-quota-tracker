"""報表頁面的大數字換單位（萬、億／K、M、B）。換算寫在頁面的腳本裡，這裡抽出那一段交給 Node 跑；沒有 Node 就略過。

畫面本身不寫自動化測試（spec〈測試決策〉），但這段是有邊界的算術：進位後剛好湊滿下一個單位、小數位數的取捨，
錯了不會報錯，只會讓表格上的數字悄悄不對。"""
import json
import re
import shutil
import subprocess
import unittest

from cc_quota_tracker import i18n, report_page

NODE = shutil.which("node")


def compact_all(language, numbers, trim=False):
    """用頁面的 makeCompact，把 numbers 逐一換成顯示的字串。單位清單取自語系檔。"""
    html = report_page.render({}, language)
    code = re.search(r"/\* compact:start \*/(.*?)/\* compact:end \*/", html, re.S).group(1)
    spec = i18n.text(language, "report.units")
    script = ("const {code, spec, language, numbers, trim} = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
              "const compact = new Function(code + '; return makeCompact;')()(spec, language, trim);"
              "console.log(JSON.stringify(numbers.map(compact)));")
    run = subprocess.run([NODE, "-e", script], input=json.dumps(dict(code=code, spec=spec, language=language,
                                                                     numbers=numbers, trim=trim)),
                         capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
    return json.loads(run.stdout)


@unittest.skipUnless(NODE, "沒有 Node，略過頁面腳本的數字換算")
class CompactNumberTest(unittest.TestCase):
    def check(self, language, cases, trim=False):
        shown = compact_all(language, [n for n, _ in cases], trim)
        self.assertEqual(shown, [expected for _, expected in cases])

    def test_chinese_switches_to_wan_at_10_thousand_and_to_yi_at_100_million(self):
        self.check("zh-TW", [(0, "0"), (9876, "9,876"), (9999, "9,999"), (10000, "1.00 萬"), (12345, "1.23 萬"),
                             (123456, "12.3 萬"), (1234567, "123 萬"), (12345678, "1,235 萬"),
                             (99999999, "1.00 億"), (100000000, "1.00 億"), (123456789, "1.23 億"),
                             (12345678901, "123 億"), (1234567890123, "12,346 億")])

    def test_english_switches_at_each_power_of_a_thousand(self):
        self.check("en", [(0, "0"), (999, "999"), (1000, "1.00K"), (9876, "9.88K"), (98765, "98.8K"), (987654, "988K"),
                          (1000000, "1.00M"), (1234567, "1.23M"), (123456789, "123M"), (1234567890, "1.23B"),
                          (123456789012, "123B")])

    def test_a_number_that_rounds_up_to_the_next_unit_is_shown_in_that_unit(self):
        self.check("en", [(999499, "999K"), (999500, "1.00M"), (999999, "1.00M"), (999999999, "1.00B")])
        self.check("zh-TW", [(99996, "10.0 萬"), (999600, "100 萬"), (99994999, "9,999 萬"), (99995000, "1.00 億")])

    def test_three_significant_digits_never_show_a_decimal_once_they_reach_100(self):
        self.check("en", [(99960, "100K"), (99940, "99.9K"), (9996, "10.0K"), (9994, "9.99K")])

    def test_axis_ticks_drop_the_trailing_zeros_but_keep_the_unit_and_grouping(self):
        self.check("zh-TW", [(0, "0"), (50000000, "5,000 萬"), (100000000, "1 億"), (20000, "2 萬")], trim=True)
        self.check("en", [(500, "500"), (50000000, "50M"), (100000000, "100M"), (1500000, "1.5M"), (2000, "2K")],
                   trim=True)


if __name__ == "__main__":
    unittest.main()
