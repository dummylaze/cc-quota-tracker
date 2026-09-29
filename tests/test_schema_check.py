"""架設者檢查指令：從命令列輸出觀察。"""
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from cc_quota_tracker.__main__ import main
from tests.fakehome import HomeTestCase, claude_json, limit_field, usage_cache

LIMITS = "cachedUsageUtilization.utilization.limits"


class SchemaCheckTest(HomeTestCase):
    def run_check(self):
        out, err = io.StringIO(), io.StringIO()
        with self.cli_environment(), redirect_stdout(out), redirect_stderr(err):
            code = main(["check"])
        return code, out.getvalue() + err.getvalue()

    def line(self, output, path):
        """某個欄位路徑那一行；路徑後面緊接全形括號，避免 limits 對到 limits[]。"""
        lines = [ln for ln in output.splitlines() if f" {path}（" in ln]
        self.assertEqual(len(lines), 1, (path, output))
        return lines[0]

    def write_raw_cache(self, mutate):
        data = claude_json(usage_cache())
        mutate(data["cachedUsageUtilization"])
        self.write_claude_json(data)

    def test_compatible_cache_passes_every_depended_field(self):
        self.write_cache(five_hour=limit_field(10), seven_day=limit_field(40))
        code, out = self.run_check()
        self.assertEqual(code, 0)
        for path in ("oauthAccount.accountUuid", "cachedUsageUtilization.fetchedAtMs",
                     "cachedUsageUtilization.accountUuid", "cachedUsageUtilization.utilization",
                     LIMITS, f"{LIMITS}[]", f"{LIMITS}[].kind", f"{LIMITS}[].percent",
                     "cachedUsageUtilization.utilization.five_hour"):
            with self.subTest(path=path):
                self.assertIn("通過", self.line(out, path))
        self.assertEqual(out.splitlines()[-1], "結果：相容")

    def test_optional_field_that_is_absent_is_not_a_failure(self):
        self.write_cache()  # 沒有 five_hour 等欄位
        code, out = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("可選", self.line(out, "cachedUsageUtilization.utilization.five_hour"))

    def test_wrong_type_is_flagged_with_the_actual_type(self):
        self.write_raw_cache(lambda c: c["utilization"].update(limits={"kind": "session"}))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        line = self.line(out, LIMITS)
        self.assertIn("型別不符", line)
        self.assertIn("物件", line)
        self.assertIn("不相容", out.splitlines()[-1])

    def test_missing_required_field_is_flagged(self):
        self.write_raw_cache(lambda c: c.pop("fetchedAtMs"))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("缺少", self.line(out, "cachedUsageUtilization.fetchedAtMs"))

    def test_every_limit_item_is_checked(self):
        self.write_raw_cache(lambda c: c["utilization"]["limits"][1].pop("kind"))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("缺少", self.line(out, f"{LIMITS}[].kind"))
        self.assertIn("通過", self.line(out, f"{LIMITS}[].percent"))

    def test_optional_field_with_wrong_type_is_flagged(self):
        self.write_cache(five_hour="10%")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("型別不符", self.line(out, "cachedUsageUtilization.utilization.five_hour"))

    def test_fields_under_a_broken_parent_are_not_reported_as_missing(self):
        self.write_raw_cache(lambda c: c.update(utilization=[]))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("型別不符", self.line(out, "cachedUsageUtilization.utilization"))
        self.assertNotIn("缺少", self.line(out, f"{LIMITS}[].kind"))

    def test_usage_cache_that_is_not_an_object_is_incompatible(self):
        self.write_claude_json({"oauthAccount": {"accountUuid": "acct-1"}, "cachedUsageUtilization": None})
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("型別不符", self.line(out, "cachedUsageUtilization"))

    def test_missing_oauth_account_is_flagged(self):
        self.write_raw_cache(lambda c: None)
        data = json.loads(self.paths.claude_json.read_text(encoding="utf-8"))
        del data["oauthAccount"]
        self.write_claude_json(data)
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("缺少", self.line(out, "oauthAccount"))

    def test_required_field_inside_an_optional_object_is_checked(self):
        self.write_cache(extra_usage={"currency": "USD"}, spend={"used": None},
                         seven_day_breakdown={"rows": [{"key": "code", "percent": 10}]})
        code, out = self.run_check()
        self.assertEqual(code, 1)
        for path in ("extra_usage.is_enabled", "spend.enabled", "seven_day_breakdown.rows[].display_name"):
            with self.subTest(path=path):
                self.assertIn("缺少", self.line(out, f"cachedUsageUtilization.utilization.{path}"))

    def test_cache_the_parser_rejects_is_never_reported_compatible(self):
        # 欄位清單沒列到的依賴（這裡是 scope.model 缺 display_name）壞掉時，仍以解析層的結果為準
        self.write_raw_cache(lambda c: c["utilization"]["limits"][0].update(
            kind="weekly_scoped", scope={"model": {"id": "m"}}))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("解析層無法解析", out)
        self.assertIn("不相容", out.splitlines()[-1])

    def test_lists_unknown_fields_under_utilization(self):
        self.write_cache(brand_new_limit=limit_field(5), brand_new_flag=True,
                         five_hour=limit_field(10), amber_cistern=None)
        code, out = self.run_check()
        self.assertEqual(code, 0)  # 未知欄位只是提示，不算不相容
        unknown = out[out.index("未知欄位"):]
        limit_line = next(ln for ln in unknown.splitlines() if "brand_new_limit" in ln)
        self.assertIn("其他限額", limit_line)
        self.assertIn("brand_new_flag", unknown)
        for known in ("five_hour", "amber_cistern", "limits"):
            self.assertNotIn(known, unknown)

    def test_no_unknown_fields_says_so(self):
        self.write_cache()
        out = self.run_check()[1]
        self.assertIn("無", out[out.index("未知欄位"):].splitlines()[1])

    def test_output_has_no_account_id_or_email(self):
        self.write_cache(oauth="acct-secret-1", account_uuid="acct-secret-1")
        out = self.run_check()[1]
        self.assertNotIn("acct-secret-1", out)
        self.assertNotIn("someone@example.com", out)

    def test_does_not_write_into_the_claude_code_dir(self):
        self.write_credentials()
        self.write_cache()

        def state():
            files = [p for p in self.home.rglob("*") if p.is_file() and "appdata-from-env" not in p.parts]
            return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}
        before = state()
        self.run_check()
        self.assertEqual(state(), before)

    def test_prints_directories_and_where_they_came_from(self):
        self.write_cache()
        out = self.run_check()[1]
        self.assertIn(f"Claude Code 目錄：{self.home / '.claude'}（預設值）", out)
        self.assertIn(f"納管目錄：{self.home / '.claude-multi'}（預設值）", out)
        self.assertIn(str(self.settings_file()), out)

        by_env = self.make_dir("by-env")
        self.env["CLAUDE_CONFIG_DIR"] = str(by_env)
        (by_env / ".claude.json").write_text(json.dumps(claude_json(usage_cache())), encoding="utf-8")
        out = self.run_check()[1]
        self.assertIn(f"Claude Code 目錄：{by_env}（環境變數 CLAUDE_CONFIG_DIR）", out)
        self.assertIn(str(by_env / ".claude.json"), out)

        by_settings, managed = self.make_dir("by-settings"), self.make_dir("managed")
        self.write_settings(claudeConfigDir=str(by_settings), managedDir=str(managed))
        out = self.run_check()[1]
        self.assertIn(f"Claude Code 目錄：{by_settings}（設定檔的 claudeConfigDir）", out)
        self.assertIn(f"納管目錄：{managed}（設定檔的 managedDir）", out)

    def test_no_reading_cannot_be_checked(self):
        self.log_in()  # .claude.json 存在，但沒有 cachedUsageUtilization
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("尚無讀數", out)
        self.assertIn("Claude Code 目錄", out)  # 路徑照樣印出，方便判斷是不是讀錯位置

    def test_missing_usage_cache_file_cannot_be_checked(self):
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("找不到", out)
        self.assertIn(str(self.home / ".claude.json"), out)

    def test_half_written_file_asks_to_retry(self):
        self.write_cache()
        self.paths.claude_json.write_text('{"cachedUsageUtilization": {', encoding="utf-8")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("稍後再執行", out)


if __name__ == "__main__":
    unittest.main()
