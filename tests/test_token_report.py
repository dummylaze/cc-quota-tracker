"""縫：命令列 `report --no-open`，跑在假 home 上。放進假的對話紀錄與切換紀錄，執行後讀出 HTML 內嵌的報表資料比對。
假對話紀錄照實測的欄位形狀造（同一則回應寫成多行、子代理的紀錄、不認得的結構），只放結構，不放任何真實內容。"""
import io
import json
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

from cc_quota_tracker import prices
from cc_quota_tracker.__main__ import main
from cc_quota_tracker.managed_directory import ManagedDirectory
from tests.fakehome import NOW, HomeTestCase, WindowsAclAssertions

UTC = timezone.utc
T0 = datetime(2025, 12, 31, 8, 0, tzinfo=UTC)
# 假單價表的單價（每百萬 token 的美元）：input、output、cache 寫入 5 分鐘、1 小時、cache 讀取
PRICES = {"input": 1, "output": 2, "cacheWrite5m": 3, "cacheWrite1h": 4, "cacheRead": 0.5}
R = NOW - timedelta(hours=10)  # 最近 24 小時之內：還沒入帳，每次產生報表都重算，晚到的紀錄不會被帳本的進度擋掉
LATE = ' '  # 字串內容裡的 U+2028：str.splitlines 會把含它的一行切成兩半


def stamp(at):
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}Z"


def assistant(message_id, request_id, at, model="claude-test-1", input=1, output=2, write_5m=0, write_1h=0, read=0,
              **extra):
    """一行帶用量的回應紀錄，欄位照實測的形狀；用量以外的欄位只放結構。"""
    usage = {"input_tokens": input, "output_tokens": output, "cache_read_input_tokens": read,
             "cache_creation_input_tokens": write_5m + write_1h,
             "cache_creation": {"ephemeral_5m_input_tokens": write_5m, "ephemeral_1h_input_tokens": write_1h},
             "service_tier": "standard"}
    record = {"type": "assistant", "uuid": "u-" + message_id, "timestamp": stamp(at), "requestId": request_id,
              "isSidechain": False, "message": {"id": message_id, "model": model, "role": "assistant",
                                                "stop_reason": "end_turn", "usage": usage}}
    record.update(extra)
    return record


class ReportTestCase(HomeTestCase):
    def setUp(self):
        super().setUp()
        zone = mock.patch("cc_quota_tracker.token_report.local_zone", return_value=UTC)  # 不隨執行的機器改變
        zone.start()
        self.addCleanup(zone.stop)
        # 測試專用的假單價表：不隨正式單價表的改版改變
        self.price_file = self.home / "prices.json"
        self.write_prices({"claude-test-1": PRICES})
        price_file = mock.patch.object(prices, "PRICE_FILE", self.price_file)
        price_file.start()
        self.addCleanup(price_file.stop)

    def write_prices(self, models, version="2025-12-01"):
        self.price_file.write_text(json.dumps({"version": version, "source": "https://example.invalid/pricing",
                                               "currency": "USD", "unit": "per million tokens", "models": models}),
                                   encoding="utf-8")

    def write_transcript(self, relative, *lines):
        """lines 的每一項：dict 寫成一行 JSON，字串原樣寫成一行。檔尾一律有換行。"""
        path = self.paths.claude_dir / "projects" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join((json.dumps(line) if isinstance(line, dict) else line) + "\n" for line in lines),
                        encoding="utf-8")
        return path

    def managed(self):
        return ManagedDirectory(self.paths.managed_dir)

    def switch(self, at, account_id, last_run_at=None):
        self.managed().append_switch(at, account_id, last_run_at)

    def run_report(self, *args, system_language="zh-TW", now=NOW):
        out, err = io.StringIO(), io.StringIO()
        with self.cli_environment(system_language), redirect_stdout(out), redirect_stderr(err), \
                mock.patch("cc_quota_tracker.__main__.datetime") as clock:
            clock.now.side_effect = lambda tz: now
            code = main(["report", *args])
        return code, out.getvalue(), err.getvalue()

    def report(self, **kw):
        """產生報表並讀回內嵌的報表資料。"""
        code, out, err = self.run_report("--no-open", **kw)
        self.assertEqual(code, 0, err)
        return self.read_data(out.strip()), err

    @staticmethod
    def read_html(path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def read_data(self, path):
        return self.read_block(path, "report-data")

    def read_texts(self, path):
        """頁面文字（依語系）：腳本只取這一份的字串。"""
        return self.read_block(path, "report-texts")

    def read_block(self, path, block):
        html = self.read_html(path)
        return json.loads(re.search(rf'<script type="application/json" id="{block}">(.*?)</script>', html,
                                    re.S).group(1))

    def totals(self, data, name="all"):
        """區間的各帳號合計：帳號鍵 → (input, output, cache 寫入 5 分鐘, 1 小時, cache 讀取)。"""
        return {row["account"]: (row["input"], row["output"], row["cacheWrite5m"], row["cacheWrite1h"],
                                 row["cacheRead"]) for row in data["summary"][name]["accounts"]}


class DedupeAndFieldsTest(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.switch(T0 - timedelta(days=1), "acct-1")

    def test_one_response_written_as_several_lines_is_counted_once_with_the_last_output(self):
        # 實測：同一則回應的各行 input 與 cache 一致，output 持平或上升，最後一行最大
        self.write_transcript("p/s1.jsonl",
                              assistant("m1", "r1", T0, output=10, input=5, read=7),
                              assistant("m1", "r1", T0 + timedelta(seconds=1), output=10, input=5, read=7),
                              assistant("m1", "r1", T0 + timedelta(seconds=2), output=40, input=5, read=7))
        data, _ = self.report()
        self.assertEqual(self.totals(data), {"a1": (5, 40, 0, 0, 7)})

    def test_a_smaller_output_on_a_later_line_does_not_replace_the_larger_one(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=40),
                              assistant("m1", "r1", T0 + timedelta(seconds=1), output=10))
        data, _ = self.report()
        self.assertEqual(self.totals(data), {"a1": (1, 40, 0, 0, 0)})

    def test_message_id_plus_request_id_is_the_key(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=10), assistant("m1", "r2", T0, output=20),
                              assistant("m2", "r1", T0, output=30))
        data, _ = self.report()
        self.assertEqual(self.totals(data)["a1"][1], 60)

    def test_subagent_transcripts_are_read_and_a_response_copied_into_another_file_is_counted_once(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=10))
        self.write_transcript("p/s1/subagents/agent-1.jsonl", assistant("m2", "r2", T0, output=20, isSidechain=True))
        self.write_transcript("p/s2.jsonl", assistant("m1", "r1", T0, output=10))  # 續接的 session 帶著舊的回應
        data, _ = self.report()
        self.assertEqual(self.totals(data)["a1"][1], 30)

    def test_every_kind_of_token_is_kept_apart_and_cache_writes_split_by_lifetime(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, input=1, output=2, write_5m=3, write_1h=4, read=5))
        data, _ = self.report()
        self.assertEqual(self.totals(data), {"a1": (1, 2, 3, 4, 5)})
        self.assertEqual(data["summary"]["all"]["total"]["cacheWrite1h"], 4)

    def test_the_earliest_line_of_a_response_decides_which_account_it_belongs_to(self):
        # 請求送出時用的是當時的憑證：後面的行晚於切換也不改變歸屬
        self.switch(T0 + timedelta(seconds=1), "acct-2")
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=10),
                              assistant("m1", "r1", T0 + timedelta(seconds=5), output=40))
        data, _ = self.report()
        self.assertEqual(self.totals(data), {"a1": (1, 40, 0, 0, 0)})

    def test_non_assistant_records_and_empty_synthetic_responses_are_skipped_without_a_warning(self):
        synthetic = assistant("m9", "r9", T0, model="<synthetic>", input=0, output=0)
        del synthetic["requestId"]  # 實測：用戶端自己合成的訊息，用量全 0，有的還缺請求識別碼
        self.write_transcript("p/s1.jsonl", {"type": "user", "timestamp": stamp(T0), "message": {"content": "hi"}},
                              {"type": "file-history-snapshot", "snapshot": {}}, synthetic,
                              assistant("m1", "r1", T0, output=5))
        data, err = self.report()
        self.assertEqual(self.totals(data), {"a1": (1, 5, 0, 0, 0)})
        self.assertEqual((data["notices"], err), ([], ""))

    def test_a_line_break_character_inside_a_string_does_not_cut_the_line(self):
        # 實測：str.splitlines() 在字串內容的 U+2028 上多切一刀，完整的行會變成讀不懂
        record = assistant("m1", "r1", T0, output=5)
        record["message"]["note"] = f"before{LATE}after"
        self.write_transcript("p/s1.jsonl", record)
        data, _ = self.report()
        self.assertEqual((self.totals(data), data["notices"]), ({"a1": (1, 5, 0, 0, 0)}, []))

    def test_no_transcripts_at_all_is_an_empty_report_not_an_error(self):
        data, err = self.report()
        self.assertEqual((data["rows"], data["summary"]["all"]["accounts"], data["notices"], err), ([], [], [], ""))


class AttributionTest(ReportTestCase):
    def usage_at(self, at, output=1):
        return assistant(f"m-{stamp(at)}", f"r-{stamp(at)}", at, output=output, input=0)

    def test_usage_belongs_to_the_account_of_the_last_switch_at_or_before_it(self):
        self.switch(T0, "acct-1")
        self.switch(T0 + timedelta(hours=2), "acct-2")
        self.write_transcript("p/s1.jsonl",
                              self.usage_at(T0 + timedelta(minutes=1), 1),
                              self.usage_at(T0 + timedelta(hours=2) - timedelta(seconds=1), 2),
                              self.usage_at(T0 + timedelta(hours=2), 4),  # 切換的那一刻算新帳號
                              self.usage_at(T0 + timedelta(hours=5), 8))
        data, _ = self.report()
        self.assertEqual({k: v[1] for k, v in self.totals(data).items()}, {"a1": 3, "a2": 12})

    def test_usage_before_the_first_switch_is_unattributed_and_counted_in_the_total(self):
        self.switch(T0 + timedelta(hours=1), "acct-1")
        self.write_transcript("p/s1.jsonl", self.usage_at(T0, 5), self.usage_at(T0 + timedelta(hours=2), 7))
        data, _ = self.report()
        summary = data["summary"]["all"]
        self.assertEqual({k: v[1] for k, v in self.totals(data).items()}, {"a1": 7, None: 5})
        self.assertEqual(summary["total"]["output"], 12)
        self.assertEqual(summary["accounts"][-1]["account"], None)  # 未歸屬排最後

    def test_usage_after_a_switch_to_an_unknown_account_is_unattributed(self):
        self.switch(T0, "acct-1")
        self.switch(T0 + timedelta(hours=1), None)
        self.write_transcript("p/s1.jsonl", self.usage_at(T0 + timedelta(hours=2), 3))
        data, _ = self.report()
        self.assertEqual({k: v[1] for k, v in self.totals(data).items()}, {None: 3})

    def test_the_span_from_the_last_run_to_the_switch_found_after_a_restart_is_unattributed(self):
        last_run = T0 + timedelta(hours=1)
        self.switch(T0, "acct-1")
        self.switch(T0 + timedelta(hours=3), "acct-2", last_run_at=last_run)
        self.write_transcript("p/s1.jsonl",
                              self.usage_at(last_run - timedelta(seconds=1), 1),  # 停機之前
                              self.usage_at(last_run, 2),  # 上一次運作的那一刻起算
                              self.usage_at(T0 + timedelta(hours=3) - timedelta(seconds=1), 4),
                              self.usage_at(T0 + timedelta(hours=3), 8))  # 偵測到的那一刻歸新帳號
        data, _ = self.report()
        self.assertEqual({k: v[1] for k, v in self.totals(data).items()}, {"a1": 1, None: 6, "a2": 8})

    def test_a_switch_recorded_twice_after_a_failed_write_does_not_widen_the_unattributed_span(self):
        # 切換紀錄寫成、觀測檔寫失敗時，下一輪重記同一筆（帶同一個上一次運作時間）
        last_run = T0 + timedelta(hours=1)
        self.switch(T0 + timedelta(hours=3), "acct-2", last_run_at=last_run)
        self.switch(T0 + timedelta(hours=3, seconds=5), "acct-2", last_run_at=last_run)
        self.write_transcript("p/s1.jsonl", self.usage_at(T0 + timedelta(hours=3, seconds=2), 4))
        data, _ = self.report()
        self.assertEqual({k: v[1] for k, v in self.totals(data).items()}, {"a1": 4})

    def test_a_switch_without_a_last_run_time_leaves_no_unattributed_span(self):
        self.switch(T0, "acct-1")
        self.switch(T0 + timedelta(hours=3), "acct-2")  # 執行中偵測到的
        self.write_transcript("p/s1.jsonl", self.usage_at(T0 + timedelta(hours=2), 4))
        data, _ = self.report()
        self.assertEqual({k: v[1] for k, v in self.totals(data).items()}, {"a1": 4})

    def test_switch_log_lines_in_the_wrong_order_still_attribute_by_time(self):
        log = self.paths.managed_dir / ".state" / "switches.jsonl"
        self.switch(T0 + timedelta(hours=2), "acct-2")
        with open(log, "a", encoding="utf-8") as f:  # 追加一筆較早的
            f.write(json.dumps({"at": (T0 + timedelta(hours=1)).isoformat(), "accountId": "acct-1"}) + "\n")
        self.write_transcript("p/s1.jsonl", self.usage_at(T0 + timedelta(hours=1, minutes=30), 4))
        data, _ = self.report()
        self.assertEqual({k: v[1] for k, v in self.totals(data).items()}, {"a1": 4})


class DowntimeNoteTest(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", NOW - timedelta(days=2), output=1))
        self.write_transcript("p/s2.jsonl", assistant("m2", "r2", NOW - timedelta(days=60), output=1))

    def flags(self, data):
        return {name: data["summary"][name]["downtimeUnrecognized"] for name in ("7d", "30d", "all")}

    def test_without_any_last_run_time_in_the_log_the_note_applies_to_every_range_with_usage(self):
        self.switch(NOW - timedelta(days=90), "acct-1")
        data, _ = self.report()
        self.assertIsNone(data["downtimeRecordedSince"])
        self.assertEqual(self.flags(data), {"7d": True, "30d": True, "all": True})

    def test_ranges_that_start_before_the_first_recorded_last_run_time_get_the_note(self):
        self.switch(NOW - timedelta(days=90), "acct-1")
        self.switch(NOW - timedelta(days=20), "acct-2", last_run_at=NOW - timedelta(days=21))
        data, _ = self.report()
        self.assertEqual(data["downtimeRecordedSince"], (NOW - timedelta(days=20)).date().isoformat())
        self.assertEqual(self.flags(data), {"7d": False, "30d": True, "all": True})

    def test_a_range_starting_exactly_when_downtime_recording_began_has_no_note(self):
        start = datetime(2025, 12, 26, tzinfo=UTC)  # 近 7 天的起點：今天（1/1）往前 6 天的零點
        for offset, expected in ((timedelta(0), False), (timedelta(seconds=1), True)):
            with self.subTest(offset=offset):
                (self.paths.managed_dir / ".state" / "switches.jsonl").unlink(missing_ok=True)
                self.switch(NOW - timedelta(days=90), "acct-1")
                self.switch(start + offset, "acct-2", last_run_at=start - timedelta(hours=1))
                data, _ = self.report()
                self.assertEqual(self.flags(data)["7d"], expected)

    def test_a_range_without_usage_has_no_note(self):
        self.switch(NOW - timedelta(days=90), "acct-1")
        (self.paths.claude_dir / "projects" / "p" / "s1.jsonl").unlink()
        data, _ = self.report()
        self.assertEqual(self.flags(data), {"7d": False, "30d": False, "all": True})

    def test_the_page_texts_carry_both_forms_of_the_note(self):
        _, out, _ = self.run_report("--no-open")
        texts = self.read_texts(out.strip())
        self.assertIn("{date} 之前無從辨識停機時段", texts["downtimeSince"])
        self.assertTrue(texts["downtimeNever"].startswith("無從辨識停機時段"))


class LocalDaysAndRangesTest(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.switch(NOW - timedelta(days=90), "acct-1")

    def usage_at(self, at, output):
        return assistant(f"m-{stamp(at)}", f"r-{stamp(at)}", at, output=output, input=0)

    def test_usage_is_bucketed_into_local_days_across_the_utc_day_boundary(self):
        taipei = timezone(timedelta(hours=8))
        with mock.patch("cc_quota_tracker.token_report.local_zone", return_value=taipei):
            self.write_transcript("p/s1.jsonl",
                                  self.usage_at(datetime(2025, 12, 30, 15, 59, tzinfo=UTC), 1),  # 本機 12/30 23:59
                                  self.usage_at(datetime(2025, 12, 30, 16, 0, tzinfo=UTC), 2),  # 本機 12/31 00:00
                                  self.usage_at(datetime(2025, 12, 31, 15, 59, tzinfo=UTC), 4))
            data, _ = self.report()
        self.assertEqual({r["day"]: r["output"] for r in data["rows"]}, {"2025-12-30": 1, "2025-12-31": 6})

    def test_today_and_the_range_starts_follow_the_local_day(self):
        taipei = timezone(timedelta(hours=8))
        now = datetime(2025, 12, 31, 17, 0, tzinfo=UTC)  # 本機已經是 1/1 01:00
        with mock.patch("cc_quota_tracker.token_report.local_zone", return_value=taipei):
            data, _ = self.report(now=now)
        self.assertEqual(data["today"], "2026-01-01")
        self.assertEqual((data["summary"]["7d"]["from"], data["summary"]["30d"]["from"], data["summary"]["all"]["from"]),
                         ("2025-12-26", "2025-12-03", None))

    def test_seven_days_means_today_and_the_six_days_before_it(self):
        self.write_transcript("p/s1.jsonl",
                              self.usage_at(datetime(2025, 12, 25, 23, 59, tzinfo=UTC), 1),  # 第 8 天
                              self.usage_at(datetime(2025, 12, 26, 0, 0, tzinfo=UTC), 2),  # 第 7 天的開頭
                              self.usage_at(datetime(2026, 1, 1, 11, 0, tzinfo=UTC), 4),
                              self.usage_at(datetime(2025, 12, 2, 23, 59, tzinfo=UTC), 8),  # 30 天之外
                              self.usage_at(datetime(2025, 12, 3, 0, 0, tzinfo=UTC), 16))
        data, _ = self.report()
        output = {name: sum(a["output"] for a in data["summary"][name]["accounts"]) for name in ("7d", "30d", "all")}
        self.assertEqual(output, {"7d": 6, "30d": 1 + 2 + 4 + 16, "all": 31})

    def test_usage_within_one_utc_hour_is_one_cell_and_hours_in_one_local_day_merge(self):
        self.write_transcript("p/s1.jsonl", self.usage_at(datetime(2025, 12, 31, 3, 5, tzinfo=UTC), 1),
                              self.usage_at(datetime(2025, 12, 31, 3, 55, tzinfo=UTC), 2),
                              self.usage_at(datetime(2025, 12, 31, 20, 0, tzinfo=UTC), 4))
        data, _ = self.report()
        self.assertEqual([(r["day"], r["output"]) for r in data["rows"]], [("2025-12-31", 7)])


class OverviewDataTest(ReportTestCase):
    """總覽分頁用的資料：每日序列、各模型的細分、帳號的顏色。畫面的算術只剩加總，這些在 Python 端算好才測得到。"""

    def setUp(self):
        super().setUp()
        self.switch(NOW - timedelta(days=90), "acct-1")

    def used(self, at, account_id=None, model="claude-test-1", **counts):
        if account_id:
            self.switch(at - timedelta(minutes=1), account_id)
        name = f"{model}-{stamp(at)}"
        return assistant(name, "r-" + name, at, model=model, **counts)

    def test_every_figure_set_carries_the_token_total_and_the_combined_cache_write(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", R, input=1, output=2, write_5m=4, write_1h=8, read=16))
        total = self.report()[0]["summary"]["all"]["total"]
        self.assertEqual((total["tokens"], total["cacheWrite"]), (31, 12))

    def test_the_day_axis_runs_from_the_range_start_to_today_with_empty_days_in_between(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", datetime(2025, 12, 29, 9, 0, tzinfo=UTC), output=1),
                              assistant("m2", "r2", R, output=1))
        summary = self.report()[0]["summary"]
        self.assertEqual(summary["7d"]["days"], [f"2025-12-{d}" for d in (26, 27, 28, 29, 30, 31)] + ["2026-01-01"])
        self.assertEqual(len(summary["30d"]["days"]), 30)
        self.assertEqual(summary["all"]["days"][0], "2025-12-29")
        self.assertEqual(summary["all"]["days"][-1], "2026-01-01")
        self.assertEqual(len(summary["all"]["days"]), 4)

    def test_usage_dated_after_today_extends_the_axis_so_its_bar_is_not_dropped(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", NOW + timedelta(days=2), output=1),
                              assistant("m2", "r2", R, output=1))
        summary = self.report()[0]["summary"]
        self.assertEqual(summary["7d"]["days"][-1], "2026-01-03")
        self.assertIn("2026-01-03", {d["day"] for d in summary["7d"]["daily"]})

    def test_a_range_without_any_usage_has_no_days_when_it_is_all_and_a_full_axis_otherwise(self):
        summary = self.report()[0]["summary"]
        self.assertEqual((summary["all"]["days"], len(summary["7d"]["days"])), ([], 7))
        self.assertEqual(summary["7d"]["daily"], [])

    def test_the_daily_series_has_one_entry_per_day_and_account_and_none_for_empty_ones(self):
        morning = datetime(2025, 12, 31, 3, 0, tzinfo=UTC)
        evening = datetime(2025, 12, 31, 20, 0, tzinfo=UTC)
        self.write_transcript("p/s1.jsonl",
                              self.used(morning, "acct-1", input=1, output=1),
                              self.used(morning + timedelta(minutes=5), model="claude-test-2", input=2, output=0),
                              self.used(evening, "acct-2", input=0, output=4),
                              self.used(R, input=0, output=8))
        daily = self.report()[0]["summary"]["7d"]["daily"]
        self.assertEqual([(d["day"], d["account"], d["tokens"]) for d in daily],
                         [("2025-12-31", "a1", 4), ("2025-12-31", "a2", 4), ("2026-01-01", "a2", 8)])

    def test_usage_that_belongs_to_no_account_is_its_own_series_after_the_accounts(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", NOW - timedelta(days=100), input=0, output=3),
                              assistant("m2", "r2", R, input=0, output=5))
        self.switch(R - timedelta(minutes=5), "")  # 切到帳號未知
        daily = self.report()[0]["summary"]["all"]["daily"]
        self.assertEqual([(d["account"], d["tokens"]) for d in daily], [(None, 3), (None, 5)])

    def test_models_are_split_in_the_total_and_in_each_account_biggest_first(self):
        t = datetime(2025, 12, 31, 5, 0, tzinfo=UTC)
        self.write_transcript("p/s1.jsonl",
                              self.used(t, "acct-1", model="claude-test-1", input=10, output=0, read=30),
                              self.used(t + timedelta(minutes=2), model="claude-test-2", input=0, output=5),
                              self.used(t + timedelta(hours=2), "acct-2", model="claude-test-2", input=0, output=100))
        all_ = self.report()[0]["summary"]["all"]
        self.assertEqual([(m["model"], m["tokens"]) for m in all_["total"]["models"]],
                         [("claude-test-2", 105), ("claude-test-1", 40)])
        second, first = all_["accounts"]  # 用量多的帳號在前
        self.assertEqual((first["account"], [(m["model"], m["tokens"]) for m in first["models"]]),
                         ("a1", [("claude-test-1", 40), ("claude-test-2", 5)]))
        self.assertEqual((second["account"], [(m["model"], m["tokens"]) for m in second["models"]]),
                         ("a2", [("claude-test-2", 100)]))

    def test_each_model_row_has_the_same_figures_as_the_totals_including_ratio_and_cost(self):
        self.write_transcript("p/s1.jsonl", self.used(R, "acct-1", model="claude-test-1", input=2_000_000, output=0,
                                                      read=2_000_000),
                              self.used(R + timedelta(minutes=1), model="claude-unpriced", input=5, output=0))
        models = {m["model"]: m for m in self.report()[0]["summary"]["all"]["total"]["models"]}
        priced, unpriced = models["claude-test-1"], models["claude-unpriced"]
        self.assertAlmostEqual(priced["cacheHitRatio"], 0.5)
        self.assertAlmostEqual(priced["cost"], 2 * PRICES["input"] + 2 * PRICES["cacheRead"])
        self.assertEqual((priced["cacheWrite"], priced["costUnknown"]), (0, []))
        self.assertIsNone(unpriced["cost"])
        self.assertIn("claude-unpriced", unpriced["costUnknown"][0])

    def test_a_range_only_lists_the_models_used_in_it(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", NOW - timedelta(days=40), model="claude-test-2", output=1),
                              assistant("m2", "r2", R, output=1))
        summary = self.report()[0]["summary"]
        self.assertEqual([m["model"] for m in summary["30d"]["total"]["models"]], ["claude-test-1"])
        self.assertEqual({m["model"] for m in summary["all"]["total"]["models"]}, {"claude-test-1", "claude-test-2"})

    def test_accounts_take_the_four_account_colors_in_turn_and_start_over_from_the_fifth(self):
        for i in range(1, 6):
            self.write_transcript(f"p/s{i}.jsonl", self.used(R + timedelta(minutes=10 * i), f"acct-{i}", output=1))
        data, _ = self.report()
        self.assertEqual([a["color"] for a in data["accounts"]],
                         ["account_1", "account_2", "account_3", "account_4", "account_1"])

    def test_the_color_of_an_account_does_not_depend_on_the_range(self):
        self.write_transcript("p/s1.jsonl", self.used(NOW - timedelta(days=40), "acct-1", output=1),
                              self.used(R, "acct-2", output=1))
        data, _ = self.report()
        self.assertEqual([(a["key"], a["color"]) for a in data["accounts"]], [("a1", "account_1"), ("a2", "account_2")])


class DailyDataTest(ReportTestCase):
    """每日分頁用的資料：每個有用量的日子一筆，帶合計、各帳號與各模型的同樣數字。畫面只負責加總以外的排版。"""

    def setUp(self):
        super().setUp()
        self.switch(NOW - timedelta(days=90), "acct-1")

    def used(self, at, account_id=None, model="claude-test-1", **counts):
        if account_id:
            self.switch(at - timedelta(minutes=1), account_id)
        name = f"{model}-{stamp(at)}"
        return assistant(name, "r-" + name, at, model=model, **counts)

    def by_day(self, name="7d"):
        return self.report()[0]["summary"][name]["byDay"]

    def test_there_is_one_entry_per_day_with_usage_oldest_first_and_none_for_empty_days(self):
        self.write_transcript("p/s1.jsonl",
                              self.used(datetime(2025, 12, 29, 9, 0, tzinfo=UTC), input=0, output=1),
                              self.used(datetime(2025, 12, 29, 20, 0, tzinfo=UTC), input=0, output=2),
                              self.used(R, input=0, output=4))
        self.assertEqual([(d["day"], d["total"]["tokens"]) for d in self.by_day()],
                         [("2025-12-29", 3), ("2026-01-01", 4)])

    def test_a_range_only_lists_the_days_inside_it(self):
        self.write_transcript("p/s1.jsonl", self.used(NOW - timedelta(days=20), input=0, output=1),
                              self.used(R, input=0, output=2))
        self.assertEqual(len(self.by_day("7d")), 1)
        self.assertEqual(len(self.by_day("30d")), 2)

    def test_a_day_carries_the_same_figures_as_the_range_totals_including_ratio_and_cost(self):
        self.write_transcript("p/s1.jsonl", self.used(R, input=2_000_000, output=0, read=2_000_000))
        total = self.by_day()[0]["total"]
        self.assertAlmostEqual(total["cacheHitRatio"], 0.5)
        self.assertAlmostEqual(total["cost"], 2 * PRICES["input"] + 2 * PRICES["cacheRead"])
        self.assertEqual((total["tokens"], total["cacheRead"], total["costUnknown"]), (4_000_000, 2_000_000, []))

    def test_the_day_total_adds_up_the_accounts_and_the_unattributed_usage(self):
        day = datetime(2025, 12, 31, 5, 0, tzinfo=UTC)
        self.switch(day + timedelta(hours=3), "")  # 切到帳號未知
        self.write_transcript("p/s1.jsonl",
                              self.used(day, "acct-1", input=0, output=1),
                              self.used(day + timedelta(hours=2), "acct-2", input=0, output=2),
                              self.used(day + timedelta(hours=4), input=0, output=4))
        entry = self.by_day()[0]
        self.assertEqual(entry["total"]["tokens"], 7)
        self.assertEqual([(a["account"], a["tokens"]) for a in entry["accounts"]], [("a1", 1), ("a2", 2), (None, 4)])

    def test_a_day_without_an_account_has_no_entry_for_it(self):
        self.write_transcript("p/s1.jsonl", self.used(R, "acct-1", input=0, output=1),
                              self.used(NOW - timedelta(days=3), "acct-2", input=0, output=1))
        days = {d["day"]: [a["account"] for a in d["accounts"]] for d in self.by_day()}
        self.assertEqual(days, {"2025-12-29": ["a2"], "2026-01-01": ["a1"]})

    def test_models_are_split_in_the_day_and_in_each_account_biggest_first(self):
        t = datetime(2025, 12, 31, 5, 0, tzinfo=UTC)
        self.write_transcript("p/s1.jsonl",
                              self.used(t, "acct-1", model="claude-test-1", input=0, output=3),
                              self.used(t + timedelta(minutes=2), model="claude-test-2", input=0, output=5),
                              self.used(t + timedelta(hours=2), "acct-2", model="claude-test-1", input=0, output=10))
        entry = self.by_day()[0]
        self.assertEqual([(m["model"], m["tokens"]) for m in entry["total"]["models"]],
                         [("claude-test-1", 13), ("claude-test-2", 5)])
        first, second = entry["accounts"]
        self.assertEqual([(m["model"], m["tokens"]) for m in first["models"]], [("claude-test-2", 5), ("claude-test-1", 3)])
        self.assertEqual([(m["model"], m["tokens"]) for m in second["models"]], [("claude-test-1", 10)])

    def test_a_model_that_cannot_be_priced_only_marks_the_days_it_was_used_on(self):
        self.write_transcript("p/s1.jsonl",
                              self.used(NOW - timedelta(days=3), model="claude-unpriced", input=5, output=0),
                              self.used(R, input=5, output=0))
        older, newer = self.by_day()
        self.assertIsNone(older["total"]["cost"])
        self.assertIn("claude-unpriced", older["total"]["costUnknown"][0])
        self.assertEqual(newer["total"]["costUnknown"], [])
        self.assertIsNotNone(newer["total"]["cost"])

    def test_a_range_without_usage_has_no_days(self):
        self.assertEqual(self.by_day("all"), [])


class CacheHitRatioTest(ReportTestCase):
    def test_ratio_is_cache_read_over_input_plus_cache_writes_plus_cache_read_and_output_is_ignored(self):
        self.switch(T0 - timedelta(days=1), "acct-1")
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, input=10, output=1000, write_5m=20, write_1h=30,
                                                      read=140))
        data, _ = self.report()
        self.assertAlmostEqual(data["summary"]["all"]["total"]["cacheHitRatio"], 140 / 200)
        self.assertAlmostEqual(data["summary"]["all"]["accounts"][0]["cacheHitRatio"], 140 / 200)

    def test_a_row_with_no_input_at_all_has_no_ratio_instead_of_a_division_error(self):
        self.switch(T0 - timedelta(days=1), "acct-1")
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, input=0, output=5))
        data, _ = self.report()
        self.assertIsNone(data["summary"]["all"]["total"]["cacheHitRatio"])

    def test_the_page_states_how_the_ratio_is_computed(self):
        _, out, _ = self.run_report("--no-open")
        note = self.read_texts(out.strip())["cacheNote"]
        self.assertIn("cache 讀取 ÷（input＋cache 寫入＋cache 讀取），output 不計", note)
        self.assertIn("供應商沒有公布這個比例的算法", note)


class AccountLabelTest(ReportTestCase):
    def add_account(self, label, refresh, account_id):
        self.log_in(refresh=refresh, account_uuid=account_id)
        with self.cli_environment(), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["add", label]), 0)

    def remove_account(self, label):
        with self.cli_environment(), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["remove", label]), 0)

    def used_by(self, account_id, at=R):
        self.switch(at - timedelta(minutes=30), account_id)
        self.write_transcript(f"p/{account_id}.jsonl", assistant(f"m-{account_id}", f"r-{account_id}", at, output=1))

    def labels(self, **kw):
        data, _ = self.report(**kw)
        return [a["label"] for a in data["accounts"]]

    @property
    def label_map_file(self):
        return self.paths.managed_dir / ".state" / "account-labels.json"

    def test_accounts_show_the_label_of_their_current_binding(self):
        self.add_account("work", "rt-1", "acct-1")
        self.add_account("home", "rt-2", "acct-2")
        self.switch(T0 - timedelta(hours=2), "acct-1")
        self.switch(T0 - timedelta(hours=1), "acct-2")
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0 - timedelta(minutes=90), output=1),
                              assistant("m2", "r2", T0, output=2))
        data, _ = self.report()
        self.assertEqual(data["accounts"], [{"key": "a1", "label": "work", "color": "account_1"},
                          {"key": "a2", "label": "home", "color": "account_2"}])

    def test_accounts_with_no_binding_show_as_numbered_unwatched_accounts_in_order_of_first_appearance(self):
        self.add_account("work", "rt-1", "acct-1")
        self.switch(T0 - timedelta(hours=3), "acct-x")
        self.switch(T0 - timedelta(hours=2), "acct-1")
        self.switch(T0 - timedelta(hours=1), "acct-y")
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0 - timedelta(minutes=150), output=1),
                              assistant("m2", "r2", T0 - timedelta(minutes=90), output=2),
                              assistant("m3", "r3", T0, output=3))
        data, _ = self.report()
        self.assertEqual([a["label"] for a in data["accounts"]], ["未監看帳號 1", "work", "未監看帳號 2"])
        data, _ = self.report(system_language="en")
        self.assertEqual([a["label"] for a in data["accounts"]], ["Unwatched account 1", "work", "Unwatched account 2"])

    def test_a_removed_account_keeps_the_last_label_it_was_seen_with(self):
        self.add_account("work", "rt-1", "acct-1")
        self.used_by("acct-1")
        self.assertEqual(self.labels(), ["work"])
        self.remove_account("work")
        _, out, _ = self.run_report("--no-open")
        self.assertEqual(self.read_data(out.strip())["accounts"],
                         [{"key": "a1", "label": "work", "color": "account_1"}])
        self.assertNotIn("acct-1", self.read_html(out.strip()))

    def test_a_renamed_account_shows_the_new_label_and_stays_one_account(self):
        self.add_account("work", "rt-1", "acct-1")
        self.used_by("acct-1")
        self.assertEqual(self.labels(), ["work"])
        self.remove_account("work")
        self.add_account("job", "rt-1", "acct-1")  # 同一個登入換個標籤納管
        data, _ = self.report()
        self.assertEqual(data["accounts"], [{"key": "a1", "label": "job", "color": "account_1"}])
        self.assertEqual(len(data["rows"]), 1)
        self.remove_account("job")
        self.assertEqual(self.labels(), ["job"])  # 之後移除，沿用最新的標籤

    def test_an_account_first_seen_after_its_removal_is_an_unwatched_account(self):
        self.add_account("work", "rt-1", "acct-1")
        self.remove_account("work")  # 移除前沒產生過報表：沒有標籤可沿用
        self.used_by("acct-1")
        self.assertEqual(self.labels(), ["未監看帳號 1"])

    def test_unwatched_numbers_do_not_change_when_an_earlier_account_shows_up_later(self):
        self.used_by("acct-y", R)
        self.assertEqual(self.labels(), ["未監看帳號 1"])
        self.used_by("acct-x", R - timedelta(hours=5))  # 切換紀錄依時間排序，x 排在 y 前面
        self.assertEqual(self.labels(), ["未監看帳號 2", "未監看帳號 1"])

    def test_an_unwatched_account_that_is_later_watched_takes_its_label_and_keeps_it_after_removal(self):
        self.used_by("acct-1")
        self.assertEqual(self.labels(), ["未監看帳號 1"])
        self.add_account("work", "rt-1", "acct-1")
        self.assertEqual(self.labels(), ["work"])
        self.remove_account("work")
        self.assertEqual(self.labels(), ["work"])

    def test_the_number_of_an_unwatched_account_that_became_watched_is_not_given_out_again(self):
        self.used_by("acct-1")
        self.assertEqual(self.labels(), ["未監看帳號 1"])
        self.add_account("work", "rt-1", "acct-1")
        self.used_by("acct-2", R + timedelta(hours=1))
        self.assertEqual(self.labels(), ["work", "未監看帳號 2"])

    def test_a_new_unwatched_account_gets_the_number_after_the_highest_used_even_with_gaps(self):
        self.label_map_file.parent.mkdir(parents=True, exist_ok=True)
        self.label_map_file.write_text(json.dumps({"labels": {}, "unwatched": {"acct-a": 1, "acct-c": 3}}),
                                       encoding="utf-8")
        self.used_by("acct-a", R)
        self.used_by("acct-c", R + timedelta(hours=1))
        self.used_by("acct-n", R + timedelta(hours=2))
        self.assertEqual(self.labels(), ["未監看帳號 1", "未監看帳號 3", "未監看帳號 4"])

    def test_an_account_bound_to_two_snapshots_shows_the_label_that_sorts_first(self):
        self.add_account("zeta", "rt-1", "acct-1")
        self.add_account("alpha", "rt-1", "acct-1")  # 同一個登入再以另一個標籤納管
        self.used_by("acct-1")
        self.assertEqual(self.labels(), ["alpha"])

    def test_the_unwatched_label_follows_the_language_setting_while_the_number_stays(self):
        self.used_by("acct-x")
        self.assertEqual(self.labels(), ["未監看帳號 1"])
        self.assertEqual(self.labels(system_language="en"), ["Unwatched account 1"])

    def test_the_map_is_kept_in_the_managed_directory_and_the_page_has_only_labels(self):
        self.add_account("work", "rt-1", "acct-1")
        self.used_by("acct-1")
        self.used_by("acct-x", R + timedelta(hours=1))
        _, out, _ = self.run_report("--no-open")
        stored = self.label_map_file.read_text(encoding="utf-8")
        self.assertIn("acct-1", stored)
        self.assertIn("work", stored)
        html = self.read_html(out.strip())
        for secret in ("acct-1", "acct-x", "account-labels"):
            self.assertNotIn(secret, html)

    def test_a_map_that_cannot_be_read_warns_and_is_left_alone(self):
        self.add_account("work", "rt-1", "acct-1")
        self.used_by("acct-1")
        self.assertEqual(self.labels(), ["work"])
        before = self.label_map_file.read_bytes()
        self.remove_account("work")
        with self.locked("account-labels.json"):
            data, err = self.report()
        self.assertEqual(data["notices"], [{"kind": "labelsUnavailable"}])
        self.assertIn("帳號標籤的對照存取不了", err)
        self.assertEqual(self.label_map_file.read_bytes(), before)

    def test_a_map_that_cannot_be_written_warns_but_the_report_is_still_made(self):
        self.used_by("acct-x")
        with mock.patch.object(ManagedDirectory, "write_account_labels", side_effect=OSError("disk full")):
            data, _ = self.report()
        self.assertEqual(data["notices"], [{"kind": "labelsUnavailable"}])
        self.assertEqual([a["label"] for a in data["accounts"]], ["未監看帳號 1"])

    def error_log(self):
        path = self.settings_file().parent / "errors.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_the_daily_update_keeps_the_label_so_an_account_removed_before_any_report_still_has_it(self):
        self.add_account("work", "rt-1", "acct-1")
        self.used_by("acct-1")
        self.assertEqual(self.run_report("--update-ledger")[0], 0)  # 報表從沒產生過
        self.remove_account("work")
        self.assertEqual(self.labels(), ["work"])

    def test_the_daily_update_gives_unwatched_accounts_their_numbers(self):
        self.used_by("acct-x")
        self.used_by("acct-y", R + timedelta(hours=1))
        self.run_report("--update-ledger")
        self.assertEqual(json.loads(self.label_map_file.read_text(encoding="utf-8"))["unwatched"],
                         {"acct-x": 1, "acct-y": 2})

    def test_a_map_the_daily_update_cannot_read_goes_to_the_error_log_and_stderr_and_the_exit_code_stays_0(self):
        self.add_account("work", "rt-1", "acct-1")
        self.used_by("acct-1")
        self.run_report("--update-ledger")
        before = self.label_map_file.read_bytes()
        with self.locked("account-labels.json"):
            code, out, err = self.run_report("--update-ledger")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("帳號標籤的對照存取不了", err)
        self.assertIn("帳號標籤的對照存取不了", self.error_log())
        self.assertEqual(self.label_map_file.read_bytes(), before)

    def test_a_map_the_daily_update_cannot_write_does_not_change_how_the_ledger_update_ends(self):
        self.used_by("acct-x", NOW - timedelta(hours=30))
        with mock.patch.object(ManagedDirectory, "write_account_labels", side_effect=OSError("disk full")):
            code, _, err = self.run_report("--update-ledger")
        self.assertEqual(code, 0)
        self.assertIn("帳號標籤的對照存取不了", self.error_log())
        self.assertTrue((self.paths.managed_dir / ".state" / "usage-ledger.jsonl").exists())

    def test_a_ledger_failure_is_still_exit_1_and_the_labels_are_still_updated(self):
        self.used_by("acct-x", NOW - timedelta(hours=30))
        with mock.patch("cc_quota_tracker.atomic.append", side_effect=OSError(28, "No space left on device")):
            code, _, err = self.run_report("--update-ledger")
        self.assertEqual(code, 1)
        self.assertIn("用量帳本更新失敗（No space left on device）", err)
        self.assertIn("acct-x", self.label_map_file.read_text(encoding="utf-8"))

    def test_a_map_that_cannot_be_understood_is_treated_as_empty(self):
        self.label_map_file.parent.mkdir(parents=True, exist_ok=True)
        self.label_map_file.write_text("{not json", encoding="utf-8")
        self.used_by("acct-x")
        data, _ = self.report()
        self.assertEqual((data["notices"], [a["label"] for a in data["accounts"]]), ([], ["未監看帳號 1"]))
        self.assertIn("acct-x", self.label_map_file.read_text(encoding="utf-8"))

    def test_entries_in_the_map_that_make_no_sense_are_dropped(self):
        self.label_map_file.parent.mkdir(parents=True, exist_ok=True)
        self.label_map_file.write_text(json.dumps({"labels": {"acct-x": 5, "acct-y": "kept"},
                                                   "unwatched": {"acct-z": "1", "acct-w": 2, "acct-v": True,
                                                                  "acct-u": 0, "acct-t": -4}}),
                                       encoding="utf-8")
        for i, account_id in enumerate(("acct-x", "acct-y", "acct-z", "acct-w", "acct-v", "acct-u", "acct-t")):
            self.used_by(account_id, R - timedelta(hours=7 - i))
        self.assertEqual(self.labels(), ["未監看帳號 3", "kept", "未監看帳號 4", "未監看帳號 2", "未監看帳號 5",
                                         "未監看帳號 6", "未監看帳號 7"])

    def test_accounts_without_usage_are_not_listed(self):
        self.switch(T0 - timedelta(hours=1), "acct-1")
        self.switch(T0 - timedelta(minutes=30), "acct-2")
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=1))
        data, _ = self.report()
        self.assertEqual([a["key"] for a in data["accounts"]], ["a2"])

    def test_the_page_carries_neither_account_ids_nor_emails(self):
        self.add_account("work", "rt-1", "acct-1")
        self.switch(T0 - timedelta(hours=1), "acct-1")
        self.switch(T0 - timedelta(minutes=30), "acct-secret-9")
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0 - timedelta(minutes=40), output=1),
                              assistant("m2", "r2", T0, output=2))
        _, out, _ = self.run_report("--no-open")
        html = self.read_html(out.strip())
        for secret in ("acct-1", "acct-secret-9", "someone@example.com", "example.com"):
            self.assertNotIn(secret, html)
        self.assertIn("work", html)


class AccountLabelPermissionTest(ReportTestCase, WindowsAclAssertions):
    @unittest.skipUnless(sys.platform == "win32", "Windows ACL")
    def test_the_label_map_is_private_like_the_switch_log(self):
        self.switch(T0 - timedelta(hours=1), "acct-x")
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=1))
        self.report()
        state = self.paths.managed_dir / ".state"
        for path in (state / "account-labels.json", state / "switches.jsonl"):
            self.assert_private(path)


class WarningsTest(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.switch(T0 - timedelta(days=1), "acct-1")

    def error_log(self):
        path = self.settings_file().parent / "errors.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_unrecognized_structures_are_counted_not_turned_into_zero_and_warned_everywhere(self):
        no_usage = assistant("m2", "r2", T0)
        del no_usage["message"]["usage"]
        broken_count = assistant("m3", "r3", T0)
        broken_count["message"]["usage"]["output_tokens"] = "12"
        no_creation = assistant("m4", "r4", T0)
        del no_creation["message"]["usage"]["cache_creation"]
        no_ids = assistant("m5", "r5", T0)
        del no_ids["requestId"]
        bad_time = assistant("m6", "r6", T0)
        bad_time["timestamp"] = "yesterday"
        naive_time = assistant("m7", "r7", T0)
        naive_time["timestamp"] = "2025-12-31T08:00:00"
        negative = assistant("m8", "r8", T0)
        negative["message"]["usage"]["input_tokens"] = -1
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=5), no_usage, broken_count, no_creation,
                              no_ids, bad_time, naive_time, negative, "{not json", "[1, 2]")
        data, err = self.report()
        self.assertEqual(self.totals(data), {"a1": (1, 5, 0, 0, 0)})  # 認不得的不算成 0，也不計入
        self.assertEqual(data["notices"], [{"kind": "schemaMismatch", "count": 9}])
        self.assertIn("9 筆對話紀錄的結構不符", err)
        self.assertIn("9 筆對話紀錄的結構不符", self.error_log())
        _, out, _ = self.run_report("--no-open")
        self.assertEqual(self.read_data(out.strip())["notices"], data["notices"])
        self.assertIn("{n} 筆對話紀錄的結構不符", self.read_texts(out.strip())["notices"]["schemaMismatch"])

    def test_a_last_line_that_is_still_being_written_is_not_a_mismatch(self):
        path = self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=5))
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"type":"assistant","message":{"usage":{"input_tok')  # 沒有換行：Claude Code 正在寫
        data, err = self.report()
        self.assertEqual((self.totals(data), data["notices"], err), ({"a1": (1, 5, 0, 0, 0)}, [], ""))

    def test_a_transcript_file_that_cannot_be_opened_is_warned_not_silently_dropped(self):
        path = self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=5))
        real_open = open

        def locked_open(file, *args, **kwargs):
            if str(file).endswith("s1.jsonl"):
                raise PermissionError("locked")
            return real_open(file, *args, **kwargs)
        with mock.patch("cc_quota_tracker.transcripts.open", locked_open, create=True):
            data, err = self.report()
        self.assertEqual(data["notices"], [{"kind": "transcriptUnreadable", "count": 1}])
        self.assertIn("1 個對話紀錄檔讀不到", err)
        self.assertTrue(path.exists())

    def test_an_unreadable_switch_log_lists_everything_as_unattributed_and_warns(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=5))
        with self.locked("switches.jsonl"):
            data, err = self.report()
        self.assertEqual(self.totals(data), {None: (1, 5, 0, 0, 0)})
        self.assertEqual(data["notices"], [{"kind": "switchLogUnreadable"}])
        self.assertIn("切換紀錄讀不到", err)

    def test_switch_log_lines_that_cannot_be_understood_are_skipped_and_counted(self):
        log = self.paths.managed_dir / ".state" / "switches.jsonl"
        with open(log, "a", encoding="utf-8") as f:
            f.write("garbage\n" + json.dumps({"accountId": "acct-3"}) + "\n[1]\n")  # 不是物件、缺時間、不是 JSON
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=5))
        data, err = self.report()
        self.assertEqual(self.totals(data), {"a1": (1, 5, 0, 0, 0)})
        self.assertEqual(data["notices"], [{"kind": "switchLogSkipped", "count": 3}])
        self.assertIn("3 行讀不懂", err)

    def test_a_missing_switch_log_is_not_a_warning(self):
        (self.paths.managed_dir / ".state" / "switches.jsonl").unlink()
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=5))
        data, err = self.report()
        self.assertEqual((data["notices"], err, self.totals(data)), ([], "", {None: (1, 5, 0, 0, 0)}))

    def test_warnings_follow_the_language_setting(self):
        self.write_transcript("p/s1.jsonl", "{not json")
        _, err = self.report(system_language="en")
        self.assertIn("1 transcript entries have an unrecognized structure", err)


class CommandTest(ReportTestCase):
    def test_no_open_writes_the_report_next_to_the_settings_file_and_prints_only_its_path(self):
        code, out, err = self.run_report("--no-open")
        expected = self.settings_file().parent / "token-report.html"
        self.assertEqual((code, out.strip(), err), (0, str(expected), ""))
        self.assertTrue(expected.is_file())

    def test_the_report_is_overwritten_each_time(self):
        self.switch(T0 - timedelta(days=1), "acct-1")
        _, out, _ = self.run_report("--no-open")
        first = self.read_data(out.strip())
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, output=5))
        _, out, _ = self.run_report("--no-open")
        self.assertEqual((first["rows"], len(self.read_data(out.strip())["rows"])), ([], 1))
        self.assertEqual([p.name for p in self.settings_file().parent.iterdir() if p.name.endswith(".html")],
                         ["token-report.html"])

    def test_without_no_open_the_default_browser_opens_the_report(self):
        with mock.patch("webbrowser.open", return_value=True) as opened:
            code, out, err = self.run_report()
        path = self.settings_file().parent / "token-report.html"
        self.assertEqual((code, err), (0, ""))
        opened.assert_called_once_with(path.as_uri())
        self.assertEqual(out.strip(), str(path))

    def test_a_browser_that_cannot_be_opened_still_leaves_the_report_and_says_where_it_is(self):
        with mock.patch("webbrowser.open", return_value=False):
            code, _, err = self.run_report()
        self.assertEqual(code, 0)
        self.assertIn(str(self.settings_file().parent / "token-report.html"), err)

    def test_no_open_never_touches_the_browser(self):
        with mock.patch("webbrowser.open") as opened:
            self.run_report("--no-open")
        opened.assert_not_called()

    def test_a_report_that_cannot_be_written_fails_with_exit_code_1_and_the_reason_on_stderr(self):
        with mock.patch("cc_quota_tracker.atomic.write_atomic", side_effect=PermissionError(13, "denied")):
            code, out, err = self.run_report("--no-open")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("token-report.html", err)
        self.assertIn("denied", err)

    def test_other_arguments_are_a_usage_error(self):
        for args in (("--open",), ("--no-open", "x"), ("x",)):
            with self.subTest(args=args):
                code, out, err = self.run_report(*args)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("report", err)

    def test_warnings_do_not_change_the_exit_code(self):
        self.write_transcript("p/s1.jsonl", "{not json")
        code, _, err = self.run_report("--no-open")
        self.assertEqual(code, 0)
        self.assertNotEqual(err, "")


class PageTest(ReportTestCase):
    def html(self, **kw):
        _, out, _ = self.run_report("--no-open", **kw)
        return self.read_html(out.strip())

    def test_the_page_loads_nothing_external_and_does_not_refresh_itself(self):
        html = self.html()
        self.assertNotRegex(html, r"(?i)https?://|//cdn|@import|url\(|<link|<img|<iframe|\ssrc=|\shref=")
        self.assertNotRegex(html, r"(?i)http-equiv|setInterval|setTimeout|fetch\(|XMLHttpRequest")

    def test_the_page_follows_the_language_setting(self):
        self.assertIn('<html lang="zh-TW">', self.html())
        _, out, _ = self.run_report("--no-open", system_language="en")
        self.assertIn('<html lang="en">', self.read_html(out.strip()))
        texts = self.read_texts(out.strip())
        self.assertEqual((texts["cacheHitRatio"], texts["total"], texts["unattributed"]),
                         ("Cache hit ratio", "Total", "Unattributed"))
        self.assertNotRegex(json.dumps(texts, ensure_ascii=False), "[一-鿿]")

    def test_the_language_in_the_settings_file_wins_over_the_system(self):
        self.write_settings(language="en")
        self.assertIn('<html lang="en">', self.html(system_language="zh-TW"))

    def test_the_header_carries_the_generation_time_and_the_data_names_the_ranges(self):
        data, _ = self.report()
        self.assertEqual(data["generatedAt"], NOW.isoformat())
        self.assertEqual(list(data["summary"]), ["7d", "30d", "all"])
        _, out, _ = self.run_report("--no-open")
        self.assertEqual(self.read_texts(out.strip())["generatedAt"], "產生時間")

    def test_data_that_looks_like_markup_cannot_break_out_of_the_page(self):
        self.switch(T0 - timedelta(days=1), "acct-1")
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", T0, model="</script><script>alert(1)</script>{{TEXTS}}",
                                                      output=5))
        html = self.html()
        self.assertEqual(html.count("<script"), 3)  # 兩份資料＋腳本，沒有多出來的
        data = self.read_data(self.settings_file().parent / "token-report.html")
        self.assertEqual(data["rows"][0]["model"], "</script><script>alert(1)</script>{{TEXTS}}")
