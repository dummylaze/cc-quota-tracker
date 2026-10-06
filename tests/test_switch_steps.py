"""切換的進度回報：核心在每個步驟開始之前回報一次，視窗的圖層靠它顯示目前進行到哪一步。
從核心的 switch 打進去，在回報的當下看假 home 的檔案，確認「回報」與「實際做到哪」一致。"""
from cc_quota_tracker.board import SwitchOutcome, SwitchStep
from tests.test_switch_queries import QueriedSwitchTestCase


class SwitchStepsTest(QueriedSwitchTestCase):
    def switch(self, label="home"):
        steps = []
        result = self.core.switch(label, on_step=steps.append)
        return result, steps

    def test_all_four_steps_are_reported_in_order_when_the_old_account_is_queried(self):
        self.lagging_work()
        result, steps = self.switch()
        self.assertIs(result.outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(steps, [SwitchStep.SYNC, SwitchStep.QUERY_OLD, SwitchStep.WRITE, SwitchStep.QUERY_NEW])

    def test_a_skipped_old_account_query_is_not_reported(self):
        self.work_reads()  # 讀數沒落後：跳過舊帳號的查詢
        result, steps = self.switch()
        self.assertIs(result.outcome, SwitchOutcome.SWITCHED)
        self.assertEqual(steps, [SwitchStep.SYNC, SwitchStep.WRITE, SwitchStep.QUERY_NEW])

    def test_a_step_is_reported_before_its_work_starts(self):
        self.lagging_work()
        work, home = self.snapshot("work").read_bytes(), self.snapshot("home").read_bytes()
        seen = {}

        def on_step(step):
            seen[step] = self.current().read_bytes(), self.starts()
        self.core.switch("home", on_step=on_step)
        self.assertEqual(seen, {SwitchStep.SYNC: (work, 0), SwitchStep.QUERY_OLD: (work, 0),
                                SwitchStep.WRITE: (work, 1),   # 寫入之前：舊帳號查過了、當前憑證還是舊的
                                SwitchStep.QUERY_NEW: (home, 1)})  # 查新帳號之前：憑證已經換成新帳號的

    def test_a_failed_verification_still_reported_the_last_step(self):
        self.work_reads()
        self.queries_write_nothing()
        result, steps = self.switch()
        self.assertIs(result.outcome, SwitchOutcome.VERIFY_FAILED)
        self.assertEqual(steps[-1], SwitchStep.QUERY_NEW)

    def test_a_refusal_before_anything_happens_reports_no_step(self):
        result, steps = self.switch("nobody")
        self.assertIs(result.outcome, SwitchOutcome.REFUSED)
        self.assertEqual(steps, [])

    def test_switching_without_a_callback_still_works(self):
        self.assertIs(self.core.switch("home").outcome, SwitchOutcome.SWITCHED)

