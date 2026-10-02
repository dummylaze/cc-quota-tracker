"""視窗接線：右鍵選單的「查詢額度」與卡片上的「更新」都呼叫核心的 start_query；查詢進行中縮短 poll 間隔。"""
from unittest import mock

from cc_quota_tracker.board import Board, QueryStatus
from cc_quota_tracker.widget import POLL_MS, QUERY_POLL_MS
from tests.fakehome import NOW
from tests.test_layout_a import ACTIVE
from tests.test_layout_a_query import LAGGING
from tests.test_widget import WidgetTestCase


class QueryWiringTestCase(WidgetTestCase):
    def setUp(self):
        super().setUp()
        self.started = []
        self.polls = 0
        self.accept = True
        self.counting.start_query = self.start_query
        self.show(ACTIVE)

    def start_query(self):
        self.started.append(True)
        return self.accept

    def show(self, card, **status):
        board = Board(cards=(card,), as_of=NOW, usage_query=QueryStatus(**status))
        self.counting.poll = lambda: self.poll(board)
        self.widget.refresh()

    def poll(self, board):
        self.polls += 1
        return board

    def menu_item(self, label):
        menu = self.widget._menu
        return next(i for i in range(menu.index("end") + 1) if menu.type(i) != "separator"
                    and menu.entrycget(i, "label") == label)

    def query_state(self, label="查詢額度"):
        return self.widget._menu.entrycget(self.menu_item(label), "state")


class MenuTest(QueryWiringTestCase):
    def test_the_menu_offers_query_usage_even_when_nothing_is_lagging(self):
        self.assertEqual(self.query_state(), "normal")  # ACTIVE 沒有落後

    def test_it_is_disabled_while_a_query_runs_or_cools_down(self):
        self.show(ACTIVE, in_progress=True)
        self.assertEqual(self.query_state(), "disabled")
        self.show(ACTIVE, cooling_down=True)
        self.assertEqual(self.query_state(), "disabled")
        self.show(ACTIVE)
        self.assertEqual(self.query_state(), "normal")

    def test_the_label_follows_the_language(self):
        self.widget.set_preference("language", "en")
        self.assertEqual(self.query_state("Query usage"), "normal")

    def test_choosing_it_starts_a_query_and_redraws_at_once(self):
        polls = self.polls
        self.widget._menu.invoke(self.menu_item("查詢額度"))
        self.assertEqual(self.started, [True])
        self.assertEqual(self.polls, polls + 1)  # 不等下一輪，立刻 poll 讓畫面顯示進行中

    def test_a_refused_query_does_nothing_more(self):
        self.accept = False
        polls = self.polls
        self.widget.query_usage()
        self.assertEqual(self.started, [True])
        self.assertEqual(self.polls, polls)


class EntryTest(QueryWiringTestCase):
    def entry_center(self):
        self.root.geometry("+-3000+-3000")
        self.root.deiconify()
        self.root.update()
        self.addCleanup(self.root.update)
        canvas = self.widget.canvas
        item = next(i for i in canvas.find_all() if canvas.type(i) == "text" and canvas.itemcget(i, "text") == "更新"
                    and canvas.itemcget(i, "state") != "hidden")
        x1, y1, x2, y2 = canvas.bbox(item)
        return int((x1 + x2) / 2), int((y1 + y2) / 2)

    def test_clicking_the_entry_on_a_lagging_card_starts_a_query(self):
        self.show(LAGGING)
        x, y = self.entry_center()
        self.widget.canvas.event_generate("<Motion>", x=x, y=y)
        self.widget.canvas.event_generate("<Button-1>", x=x, y=y)
        self.root.update()
        self.assertEqual(self.started, [True])

    def test_double_clicking_the_entry_does_not_toggle_the_mode(self):
        self.show(LAGGING)
        x, y = self.entry_center()
        self.widget.canvas.event_generate("<Motion>", x=x, y=y)
        self.root.update()
        before = self.widget.menu_state().mode
        self.widget._double_click(None)  # 游標在入口上：入口自己處理點擊，雙擊不該同時切換模式
        self.assertEqual(self.widget.menu_state().mode, before)


class PollIntervalTest(QueryWiringTestCase):
    def delay_after(self, **status):
        self.show(ACTIVE, **status)
        with mock.patch.object(self.root, "after", wraps=self.root.after) as after:
            self.widget.refresh()
        return after.call_args.args[0]

    def test_polls_faster_while_a_query_is_in_progress(self):
        self.assertEqual(self.delay_after(), POLL_MS)
        self.assertEqual(self.delay_after(in_progress=True), QUERY_POLL_MS)
        self.assertEqual(self.delay_after(cooling_down=True), POLL_MS)
        self.assertLess(QUERY_POLL_MS, POLL_MS)
