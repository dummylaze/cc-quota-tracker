"""停止更新：每輪 poll 沒有完成（重試寫回設定檔、poll、渲染任一步丟出例外）時 refresh() 吞下例外、照樣排下一輪；
連續 12 輪沒有完成才亮橫幅，恢復完成的那一輪就熄滅。縫：把核心的 poll 換成會丟例外的替身。"""
import unittest
from unittest import mock

from cc_quota_tracker.fmt import absolute
from cc_quota_tracker.widget import STALL_ROUNDS
from tests.test_layout_a import visible_texts
from tests.test_widget import WidgetTestCase

_ZH = "看板已停止更新：讀取時發生錯誤"
_EN = "Board stopped updating: an error occurred while reading"


class StalledTestCase(WidgetTestCase):
    def setUp(self):
        super().setUp()
        self.working_poll = self.counting.poll

    def fail_rounds(self, rounds, error=RuntimeError("boom")):
        """poll 改成丟例外，再跑 rounds 輪；每輪之間時鐘前進 5 秒，與實際排程相同。"""
        def broken():
            raise error
        self.counting.poll = broken
        for _ in range(rounds):
            self.clock.advance(seconds=5)
            self.widget.refresh()

    def recover(self):
        self.counting.poll = self.working_poll
        self.widget.refresh()

    def banner(self):
        """停止更新那一句。各橫幅接在同一段文字裡，它排在最後，所以從它開頭切到段尾。"""
        return [t[t.index(prefix):] for t in visible_texts(self.widget.canvas)
                for prefix in (_ZH, _EN) if prefix in t]


class StalledTest(StalledTestCase):
    def test_threshold_is_twelve_rounds(self):
        self.assertEqual(STALL_ROUNDS, 12)

    def test_a_failing_poll_does_not_escape_and_keeps_a_single_pending_after(self):
        self.fail_rounds(3)
        self.assertEqual(len(self.pending_after()), 1)

    def test_banner_lights_on_the_twelfth_round_with_the_last_completed_time(self):
        done = self.clock.now
        self.fail_rounds(STALL_ROUNDS - 1)
        self.assertEqual(self.banner(), [])
        self.clock.advance(hours=2)
        self.fail_rounds(1)
        when = absolute(done, self.clock.now)
        self.assertEqual(self.banner(), [f"{_ZH}；最後一次成功的讀數：（{when}，2 小時前）"])

    def test_shown_after_the_other_banners(self):
        self.fail_rounds(STALL_ROUNDS)
        block = next(t for t in visible_texts(self.widget.canvas) if _ZH in t)
        self.assertIn("預設位置找不到 Claude Code 的額度快取", block)  # 這個測試環境本來就亮著的橫幅
        self.assertTrue(block.endswith(self.banner()[0]))
        self.assertLess(block.index("預設位置找不到"), block.index(_ZH))

    def test_age_grows_while_stalled(self):
        self.fail_rounds(STALL_ROUNDS)
        self.assertIn("1 分鐘前", self.banner()[0])
        self.clock.advance(minutes=10)
        self.fail_rounds(1)
        self.assertIn("11 分鐘前", self.banner()[0])

    def test_recovering_clears_the_banner_and_the_count_starts_over(self):
        self.fail_rounds(STALL_ROUNDS)
        self.recover()
        self.assertEqual(self.banner(), [])
        self.fail_rounds(STALL_ROUNDS - 1)
        self.assertEqual(self.banner(), [])
        self.fail_rounds(1)
        self.assertEqual(len(self.banner()), 1)

    def test_changing_a_preference_while_stalled_keeps_the_banner(self):
        self.fail_rounds(STALL_ROUNDS)
        self.widget.set_preference("mode", "expanded")
        self.assertEqual(len(self.banner()), 1)

    def test_a_failing_settings_retry_counts_as_not_completed(self):
        self.widget._unwritten["opacity"] = 70
        with mock.patch("cc_quota_tracker.widget.write_preference", side_effect=ValueError("boom")):
            for _ in range(STALL_ROUNDS):
                self.widget.refresh()
        self.assertEqual(len(self.banner()), 1)
        self.assertEqual(len(self.pending_after()), 1)

    def test_a_failing_render_counts_and_the_banner_is_still_tried(self):
        render, stalled = self.widget.layout.render, []

        def broken(board, theme, expanded=False, lang="zh-TW", stalled_text=None):
            if stalled_text is None:
                raise RuntimeError("boom")
            stalled.append(stalled_text)
            render(board, theme, expanded, lang, stalled_text)
        self.widget.layout.render = broken
        for _ in range(STALL_ROUNDS - 1):
            self.widget.refresh()
        self.assertEqual(stalled, [])
        self.widget.refresh()
        self.assertEqual(len(stalled), 1)
        self.assertEqual(len(self.banner()), 1)

    def test_a_render_that_fails_even_for_the_banner_does_not_escape(self):
        self.widget.layout.render = mock.Mock(side_effect=RuntimeError("boom"))
        for _ in range(STALL_ROUNDS + 1):
            self.widget.refresh()
        self.assertEqual(len(self.pending_after()), 1)

    def test_query_usage_and_the_auto_query_toggle_do_not_raise(self):
        self.fail_rounds(1)
        with mock.patch.object(self.counting.core, "start_query", return_value=True):
            self.widget.query_usage()
        self.widget._toggle_auto_query()
        self.assertEqual(len(self.pending_after()), 1)


class NeverCompletedTest(StalledTestCase):
    def open_widget(self):
        with mock.patch.object(self.core, "poll", side_effect=RuntimeError("boom")):
            super().open_widget()  # 啟動的那一輪就沒有完成

    def test_a_widget_that_never_completed_shows_the_no_reading_version(self):
        self.fail_rounds(STALL_ROUNDS - 2)
        self.assertEqual(self.banner(), [])
        self.fail_rounds(1)
        self.assertEqual(self.banner(), [f"{_ZH}；目前沒有成功的讀數"])

    def test_every_layout_mode_and_language_shows_the_no_reading_version(self):
        """沒有看板時偏好只能從選單改：停止更新期間換版面、模式、語系，橫幅都要畫得出來。"""
        self.fail_rounds(STALL_ROUNDS - 1)
        for layout in ("cards", "table", "ring"):
            for mode in ("compact", "expanded"):
                for language, expected in (("zh-TW", f"{_ZH}；目前沒有成功的讀數"),
                                           ("en", f"{_EN}; there is no successful reading yet")):
                    with self.subTest(layout=layout, mode=mode, language=language):
                        self.widget.set_preference("layout", layout)
                        self.widget.set_preference("mode", mode)
                        self.widget.set_preference("language", language)
                        self.assertEqual(self.banner(), [expected])


class LayoutsAndLanguagesTest(StalledTestCase):
    def test_every_layout_shows_the_banner_in_both_languages(self):
        for layout in ("cards", "table", "ring"):
            for language, expected in (("zh-TW", f"{_ZH}；最後一次成功的讀數：（"),
                                       ("en", f"{_EN}; last successful reading: (")):
                with self.subTest(layout=layout, language=language):
                    self.recover()
                    self.widget.set_preference("layout", layout)
                    self.widget.set_preference("language", language)
                    self.fail_rounds(STALL_ROUNDS)
                    banner = self.banner()
                    self.assertEqual(len(banner), 1)
                    self.assertTrue(banner[0].startswith(expected), banner[0])


if __name__ == "__main__":
    unittest.main()
