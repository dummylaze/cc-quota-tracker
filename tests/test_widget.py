"""視窗骨架：每輪 poll 一次交給版面渲染，after() 不重複註冊。"""
import tkinter as tk
import unittest

from cc_quota_tracker.widget import Widget
from tests.test_layout_a import BOARDS


class WidgetTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # 沒有顯示環境
            self.skipTest(f"Tk 無法啟動：{e}")
        self.root.withdraw()
        self.addCleanup(self.destroy_root)
        self.polls = 0
        self.widget = Widget(self.root, self.poll)

    def destroy_root(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass  # 已被 close() 銷毀

    def poll(self):
        self.polls += 1
        return BOARDS[self.polls % len(BOARDS)]

    def pending_after(self):
        return self.root.tk.splitlist(self.root.tk.call("after", "info"))

    def test_polls_once_on_start(self):
        self.assertEqual(self.polls, 1)
        self.assertEqual(len(self.pending_after()), 1)

    def test_refresh_keeps_a_single_pending_after(self):
        items = len(self.widget.canvas.find_all())
        for _ in range(10):
            self.widget.refresh()
        self.assertEqual(self.polls, 11)
        self.assertEqual(len(self.pending_after()), 1)
        self.assertEqual(len(self.widget.canvas.find_all()), items)

    def test_close_cancels_the_pending_after(self):
        self.widget.close()
        self.assertEqual(self.pending_after(), ())

    def test_window_is_borderless_and_topmost(self):
        self.assertTrue(self.root.overrideredirect())
        self.assertTrue(self.root.attributes("-topmost"))


if __name__ == "__main__":
    unittest.main()
