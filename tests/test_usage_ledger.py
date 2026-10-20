"""縫：命令列 `report --no-open` 與不寫進說明的 `report --update-ledger`，跑在假 home 上。
帳本的內容靠「刪掉對話紀錄後報表還在不在」驗；只有「只存 token 數」「只追加」「收緊權限」這幾條直接讀帳本檔。"""
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from cc_quota_tracker import usage_ledger
from cc_quota_tracker.__main__ import main
from tests.fakehome import NOW, WindowsAclAssertions
from tests.test_token_report import ReportTestCase, assistant, stamp

UTC = timezone.utc
OLD = NOW - timedelta(hours=26)  # 前一天 10:00：過了 24 小時以上
RECENT = NOW - timedelta(hours=1)
# NOW 是 12:00，所以 24 小時前整是前一天 12:00：它之前的小時入帳，它之後的小時（含）每次重算
LEDGER_EDGE = NOW - timedelta(hours=24)


class LedgerTestCase(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.switch(NOW - timedelta(days=30), "acct-1")

    @property
    def ledger_file(self):
        return self.paths.managed_dir / ".state" / "usage-ledger.jsonl"

    def ledger_rows(self):
        """入帳的格子（批次標頭不算）。"""
        rows = [json.loads(line) for line in self.ledger_file.read_text(encoding="utf-8").splitlines()]
        return [row for row in rows if "hour" in row]

    def delete_transcripts(self):
        for path in (self.paths.claude_dir / "projects").rglob("*.jsonl"):
            path.unlink()

    def output_of(self, data, name="all"):
        return sum(row["output"] for row in data["summary"][name]["accounts"])

    def lock(self, wait=0):
        """像另一個行程那樣占著帳本的鎖。"""
        return usage_ledger.exclusive(self.paths.managed_dir / ".state" / "usage-ledger.lock", wait)


class LedgerKeepsUsageTest(LedgerTestCase):
    def test_usage_already_ledgered_stays_in_the_report_after_the_transcripts_are_deleted(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=7, input=3, write_5m=2, write_1h=4, read=9))
        data, _ = self.report()
        self.assertEqual(self.totals(data), {"a1": (3, 7, 2, 4, 9)})
        self.delete_transcripts()
        data, _ = self.report()
        self.assertEqual(self.totals(data), {"a1": (3, 7, 2, 4, 9)})
        self.assertEqual(data["rows"][0]["day"], OLD.date().isoformat())

    def test_running_twice_with_the_transcripts_still_there_does_not_count_anything_twice(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=7), assistant("m2", "r2", RECENT, output=5))
        first, _ = self.report()
        second, _ = self.report()
        self.assertEqual((self.output_of(first), self.output_of(second)), (12, 12))

    def test_the_hour_before_the_24_hour_edge_is_ledgered_and_the_hour_after_it_is_recomputed(self):
        before = LEDGER_EDGE - timedelta(minutes=1)  # 11:59 的那個小時 11:00～12:00 已整個過了 24 小時
        after = LEDGER_EDGE  # 12:00 的那個小時 12:00～13:00 還沒過
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", before, output=3), assistant("m2", "r2", after, output=5))
        self.report()
        self.delete_transcripts()
        data, _ = self.report()
        self.assertEqual(self.output_of(data), 3)  # 只有入帳的那一小時留下來
        self.assertEqual([row["output"] for row in self.ledger_rows()], [3])

    def test_the_hour_the_ledger_stops_at_is_counted_from_the_transcripts_not_dropped(self):
        before = LEDGER_EDGE - timedelta(minutes=1)
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", before, output=3),
                              assistant("m2", "r2", LEDGER_EDGE, output=5))
        self.assertEqual(self.output_of(self.report()[0]), 8)
        self.assertEqual(self.output_of(self.report()[0]), 8)  # 入帳之後的第二次也一樣：不漏、不重複

    def test_the_last_24_hours_are_recomputed_each_time_so_a_late_record_is_not_missed(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", RECENT, output=5))
        self.assertEqual(self.output_of(self.report()[0]), 5)
        self.write_transcript("p/s2.jsonl", assistant("m2", "r2", RECENT - timedelta(minutes=30), output=6))
        self.assertEqual(self.output_of(self.report()[0]), 11)
        self.assertFalse(self.ledger_file.exists())  # 最近 24 小時沒有東西可以入帳

    def test_a_later_run_appends_only_the_hours_that_have_since_passed_24_hours(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3),
                              assistant("m2", "r2", NOW - timedelta(hours=10), output=5))
        self.report()
        first = self.ledger_file.read_bytes()
        self.report()
        self.assertEqual(self.ledger_file.read_bytes(), first)  # 沒有新的小時可入帳：一個位元組都不動
        code, _, err = self.run_report("--no-open", now=NOW + timedelta(hours=20))
        self.assertEqual(code, 0, err)
        second = self.ledger_file.read_bytes()
        self.assertTrue(second.startswith(first))  # 只追加，既有的內容不改寫
        self.assertEqual([row["output"] for row in self.ledger_rows()], [3, 5])
        self.delete_transcripts()
        data, _ = self.report(now=NOW + timedelta(hours=20))
        self.assertEqual(self.output_of(data), 8)

    def test_the_ledger_holds_token_counts_only_not_money(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3))
        self.report()
        cell = self.ledger_rows()[0]
        self.assertEqual(sorted(cell), ["accountId", "cacheRead", "cacheWrite1h", "cacheWrite5m", "hour", "input",
                                        "model", "output"])

    def test_usage_with_no_account_is_ledgered_as_unattributed(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", NOW - timedelta(days=40), output=3))
        self.report()
        self.delete_transcripts()
        data, _ = self.report()
        self.assertEqual(self.totals(data), {None: (1, 3, 0, 0, 0)})

    def test_usage_is_split_by_account_and_model_per_hour_when_ledgered(self):
        self.switch(OLD, "acct-2")
        self.write_transcript("p/s1.jsonl",
                              assistant("m1", "r1", OLD - timedelta(minutes=30), model="claude-a", output=1),
                              assistant("m2", "r2", OLD + timedelta(minutes=10), model="claude-a", output=2),
                              assistant("m3", "r3", OLD + timedelta(minutes=20), model="claude-b", output=4))
        self.report()
        self.delete_transcripts()
        data, _ = self.report()
        self.assertEqual(sorted((r["account"], r["model"], r["output"]) for r in data["rows"]),
                         [("a1", "claude-a", 1), ("a2", "claude-a", 2), ("a2", "claude-b", 4)])

    def test_accounts_in_the_ledger_keep_a_key_even_when_the_switch_log_cannot_be_read(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3))
        self.report()
        self.delete_transcripts()
        with self.locked("switches.jsonl"):
            data, _ = self.report()
        self.assertEqual(self.totals(data), {"a1": (1, 3, 0, 0, 0)})
        self.assertEqual([a["label"] for a in data["accounts"]], ["未監看帳號 1"])


class LedgerDaysTest(LedgerTestCase):
    def test_usage_across_a_utc_day_boundary_lands_on_two_days_and_stays_there_once_ledgered(self):
        late = datetime(2025, 12, 29, 23, 30, tzinfo=UTC)
        early = datetime(2025, 12, 30, 0, 30, tzinfo=UTC)
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", late, output=1), assistant("m2", "r2", early, output=2))
        self.report()
        self.delete_transcripts()
        data, _ = self.report()
        self.assertEqual([(r["day"], r["output"]) for r in data["rows"]], [("2025-12-29", 1), ("2025-12-30", 2)])

    def test_ledgered_hours_are_converted_to_local_days_when_the_report_is_made(self):
        late = datetime(2025, 12, 29, 23, 30, tzinfo=UTC)
        early = datetime(2025, 12, 30, 0, 30, tzinfo=UTC)
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", late, output=1), assistant("m2", "r2", early, output=2))
        self.report()
        self.delete_transcripts()
        with mock.patch("cc_quota_tracker.token_report.local_zone", return_value=timezone(timedelta(hours=8))):
            data, _ = self.report()
        self.assertEqual([(r["day"], r["output"]) for r in data["rows"]], [("2025-12-30", 3)])  # 台灣時間同一天


class LedgerHeaderTest(LedgerTestCase):
    def test_the_report_carries_the_earliest_data_and_the_last_update(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3), assistant("m2", "r2", RECENT, output=1))
        data, _ = self.report()
        self.assertEqual(data["ledger"], {"earliest": OLD.replace(minute=0).isoformat(), "updatedAt": NOW.isoformat()})
        self.delete_transcripts()
        data, _ = self.report(now=NOW + timedelta(hours=3))
        self.assertEqual(data["ledger"], {"earliest": OLD.replace(minute=0).isoformat(),
                                          "updatedAt": (NOW + timedelta(hours=3)).isoformat()})

    def test_without_any_usage_there_is_no_earliest_time(self):
        data, _ = self.report()
        self.assertEqual(data["ledger"], {"earliest": None, "updatedAt": NOW.isoformat()})

    def test_the_page_has_the_texts_for_both_header_items_in_both_languages(self):
        _, out, _ = self.run_report("--no-open")
        texts = self.read_texts(out.strip())
        self.assertEqual((texts["ledgerUpdatedAt"], texts["earliest"]), ("帳本更新", "最早有資料"))
        _, out, _ = self.run_report("--no-open", system_language="en")
        texts = self.read_texts(out.strip())
        self.assertEqual((texts["ledgerUpdatedAt"], texts["earliest"]), ("Ledger updated", "Earliest data"))


class UpdateLedgerOnlyTest(LedgerTestCase):
    def error_log(self):
        path = self.settings_file().parent / "errors.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_the_hidden_flag_updates_the_ledger_without_writing_a_report_or_printing_anything(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3))
        code, out, err = self.run_report("--update-ledger")
        self.assertEqual((code, out, err), (0, "", ""))
        self.assertFalse((self.settings_file().parent / "token-report.html").exists())
        self.delete_transcripts()
        data, _ = self.report()
        self.assertEqual(self.output_of(data), 3)

    def test_the_flag_is_not_in_the_help_text(self):
        for lang in ("zh-TW", "en"):
            with self.cli_environment(lang), mock.patch("builtins.print") as printed:
                self.assertEqual(main(["--help"]), 0)
            self.assertNotIn("update-ledger", printed.call_args[0][0])

    def test_a_failure_exits_1_and_goes_to_stderr_and_the_error_log(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3))
        with mock.patch("cc_quota_tracker.atomic.append", side_effect=OSError(28, "No space left on device")):
            code, out, err = self.run_report("--update-ledger")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("用量帳本更新失敗（No space left on device）", err)
        self.assertIn("用量帳本更新失敗（No space left on device）", self.error_log())
        self.assertFalse((self.settings_file().parent / "token-report.html").exists())


class LedgerFailureTest(LedgerTestCase):
    def test_a_failed_update_leaves_the_report_made_with_a_banner_with_the_reason_and_the_old_update_time(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3))
        self.report(now=NOW - timedelta(hours=5))  # 先有一次成功的更新
        with mock.patch("cc_quota_tracker.atomic.append", side_effect=OSError(28, "No space left on device")):
            self.write_transcript("p/s2.jsonl", assistant("m2", "r2", NOW - timedelta(hours=30), output=4))
            data, err = self.report(now=NOW + timedelta(days=1))
        self.assertEqual(self.output_of(data), 7)  # 沒入帳的照對話紀錄算
        notice = [n for n in data["notices"] if n["kind"] == "ledgerUpdateFailed"]
        self.assertEqual(notice, [{"kind": "ledgerUpdateFailed", "reason": "No space left on device"}])
        self.assertEqual(data["ledger"]["updatedAt"], (NOW - timedelta(hours=5)).isoformat())
        self.assertIn("No space left on device", err)

    def test_the_failure_stays_visible_in_later_reports_until_an_update_succeeds(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3))
        with mock.patch("cc_quota_tracker.atomic.append", side_effect=OSError(28, "No space left on device")):
            self.run_report("--update-ledger")
        with self.lock():  # 這次報表沒機會更新帳本
            with mock.patch("cc_quota_tracker.usage_ledger.LOCK_WAIT_SECONDS", 0.05):
                data, _ = self.report()
        self.assertEqual([n["kind"] for n in data["notices"]], ["ledgerUpdateFailed"])
        data, err = self.report()
        self.assertEqual((data["notices"], err), ([], ""))
        self.assertEqual(data["ledger"]["updatedAt"], NOW.isoformat())

    def test_transcripts_that_cannot_be_read_do_not_hold_the_ledger_back(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3))
        self.write_transcript("p/s2.jsonl", assistant("m2", "r2", OLD, output=4))
        real_open = open

        def locked_open(file, *args, **kwargs):
            if str(file).endswith("s2.jsonl"):
                raise PermissionError("locked")
            return real_open(file, *args, **kwargs)
        with mock.patch("cc_quota_tracker.transcripts.open", locked_open, create=True):
            data, _ = self.report()
        self.assertEqual([n["kind"] for n in data["notices"]], ["transcriptUnreadable"])  # 示警，但不是帳本失敗
        self.assertEqual(data["ledger"]["updatedAt"], NOW.isoformat())
        self.delete_transcripts()  # 能讀的那個已經入帳；讀不到的沒算進去，這是示警的意思
        self.assertEqual(self.output_of(self.report()[0]), 3)

    def test_a_torn_batch_is_not_used_and_the_next_update_writes_the_hours_again(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3))
        state = self.paths.managed_dir / ".state"
        state.mkdir(parents=True, exist_ok=True)
        # 上一次寫到一半被中斷：標頭說有兩行，只寫了一行，也沒有收尾的換行
        torn = (usage_ledger.encode_batch([usage_ledger.LedgerCell(OLD.replace(minute=0), "acct-1", "claude-test-1",
                                                                  (1, 3, 0, 0, 0))] * 2, LEDGER_EDGE)
                .decode("utf-8").rstrip("\n").rsplit("\n", 1)[0].encode("utf-8"))
        self.ledger_file.write_bytes(torn)
        data, _ = self.report()
        self.assertEqual(self.output_of(data), 3)  # 殘批不採用、也沒有重複
        self.assertEqual([n for n in data["notices"] if n["kind"] == "ledgerSkipped"],
                         [{"kind": "ledgerSkipped", "count": 1}])
        self.delete_transcripts()
        self.assertEqual(self.output_of(self.report()[0]), 3)  # 新批次接在殘批後面，照樣讀得回來


class LedgerLockTest(LedgerTestCase):
    def test_while_another_process_holds_the_lock_the_append_is_skipped_and_the_report_is_still_made(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3))
        with self.lock(), mock.patch("cc_quota_tracker.usage_ledger.LOCK_WAIT_SECONDS", 0.05):
            data, err = self.report()
        self.assertEqual((self.output_of(data), data["notices"], err), (3, [], ""))  # 跳過不是失敗
        self.assertFalse(self.ledger_file.exists())
        self.assertIsNone(data["ledger"]["updatedAt"])
        self.report()  # 鎖放開之後照常入帳
        self.delete_transcripts()
        self.assertEqual(self.output_of(self.report()[0]), 3)

    def test_it_waits_for_the_other_process_to_finish_when_that_is_quick(self):
        import threading
        import time
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3))
        held = threading.Event()

        def hold():
            with self.lock():
                held.set()
                time.sleep(0.3)
        thread = threading.Thread(target=hold)
        thread.start()
        held.wait(5)
        try:
            data, _ = self.report()
        finally:
            thread.join()
        self.assertEqual(data["ledger"]["updatedAt"], NOW.isoformat())
        self.assertTrue(self.ledger_file.exists())

    def test_several_processes_started_together_write_each_hour_once(self):
        now = datetime.now(UTC)
        hours = [now - timedelta(hours=30 + i) for i in range(3)]
        for i, at in enumerate(hours):
            self.write_transcript(f"p/s{i}.jsonl", assistant(f"m{i}", f"r{i}", at, output=i + 1))
        self.switch(now - timedelta(days=30), "acct-1")
        env = dict(self.env, USERPROFILE=str(self.home), HOME=str(self.home), PYTHONPATH=str(Path.cwd()))
        for name in ("SYSTEMROOT", "PATH"):
            if name in os.environ:
                env[name] = os.environ[name]
        procs = [subprocess.Popen([sys.executable, "-m", "cc_quota_tracker", "report", "--update-ledger"], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
        results = [(p.returncode, err) for p, (_, err) in ((p, p.communicate(timeout=120)) for p in procs)]
        self.assertEqual(results, [(0, "")] * 4)
        cells = usage_ledger.decode(self.ledger_file.read_text(encoding="utf-8")).cells
        self.assertEqual(sorted(c.counts[1] for c in cells), [1, 2, 3])


class LedgerPermissionTest(LedgerTestCase, WindowsAclAssertions):
    @unittest.skipUnless(sys.platform == "win32", "Windows ACL")
    def test_the_ledger_and_its_status_are_private_like_the_switch_log(self):
        self.write_transcript("p/s1.jsonl", assistant("m1", "r1", OLD, output=3))
        self.report()
        for path in (self.ledger_file, self.ledger_file.with_name("usage-ledger-status.json"),
                     self.ledger_file.parent, self.switch_log_file()):
            self.assert_private(path)

    def switch_log_file(self):
        return self.paths.managed_dir / ".state" / "switches.jsonl"


if __name__ == "__main__":
    unittest.main()
