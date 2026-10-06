"""視窗接線：右鍵選單的「切換帳號」子選單與確認對話框。視窗接真的核心與假 claude，從選單打進去，
斷言選單內容、對話框文字、假 home 裡的當前憑證，以及切換在背景執行、視窗的事件迴圈沒有被擋住。"""
import gc
import threading
import time
from dataclasses import replace
from datetime import timedelta
from unittest import mock

from cc_quota_tracker.board import SwitchOutcome, SwitchRefusal, SwitchResult, SwitchStep
from cc_quota_tracker.entry import CLICKABLE_TAG
from cc_quota_tracker.tokens import THEMES
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

        def slow(label, on_step=None):
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
        self.counting.switch = lambda label, on_step=None: SwitchResult(SwitchOutcome.REFUSED,
                                                                        SwitchRefusal.SYNC_FAILED)
        self.choose("home", "Switch account")
        self.finish()
        self.assertEqual(errors.call_args.args[1],
                         "Couldn't sync the current account's credential back to its snapshot, so nothing was "
                         "switched. Try again later.")

    def test_a_write_that_stopped_halfway_is_reported_too(self):
        self.confirm()
        errors = self.errors()
        self.counting.switch = lambda label, on_step=None: SwitchResult(SwitchOutcome.WRITE_FAILED)
        self.choose("home")
        self.finish()
        self.assertIn("「home」", errors.call_args.args[1])
        self.assertIn("兩者目前不一致", errors.call_args.args[1])

    def test_old_account_query_failure_is_not_reported(self):
        self.confirm()
        errors = self.errors()
        self.counting.switch = lambda label, on_step=None: SwitchResult(SwitchOutcome.SWITCHED,
                                                                        old_account_query_failed=True)
        self.choose("home")
        self.finish()
        self.assertFalse(errors.called)

    def test_an_exception_in_the_background_switch_is_reported_and_the_window_recovers(self):
        self.confirm()
        errors = self.errors()

        def boom(label, on_step=None):
            raise RuntimeError("壞了")
        self.counting.switch = boom
        self.choose("home")
        self.finish()
        errors.assert_called_once()
        self.assertFalse(self.widget.switching)
        self.assertEqual(self.widget._menu.entrycget(self.menu_index(TITLE), "state"), "normal")


OVERLAY = "switch-overlay"


class OverlayTest(WidgetSwitchTestCase):
    """切換中蓋在整個視窗上的半透明圖層：右鍵打不開、可以拖動、沒有取消的入口，展開模式顯示目前步驟。"""

    def gated_switch(self, *steps, result=None):
        """核心的 switch 依序回報 steps，每回報一步就等測試放行（gate.release()），全部放行後才做真的切換；
        result 給了就回傳它、不真的切換（要在同一個測試裡切好幾次時用）。"""
        gate, real = threading.Semaphore(0), self.core.switch

        def gated(label, on_step=None):
            for step in steps:
                on_step(step)
                gate.acquire(timeout=10)
            return result or real(label)
        self.counting.switch = gated
        self.addCleanup(lambda: [gate.release() for _ in steps])
        return gate

    def overlay(self):
        return self.widget.canvas.find_withtag(OVERLAY)

    def overlay_texts(self):
        cv = self.widget.canvas
        return [cv.itemcget(i, "text") for i in self.overlay() if cv.type(i) == "text"]

    def veil(self):
        return next(i for i in self.overlay() if self.widget.canvas.type(i) == "polygon")

    def pump(self, until):
        """讓事件迴圈跑到條件成立；超時就是畫面沒跟上。"""
        deadline = time.monotonic() + 10
        while not until():
            self.assertLess(time.monotonic(), deadline, "畫面沒有跟上")
            self.root.update()
            time.sleep(0.02)

    def begin(self, *steps, mode="expanded", result=None):
        """選了「home」並確認，核心卡在第一個步驟；回傳放行用的 gate。"""
        self.widget.set_preference("mode", mode)
        self.confirm()
        gate = self.gated_switch(*steps, result=result)
        self.choose("home", "Switch account" if self.widget._lang == "en" else TITLE)
        return gate

    def show_window(self):
        """真的把視窗顯示出來（移到螢幕外），滑鼠事件才會送到它。"""
        self.root.geometry("+-3000+-3000")
        self.root.deiconify()
        self.root.update()
        self.addCleanup(self.root.update)

    def right_click(self):
        self.widget.canvas.event_generate("<Button-3>", x=30, y=30, rootx=130, rooty=130)

    def test_the_overlay_covers_the_whole_window_from_confirmation_until_the_switch_ends(self):
        self.assertEqual(self.overlay(), ())
        gate = self.begin(SwitchStep.SYNC)
        self.assertTrue(self.overlay())
        cv = self.widget.canvas
        width, height = cv.winfo_reqwidth(), cv.winfo_reqheight()
        for x, y in ((width // 2, height // 2), (20, 20), (width - 20, 20), (20, height - 20),
                     (width - 20, height - 20)):
            self.assertIn(OVERLAY, cv.gettags(cv.find_overlapping(x, y, x, y)[-1]), (x, y))  # 最上面的就是圖層
        gate.release()
        self.finish()
        self.assertEqual(self.overlay(), ())

    def test_the_overlay_is_translucent_not_solid(self):
        self.begin(SwitchStep.SYNC)
        self.assertTrue(self.widget.canvas.itemcget(self.veil(), "stipple"))  # 點陣填色：底下的內容隱約可見

    def test_the_overlay_follows_the_theme(self):
        self.widget.set_preference("theme", "dark")
        self.begin(SwitchStep.SYNC)
        self.assertEqual(self.widget.canvas.itemcget(self.veil(), "fill"), THEMES["dark"]["panel"])

    def test_the_overlay_goes_away_when_the_switch_is_refused_fails_to_verify_or_blows_up(self):
        for result in (SwitchResult(SwitchOutcome.REFUSED, SwitchRefusal.SYNC_FAILED),
                       SwitchResult(SwitchOutcome.VERIFY_FAILED),
                       SwitchResult(SwitchOutcome.WRITE_FAILED),
                       RuntimeError("壞了")):
            self.confirm()
            self.errors()
            release = threading.Event()

            def outcome(label, on_step=None, result=result):
                release.wait(10)
                if isinstance(result, Exception):
                    raise result
                return result
            self.counting.switch = outcome
            self.choose("home")
            self.assertTrue(self.overlay(), result)
            release.set()
            self.finish()
            self.assertEqual(self.overlay(), (), result)

    def test_the_context_menu_does_not_open_while_switching(self):
        self.show_window()
        with mock.patch.object(self.widget._menu, "tk_popup") as popup:
            self.right_click()
            self.assertEqual(popup.call_count, 1)  # 沒在切換時照常打得開
            gate = self.begin(SwitchStep.SYNC)
            self.right_click()
            self.assertEqual(popup.call_count, 1)
            gate.release()
            self.finish()
            self.right_click()
            self.assertEqual(popup.call_count, 2)  # 結束之後又打得開

    def test_the_window_can_still_be_dragged_while_switching(self):
        self.show_window()
        self.begin(SwitchStep.SYNC)
        cv = self.widget.canvas
        before = self.root.geometry().split("+", 1)[1]
        cv.event_generate("<ButtonPress-1>", x=30, y=30, rootx=330, rooty=330)
        cv.event_generate("<B1-Motion>", x=80, y=70, rootx=380, rooty=370, state=0x100)
        self.assertNotEqual(self.root.geometry().split("+", 1)[1], before)

    def test_there_is_no_way_to_cancel(self):
        self.begin(SwitchStep.SYNC)
        self.assertFalse([i for i in self.overlay() if CLICKABLE_TAG in self.widget.canvas.gettags(i)])
        words = ("取消", "Cancel", "cancel")
        self.assertFalse([t for t in self.overlay_texts() + self.widget.menu_labels() if any(w in t for w in words)])

    def test_expanded_mode_shows_each_step_as_it_is_reached(self):
        gate = self.begin(*SwitchStep)
        for shown in ("同步目前帳號的憑證…", "查詢舊帳號的額度…", "寫入「home」的憑證…", "查詢新帳號的額度…"):
            self.pump(lambda: self.overlay_texts() == [shown])
            self.assertIn(shown, visible_texts(self.widget.canvas))
            gate.release()
        self.finish()
        self.assertEqual(self.overlay(), ())

    def test_a_step_that_is_not_reported_is_not_shown(self):
        gate = self.begin(SwitchStep.SYNC, SwitchStep.WRITE)  # 舊帳號的查詢被跳過
        shown = []
        for _ in range(2):
            self.pump(lambda: self.overlay_texts() and self.overlay_texts() != shown[-1:])
            shown.append(self.overlay_texts()[0])
            gate.release()
        self.assertEqual(shown, ["同步目前帳號的憑證…", "寫入「home」的憑證…"])
        self.finish()

    def test_compact_mode_covers_the_window_but_shows_no_step(self):
        gate = self.begin(SwitchStep.SYNC, mode="compact")
        for _ in range(5):
            self.root.update()
            time.sleep(0.12)  # 讓背景的回報有機會被視窗收走
        self.assertTrue(self.overlay())
        self.assertEqual(self.overlay_texts(), [])
        gate.release()
        self.finish()

    def test_toggling_the_mode_during_the_switch_adds_or_removes_the_step_text(self):
        gate = self.begin(SwitchStep.SYNC)
        self.pump(lambda: self.overlay_texts())
        self.widget.toggle_mode()
        self.assertEqual(self.overlay_texts(), [])
        self.assertTrue(self.overlay())
        self.widget.toggle_mode()
        self.assertEqual(self.overlay_texts(), ["同步目前帳號的憑證…"])
        cv = self.widget.canvas
        self.assertIn(OVERLAY, cv.gettags(cv.find_all()[-1]))  # 重畫版面之後，圖層仍在最上面
        gate.release()
        self.finish()

    def test_the_steps_follow_the_language(self):
        self.widget.set_preference("language", "en")
        gate = self.begin(*SwitchStep)
        for shown in ("Syncing the current credential…", "Querying usage for the old account…",
                      'Writing the credential of "home"…', "Querying usage for the new account…"):
            self.pump(lambda: self.overlay_texts() == [shown])
            gate.release()
        self.finish()

    def test_every_layout_gets_the_overlay_on_top(self):
        for layout in ("cards", "table", "ring"):
            self.widget.set_preference("layout", layout)
            gate = self.begin(SwitchStep.SYNC, result=SwitchResult(SwitchOutcome.SWITCHED))
            self.pump(lambda: self.overlay_texts())
            cv = self.widget.canvas
            self.assertIn(OVERLAY, cv.gettags(cv.find_all()[-1]), layout)
            gate.release()
            self.finish()
            self.assertEqual(self.overlay(), (), layout)

    def test_the_overlay_goes_away_even_when_the_round_after_the_switch_fails(self):
        gate = self.begin(SwitchStep.SYNC, result=SwitchResult(SwitchOutcome.SWITCHED))

        def boom():
            raise RuntimeError("壞了")
        self.counting.poll = boom  # 切換結束後那一輪 poll 出錯：_apply 到不了，圖層要靠結束時的那一次拿掉
        gate.release()
        self.finish()
        self.assertEqual(self.overlay(), ())

    def test_changing_the_theme_language_or_layout_during_the_switch_redraws_the_overlay(self):
        gate = self.begin(SwitchStep.SYNC)
        self.pump(lambda: self.overlay_texts())
        cv = self.widget.canvas
        self.widget.set_preference("theme", "dark")
        self.assertEqual(cv.itemcget(self.veil(), "fill"), THEMES["dark"]["panel"])
        self.widget.set_preference("language", "en")
        self.assertEqual(self.overlay_texts(), ["Syncing the current credential…"])
        for layout in ("table", "ring", "cards"):
            self.widget.set_preference("layout", layout)
            self.assertIn(OVERLAY, cv.gettags(cv.find_all()[-1]), layout)
            self.assertEqual(len(self.overlay_texts()), 1, layout)
        gate.release()
        self.finish()

    def test_clicks_land_on_the_overlay_and_not_on_the_entries_underneath(self):
        real = self.core.poll
        self.counting.poll = lambda: (lambda b: replace(b, cards=(replace(b.cards[0], lagging=True),
                                                                  *b.cards[1:])))(real())
        self.widget.refresh()
        self.show_window()
        cv = self.widget.canvas
        entry = next(i for i in cv.find_all() if cv.type(i) == "text" and cv.itemcget(i, "text") == "更新"
                     and cv.itemcget(i, "state") != "hidden")
        x1, y1, x2, y2 = cv.bbox(entry)
        x, y = int((x1 + x2) / 2), int((y1 + y2) / 2)
        cv.event_generate("<Motion>", x=x, y=y)
        self.root.update()
        self.assertIn(CLICKABLE_TAG, cv.gettags("current"))  # 沒在切換時，游標落在「更新」上
        self.begin(SwitchStep.SYNC)
        cv.event_generate("<Motion>", x=x + 1, y=y)
        self.root.update()
        self.assertIn(OVERLAY, cv.gettags("current"))  # 切換中，同一個位置落在圖層上
        self.assertNotIn(CLICKABLE_TAG, cv.gettags("current"))
