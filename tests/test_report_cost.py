"""縫：命令列 `report --no-open`，跑在假 home 上，用測試專用的假單價表。金額在產生報表時算，不寫進任何紀錄；
單價表沒有的模型、或紀錄裡出現單價表無法計價的計費因素時，那部分金額是未知（ADR-0013）。"""
import json
from datetime import timedelta
from pathlib import Path

from cc_quota_tracker import prices
from tests.fakehome import NOW
from tests.test_token_report import PRICES as RATES
from tests.test_token_report import ReportTestCase, assistant

OLD = NOW - timedelta(hours=26)  # 過了 24 小時以上：入帳
RECENT = NOW - timedelta(hours=1)
M = 1_000_000


def billed(message_id, at, model="claude-test-1", web_search=0, **usage_fields):
    """帶計費欄位的回應紀錄；usage_fields 覆寫 service_tier、speed、inference_geo 等欄位，值是 None 時拿掉那個欄位。"""
    counts = {k: usage_fields.pop(k) for k in ("input", "output", "write_5m", "write_1h", "read") if k in usage_fields}
    record = assistant(message_id, "r-" + message_id, at, model=model, **counts)
    usage = record["message"]["usage"]
    usage.update({"speed": "standard", "inference_geo": "global",
                  "server_tool_use": {"web_search_requests": web_search, "web_fetch_requests": 0}})
    for key, value in usage_fields.items():
        if value is None:
            usage.pop(key, None)
        else:
            usage[key] = value
    return record


class CostTestCase(ReportTestCase):
    """假單價表由 ReportTestCase 放好：claude-test-1 的單價是 RATES。"""

    def setUp(self):
        super().setUp()
        self.switch(NOW - timedelta(days=30), "acct-1")

    def total(self, data, name="all"):
        return data["summary"][name]["total"]


class CostTest(CostTestCase):
    def test_every_kind_of_token_is_priced_at_its_own_rate(self):
        self.write_transcript("p/s1.jsonl", billed("m1", RECENT, input=M, output=M, write_5m=M, write_1h=M, read=M))
        data, err = self.report()
        self.assertAlmostEqual(self.total(data)["cost"], 1 + 2 + 3 + 4 + 0.5)
        self.assertEqual(self.total(data)["costUnknown"], [])
        self.assertAlmostEqual(data["summary"]["all"]["accounts"][0]["cost"], 10.5)
        self.assertAlmostEqual(data["rows"][0]["cost"], 10.5)
        self.assertEqual(err, "")

    def test_the_report_shows_the_price_table_version(self):
        self.write_prices({"claude-test-1": RATES}, version="2025-11-30")
        data, _ = self.report()
        self.assertEqual(data["prices"], {"version": "2025-11-30"})

    def test_a_model_id_with_a_date_suffix_uses_the_entry_without_it(self):
        self.write_transcript("p/s1.jsonl", billed("m1", RECENT, model="claude-test-1-20251001", input=M, output=0))
        data, _ = self.report()
        self.assertAlmostEqual(self.total(data)["cost"], 1)

    def test_the_cost_follows_the_price_table_at_report_time_even_for_ledgered_usage(self):
        self.write_transcript("p/s1.jsonl", billed("m1", OLD, input=M, output=0))
        self.assertAlmostEqual(self.total(self.report()[0])["cost"], 1)
        self.write_prices({"claude-test-1": dict(RATES, input=7)})
        self.assertAlmostEqual(self.total(self.report()[0])["cost"], 7)

    def test_no_cost_is_written_into_the_ledger(self):
        self.write_transcript("p/s1.jsonl", billed("m1", OLD, input=M))
        self.report()
        ledger = (self.paths.managed_dir / ".state" / "usage-ledger.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("cost", ledger.lower())
        self.assertTrue(ledger.strip())

    def test_a_ledger_written_before_billing_factors_were_recorded_is_still_priced(self):
        self.write_transcript("p/s1.jsonl", billed("m1", OLD, input=M, output=0))
        self.report()
        ledger = self.paths.managed_dir / ".state" / "usage-ledger.jsonl"
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        self.assertFalse(any("factors" in row for row in rows))  # 沒有因素的格子不寫這個欄位：跟舊帳本同一個形狀
        for path in (self.paths.claude_dir / "projects").rglob("*.jsonl"):
            path.unlink()
        self.assertAlmostEqual(self.total(self.report()[0])["cost"], 1)


class UnknownCostTest(CostTestCase):
    def test_a_model_missing_from_the_price_table_still_counts_tokens_but_its_cost_is_unknown(self):
        self.write_transcript("p/s1.jsonl", billed("m1", RECENT, input=M, output=0),
                              billed("m2", RECENT, model="claude-new-1", input=5, output=6))
        data, err = self.report()
        self.assertEqual(self.totals(data)["a1"][:2], (M + 5, 6))
        new = next(r for r in data["rows"] if r["model"] == "claude-new-1")
        self.assertIsNone(new["cost"])
        self.assertEqual(len(new["costUnknown"]), 1)
        self.assertIn("claude-new-1", new["costUnknown"][0])
        total = self.total(data)
        self.assertAlmostEqual(total["cost"], 1)  # 合計只含算得出的部分
        self.assertEqual(total["costUnknown"], new["costUnknown"])
        notice = next(n for n in data["notices"] if n["kind"] == "costUnknown")
        self.assertIn("claude-new-1", notice["reason"])
        self.assertIn("claude-new-1", err)

    def test_when_nothing_can_be_priced_the_cost_is_null_not_zero(self):
        self.write_transcript("p/s1.jsonl", billed("m1", RECENT, model="claude-new-1"))
        data, _ = self.report()
        self.assertIsNone(self.total(data)["cost"])
        self.assertIsNone(data["summary"]["all"]["accounts"][0]["cost"])

    def test_billing_factors_the_price_table_cannot_price_make_that_part_unknown(self):
        cases = {"fast": dict(speed="fast"), "batch": dict(service_tier="batch"), "US-only": dict(inference_geo="us"),
                 "web search": dict(web_search=2)}
        for word, fields in cases.items():
            with self.subTest(word=word):
                self.write_transcript("p/s1.jsonl", billed("m1", RECENT, input=M, output=0),
                                      billed("m2", RECENT, input=M, output=0, **fields))
                data, err = self.report()
                total = self.total(data)
                self.assertAlmostEqual(total["cost"], 1)
                self.assertEqual(len(total["costUnknown"]), 1)
                self.assertIn(word, total["costUnknown"][0])
                self.assertIn(word, err)

    def test_standard_values_and_missing_fields_are_priced_normally(self):
        self.write_transcript("p/s1.jsonl",
                              billed("m1", RECENT, input=M, output=0, inference_geo="not_available"),
                              billed("m2", RECENT, input=M, output=0, speed=None, inference_geo=None,
                                     service_tier=None, server_tool_use=None))
        data, err = self.report()
        self.assertAlmostEqual(self.total(data)["cost"], 2)
        self.assertEqual(self.total(data)["costUnknown"], [])
        self.assertFalse(any(n["kind"] == "costUnknown" for n in data["notices"]))

    def test_a_billing_factor_survives_in_the_ledger_after_the_transcripts_are_deleted(self):
        self.write_transcript("p/s1.jsonl", billed("m1", OLD, input=M, output=0),
                              billed("m2", OLD, input=M, output=0, speed="fast"))
        self.report()
        for path in (self.paths.claude_dir / "projects").rglob("*.jsonl"):
            path.unlink()
        data, _ = self.report()
        self.assertAlmostEqual(self.total(data)["cost"], 1)
        self.assertIn("fast", self.total(data)["costUnknown"][0])

    def test_a_prompt_over_the_long_prompt_threshold_is_unknown_when_the_table_prices_it_separately(self):
        self.write_prices({"claude-test-1": dict(RATES, longPromptOver=100)})
        # prompt 長度＝input＋cache 寫入＋cache 讀取
        self.write_transcript("p/s1.jsonl", billed("m1", RECENT, input=40, write_5m=30, read=30, output=0),
                              billed("m2", RECENT, input=40, write_1h=30, read=31, output=0))
        data, _ = self.report()
        total = self.total(data)
        self.assertAlmostEqual(total["cost"], (40 * 1 + 30 * 3 + 30 * 0.5) / M)
        self.assertEqual(len(total["costUnknown"]), 1)
        self.assertIn("100", total["costUnknown"][0])

    def test_a_long_prompt_ledgered_before_the_table_knew_the_model_is_unknown_once_the_table_has_a_threshold(self):
        # 入帳時單價表還沒有這個模型，分不出哪幾則是長 prompt；之後的單價表補上門檻，不能照標準單價算
        self.write_transcript("p/s1.jsonl", billed("m1", OLD, model="claude-later-1", input=150, output=0),
                              billed("m2", OLD - timedelta(hours=1), model="claude-later-1", input=50, output=0))
        self.report()
        for path in (self.paths.claude_dir / "projects").rglob("*.jsonl"):
            path.unlink()
        self.write_prices({"claude-later-1": dict(RATES, longPromptOver=100)})
        total = self.total(self.report()[0])
        self.assertAlmostEqual(total["cost"], 50 / M)  # prompt 都沒超過門檻的那一小時照算
        self.assertEqual(len(total["costUnknown"]), 1)
        self.assertIn("100", total["costUnknown"][0])

    def test_billing_fields_of_an_unexpected_type_make_the_cost_unknown_without_breaking_the_report(self):
        self.write_transcript("p/s1.jsonl", billed("m1", RECENT, input=M, output=0, speed=["fast"]),
                              billed("m2", RECENT, input=M, output=0, service_tier={"x": 1}))
        data, _ = self.report()
        self.assertIsNone(self.total(data)["cost"])
        self.assertEqual(len(self.total(data)["costUnknown"]), 2)

    def test_a_hand_edited_ledger_factor_does_not_break_the_report(self):
        self.write_transcript("p/s1.jsonl", billed("m1", OLD, input=M, output=0))
        self.report()
        ledger = self.paths.managed_dir / ".state" / "usage-ledger.jsonl"
        ledger.write_text(ledger.read_text(encoding="utf-8").replace('"model"', '"factors": ["longPrompt:\\u00b2"], "model"'),
                          encoding="utf-8")
        for path in (self.paths.claude_dir / "projects").rglob("*.jsonl"):
            path.unlink()
        data, _ = self.report()
        self.assertIsNone(self.total(data)["cost"])

    def test_an_unreadable_price_table_leaves_every_cost_unknown_and_says_so(self):
        self.price_file.write_text("{not json", encoding="utf-8")
        self.write_transcript("p/s1.jsonl", billed("m1", RECENT, input=M))
        code, out, err = self.run_report("--no-open")
        self.assertEqual(code, 0, err)
        data = self.read_data(out.strip())
        self.assertEqual(data["prices"], {"version": None})
        self.assertIsNone(self.total(data)["cost"])
        self.assertEqual(len(self.total(data)["costUnknown"]), 1)
        self.assertTrue(any(n["kind"] == "costUnknown" for n in data["notices"]))

    def test_the_unknown_parts_are_listed_once_each_in_order_of_appearance(self):
        self.write_transcript("p/s1.jsonl", billed("m1", RECENT, model="claude-new-1"),
                              billed("m2", RECENT, model="claude-new-1"),
                              billed("m3", RECENT, speed="fast"))
        data, _ = self.report()
        reasons = self.total(data)["costUnknown"]
        self.assertEqual(len(reasons), 2)
        self.assertIn("claude-new-1", reasons[0])
        self.assertIn("fast", reasons[1])

    def test_the_page_texts_follow_the_language(self):
        self.write_transcript("p/s1.jsonl", billed("m1", RECENT, model="claude-new-1"))
        data, _ = self.report(system_language="en-US")
        self.assertIn("price table", self.total(data)["costUnknown"][0])


class ShippedPriceTableTest(CostTestCase):
    """隨版本發佈的單價表本身：讀得懂、記有版本日期、每個模型五種單價齊全。"""

    def test_the_shipped_price_table_loads_with_a_version_and_full_rates(self):
        table = prices.load(Path(prices.__file__).with_name("prices.json"))
        self.assertTrue(table.readable)
        self.assertRegex(table.version, r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn("claude-opus-5-5", table.models)
        self.assertEqual(table.models["claude-opus-5-5"].rates, (4, 20, 5, 8, 0.2))
        self.assertEqual(table.models["claude-haiku-5-5"].long_prompt_over, 100_000)
