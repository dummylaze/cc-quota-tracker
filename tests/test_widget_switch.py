"""視窗接線：右鍵選單的「切換帳號」子選單與確認對話框。視窗接真的核心與假 claude，從選單打進去，
斷言選單內容、對話框文字、假 home 裡的當前憑證，以及切換在背景執行、視窗的事件迴圈沒有被擋住。"""
import gc
import threading
import time
from dataclasses import replace
from datetime import timedelta
from unittest import mock

from cc_quota_tracker.board import SwitchOutcome, SwitchRefusal, SwitchResult
from tests.fakehome import NOW
from tests.test_credential_sync import HOME, WORK
from tests.test_layout_a import visible_texts
from tests.test_switch import SwitchTestCase
from tests.test_widget import WidgetTestCase

TITLE = "切換帳號"
PLACEHOLDER = "（沒有可切換的帳號）"


class WidgetSwitchTestCase(SwitchTestCase, WidgetTestCase):
    """當前憑證帳號是 work，待命帳號是 home；視窗與測試共用同一個核心。"""

    def setUp(self):
        super().setUp()
        # 背景執行緒配置物件時可能觸發垃圾回收，順手回收前面測試留下的 Tk 變數：Tk 物件只能在主執行緒釋放，
        # 否則整個程序會被 Tcl_AsyncDelete 中止。測試期間先停掉自動回收，收尾時在主執行緒補回收
        gc.collect()
        gc.disable()
        self.addCleanup(gc.collect)
        self.addCleanup(gc.enable)
        self.addCleanup(self.wait_for_switch)
        self.widget.refresh()

    def wait_for_switch(self):
        thread = self.widget._switch_thread
        if thread is not None:
            thread.join(20)

    def drop_in(self, label, refresh):
        """像使用者那樣直接把一份憑證檔放進納管目錄：沒有帳號資訊，當前憑證不動。"""
        keep = self.current().read_bytes()
        self.write_credentials(refresh=refresh)
        data = self.current().read_bytes()
        self.current().write_bytes(keep)
        self.snapshot(label).write_bytes(data)

    def menu_index(self, label):
        menu = self.widget._menu
        return next(i for i in range(menu.index("end") + 1) if menu.type(i) != "separator"
                    and menu.entrycget(i, "label") == label)

    def submenu(self, label=TITLE):
        return self.root.nametowidget(self.widget._menu.entrycget(self.menu_index(label), "menu"))

    def rows(self, label=TITLE):
        """子選單的每一列：(標籤, 可不可點)。"""
        sub = self.submenu(label)
        return [(sub.entrycget(i, "label"), sub.entrycget(i, "state") != "disabled")
                for i in range(sub.index("end") + 1) if sub.type(i) != "separator"]

    def choose(self, label, submenu=TITLE):
        sub = self.submenu(submenu)
        index = next(i for i in range(sub.index("end") + 1) if sub.type(i) != "separator"
                     and sub.entrycget(i, "label") == label)
        sub.invoke(index)

    def finish(self):
        """讓事件迴圈跑到背景的切換結束；超時就是切換卡住。"""
        deadline = time.monotonic() + 20
        while self.widget.switching:
            self.assertLess(time.monotonic(), deadline, "切換沒有結束")
            self.root.update()
            time.sleep(0.02)

    def confirm(self, answer=True):
        """換掉確認對話框，回傳那個替身：呼叫它的參數就是對話框的標題與內文。"""
        patcher = mock.patch("cc_quota_tracker.widget.messagebox.askyesno", return_value=answer)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def errors(self):
        patcher = mock.patch("cc_quota_tracker.widget.messagebox.showerror")
        self.addCleanup(patcher.stop)
        return patcher.start()

    def with_query_status(self, **status):
        """看板的查詢狀態換成指定的：其餘照核心的看板。"""
        real = self.core.poll
        self.counting.poll = lambda: replace(real(), usage_query=replace(real().usage_query, **status))
        self.widget.refresh()


class MenuTest(WidgetSwitchTestCase):
    def test_the_submenu_lists_the_standby_accounts_by_label(self):
        self.assertEqual(self.rows(), [("home", True)])

    def test_the_standby_accounts_come_in_order_and_the_active_one_is_not_listed(self):
        self.manage("away", "rt-a", "acct-a", NOW + timedelta(days=25))
        self.manage("work", "rt-w", "acct-w", WORK)  # 回到 work：away 與 home 是待命帳號
        self.widget.refresh()
        self.assertEqual(self.rows(), [("away", True), ("home", True)])

    def test_watch_only_accounts_are_listed_but_cannot_be_chosen(self):
        self.drop_in("dropped", "rt-d")  # 直接放進納管目錄：沒有帳號資訊
        self.manage("expired", "rt-e", "acct-e", NOW + timedelta(days=1))
        self.clock.advance(days=2)
        self.manage("work", "rt-w2", "acct-w", self.clock.now + timedelta(days=30))
        self.widget.refresh()
        rows = dict(self.rows())
        self.assertEqual((rows["dropped"], rows["expired"]), (False, False))

    def test_without_a_switchable_account_the_submenu_still_opens_with_a_greyed_placeholder(self):
        self.core.remove("home")
        self.widget.refresh()
        self.assertEqual(self.rows(), [(PLACEHOLDER, False)])
        self.drop_in("dropped", "rt-d")
        self.widget.refresh()
        self.assertEqual(self.rows(), [("dropped", False), (PLACEHOLDER, False)])

    def test_the_menu_item_and_rows_follow_the_language(self):
        self.widget.set_preference("language", "en")
        self.assertEqual(self.rows("Switch account"), [("home", True)])
        self.core.remove("home")
        self.widget.refresh()
        self.assertEqual(self.rows("Switch account"), [("(No account to switch to)", False)])

    def test_every_layout_shares_the_same_menu_and_cards_have_no_switch_entry(self):
        for layout in ("cards", "table", "ring"):
            for mode in ("compact", "expanded"):
                self.widget.set_preference("layout", layout)
                self.widget.set_preference("mode", mode)
                self.assertEqual(self.rows(), [("home", True)], (layout, mode))
                shown = visible_texts(self.widget.canvas)
                self.assertFalse([t for t in shown if t in (TITLE, "切換", "Switch", "Switch account")], (layout, mode))

    def test_the_submenu_is_greyed_while_a_query_is_in_progress(self):
        entry = self.menu_index(TITLE)
        self.assertEqual(self.widget._menu.entrycget(entry, "state"), "normal")
        self.with_query_status(in_progress=True)
        self.assertEqual(self.widget._menu.entrycget(entry, "state"), "disabled")
        self.with_query_status(in_progress=False, cooling_down=True)  # 冷卻中不擋：切換的查詢本來就不啟動冷卻
        self.assertEqual(self.widget._menu.entrycget(entry, "state"), "normal")

    def test_polling_leaves_the_submenu_alone_while_nothing_changed(self):
        # Windows 上改動彈出中的選單項會重建原生選單：展開中的子選單被收掉、整個選單跟著關閉
        sub = self.submenu()
        with mock.patch.object(sub, "delete", wraps=sub.delete) as delete, \
                mock.patch.object(self.widget._menu, "entryconfigure",
                                  wraps=self.widget._menu.entryconfigure) as configure:
            self.widget.refresh()
            self.widget.refresh()
        self.assertEqual((delete.call_count, configure.call_count), (0, 0))

    def test_a_new_standby_account_shows_up_on_the_next_round(self):
        self.manage("away", "rt-a", "acct-a", NOW + timedelta(days=25))
        self.manage("work", "rt-w", "acct-w", WORK)
        self.assertEqual(self.rows(), [("home", True)])
        self.widget.refresh()
        self.assertEqual(self.rows(), [("away", True), ("home", True)])


class ConfirmDialogTest(WidgetSwitchTestCase):
    def message(self, **kw):
        ask = self.confirm(**kw)
        self.choose("home")
        self.finish()
        ask.assert_called_once()
        self.assertEqual(ask.call_args.args[0], TITLE)
        return ask.call_args.args[1]

    def test_the_dialog_names_the_target_and_its_snapshot_expiry_and_the_consequence_for_a_watched_account(self):
        message = self.message()
        paragraphs = message.split("\n\n")
        self.assertEqual(paragraphs[0], "切換到「home」？")
        self.assertRegex(paragraphs[1], r"^憑證快照 20天0小時後到期（\d\d-\d\d \d\d:\d\d）$")
        self.assertEqual(paragraphs[2], "目前帳號「work」是監看帳號：切走之前，會先同步憑證至快照。")
        self.assertEqual(len(paragraphs), 3)

    def test_an_unwatched_current_account_gets_the_pre_switch_credential_consequence(self):
        self.log_in_at("rt-x", "acct-x", NOW + timedelta(days=5))
        self.widget.refresh()
        paragraphs = self.message().split("\n\n")
        self.assertEqual(paragraphs[2], "目前帳號是未監看帳號：只會存成切換前憑證，且只留最新一份。")
        self.assertEqual(len(paragraphs), 3)

    def test_an_invalid_snapshot_of_the_current_account_adds_one_line(self):
        self.log_in_at("rt-w2", "acct-w", WORK + timedelta(days=1))  # 同一個帳號重新登入：快照跟新登入不是同一次
        self.widget.refresh()
        paragraphs = self.message().split("\n\n")
        self.assertEqual(paragraphs[-1], "目前帳號快照已失效；用「還原上一次切換」，或在 Claude Code 登入後再重新納管。")
        self.assertEqual(len(paragraphs), 4)

    def test_the_dialog_shows_no_usage_numbers(self):
        self.assertNotRegex(self.message(), r"%|額度|讀數")

    def test_the_dialog_follows_the_language(self):
        self.widget.set_preference("language", "en")
        ask = self.confirm()
        self.choose("home", "Switch account")
        self.finish()
        self.assertEqual(ask.call_args.args[0], "Switch account")
        paragraphs = ask.call_args.args[1].split("\n\n")
        self.assertEqual(paragraphs[0], "Switch to \"home\"?")
        self.assertRegex(paragraphs[1], r"^Credential snapshot expires in 20d 0h \(")
        self.assertEqual(paragraphs[2], "The current account \"work\" is a watched account: its credential is synced "
                                        "to its snapshot before switching.")

    def test_there_is_a_single_dialog_and_no_delay(self):
        ask = self.confirm()
        started = time.monotonic()
        self.choose("home")
        self.assertLess(time.monotonic() - started, 1)  # 確認之後立刻開始，沒有倒數
        self.finish()
        self.assertEqual(ask.call_count, 1)

    def test_declining_changes_nothing(self):
        before = self.untouched()
        self.confirm(False)
        self.choose("home")
        self.assertFalse(self.widget.switching)
        self.assertEqual(self.untouched(), before)
        self.assertEqual(self.starts(), 0)


class SwitchRunTest(WidgetSwitchTestCase):
    def slow_switch(self):
        """核心的 switch 卡在這裡，直到測試放行；回傳放行用的事件。"""
        release, real = threading.Event(), self.core.switch

        def slow(label):
            release.wait(10)
            return real(label)
        self.counting.switch = slow
        return release

    def test_confirming_switches_in_the_background_without_blocking_the_event_loop(self):
        self.confirm()
        release = self.slow_switch()
        self.addCleanup(release.set)
        before = self.untouched()
        self.choose("home")  # 切換卡住了，選單項照樣返回：事件迴圈沒有被擋住
        self.assertTrue(self.widget.switching)
        self.root.update()
        self.assertEqual(self.untouched(), before)
        release.set()
        self.finish()
        self.assertEqual(self.current().read_bytes(), self.snapshot("home").read_bytes())
        self.assertEqual(self.oauth_account()["accountUuid"], "acct-h")

    def test_the_first_row_is_the_new_account_after_it_succeeds_and_nothing_is_shown(self):
        self.confirm()
        errors = self.errors()
        with mock.patch("cc_quota_tracker.widget.messagebox.showinfo") as info:
            self.choose("home")
            self.finish()
        self.assertEqual(self.counting.core.poll().cards[0].account_key, "claude:home")
        self.assertEqual(self.rows(), [("work", True)])  # 切換完成立刻 poll 過一次，子選單已經換成新的待命帳號
        self.assertFalse(errors.called or info.called)

    def test_the_board_is_not_polled_while_switching(self):
        self.confirm()
        release = self.slow_switch()
        self.addCleanup(release.set)
        self.choose("home")
        polls = self.counting.polls
        for _ in range(5):
            self.widget.refresh()  # 核心不是執行緒安全的：切換進行中不能同時 poll
        self.assertEqual(self.counting.polls, polls)
        self.assertEqual(len(self.pending_after()), 2)  # 一個是 poll 的排程，另一個是等切換結束
        release.set()
        self.finish()
        self.assertGreater(self.counting.polls, polls)

    def test_the_submenu_is_greyed_and_new_queries_are_not_started_while_switching(self):
        self.confirm()
        release = self.slow_switch()
        self.addCleanup(release.set)
        self.choose("home")
        self.assertEqual(self.widget._menu.entrycget(self.menu_index(TITLE), "state"), "disabled")
        started = []
        self.counting.start_query = lambda: started.append(True)
        self.widget.query_usage()
        self.assertEqual(started, [])
        release.set()
        self.finish()
        self.assertEqual(self.widget._menu.entrycget(self.menu_index(TITLE), "state"), "normal")

    def test_the_query_entry_is_greyed_while_switching(self):
        self.confirm()
        release = self.slow_switch()
        self.addCleanup(release.set)
        self.choose("home")
        self.assertEqual(self.widget._menu.entrycget(self.menu_index("查詢額度"), "state"), "disabled")
        release.set()
        self.finish()
        self.assertEqual(self.widget._menu.entrycget(self.menu_index("查詢額度"), "state"), "normal")

    def test_the_other_actions_that_use_the_core_do_nothing_while_switching(self):
        self.confirm()
        release = self.slow_switch()
        self.addCleanup(release.set)
        self.choose("home")
        before = sorted(p.name for p in (self.home / ".claude-multi").iterdir())
        with mock.patch("cc_quota_tracker.widget.simpledialog.askstring", return_value="extra") as ask, \
                mock.patch("cc_quota_tracker.widget.filedialog.askopenfilename", return_value="x.json") as pick:
            self.widget.add_current_account()
            self.widget.import_credential_file()
        self.widget.dismiss_untightened_warning()
        self.assertFalse(ask.called or pick.called)
        self.assertEqual(sorted(p.name for p in (self.home / ".claude-multi").iterdir()), before)
        release.set()
        self.finish()

    def test_a_query_that_starts_while_the_dialog_is_open_stops_the_switch(self):
        def answer(*args, **kwargs):
            self.with_query_status(in_progress=True)  # 對話框開著時，自動查詢啟動了
            return True
        self.confirm().side_effect = answer
        before = self.untouched()
        self.choose("home")
        self.assertFalse(self.widget.switching)
        self.assertEqual(self.untouched(), before)
        self.assertEqual(self.starts(), 0)

    def test_closing_the_window_cancels_the_wait_for_the_switch(self):
        self.confirm()
        release = self.slow_switch()
        self.addCleanup(release.set)
        self.choose("home")
        self.widget.close()
        self.assertEqual(self.pending_after(), ())
        release.set()

    def test_a_second_choice_while_switching_is_ignored(self):
        ask = self.confirm()
        release = self.slow_switch()
        self.addCleanup(release.set)
        self.choose("home")
        self.widget.switch_to("home")
        self.assertEqual(ask.call_count, 1)
        release.set()
        self.finish()

    def test_choosing_while_a_query_is_in_progress_does_nothing(self):
        self.with_query_status(in_progress=True)
        ask = self.confirm()
        self.widget.switch_to("home")  # 過期看板的漏網之魚：選單項這時本來就不可點
        self.assertFalse(ask.called or self.widget.switching)


class ResultTest(WidgetSwitchTestCase):
    def test_a_refusal_shows_the_reason_and_writes_nothing(self):
        self.confirm()
        errors = self.errors()
        self.clock.advance(days=21)  # 看板還停在 21 天前：選單項看起來能切，核心重新判斷時 home 已經過期
        before = self.untouched()
        self.choose("home")
        self.finish()
        errors.assert_called_once()
        self.assertEqual(errors.call_args.args[1],
                         "「home」是僅監看帳號（已過期），不能切換過去：在 Claude Code 登入這個帳號後重新納管")
        self.assertEqual(self.untouched(), before)

    def test_the_refusal_follows_the_language(self):
        self.widget.set_preference("language", "en")
        self.confirm()
        errors = self.errors()
        self.counting.switch = lambda label: SwitchResult(SwitchOutcome.REFUSED, SwitchRefusal.SYNC_FAILED)
        self.choose("home", "Switch account")
        self.finish()
        self.assertEqual(errors.call_args.args[1],
                         "Couldn't sync the current account's credential back to its snapshot, so nothing was "
                         "switched. Try again later.")

    def test_a_write_that_stopped_halfway_is_reported_too(self):
        self.confirm()
        errors = self.errors()
        self.counting.switch = lambda label: SwitchResult(SwitchOutcome.WRITE_FAILED)
        self.choose("home")
        self.finish()
        self.assertIn("「home」", errors.call_args.args[1])
        self.assertIn("兩者目前不一致", errors.call_args.args[1])

    def test_old_account_query_failure_is_not_reported(self):
        self.confirm()
        errors = self.errors()
        self.counting.switch = lambda label: SwitchResult(SwitchOutcome.SWITCHED, old_account_query_failed=True)
        self.choose("home")
        self.finish()
        self.assertFalse(errors.called)

    def test_an_exception_in_the_background_switch_is_reported_and_the_window_recovers(self):
        self.confirm()
        errors = self.errors()

        def boom(label):
            raise RuntimeError("壞了")
        self.counting.switch = boom
        self.choose("home")
        self.finish()
        errors.assert_called_once()
        self.assertFalse(self.widget.switching)
        self.assertEqual(self.widget._menu.entrycget(self.menu_index(TITLE), "state"), "normal")
