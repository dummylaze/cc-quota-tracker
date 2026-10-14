"""置頂要持續維持在 Windows 的置頂層：Windows 偶爾會讓視窗掉出置頂層（Tk 的 -topmost 仍是真），
每輪 poll 偵測到掉層就重新宣告置頂；沒掉層時不動，免得蓋住開著的右鍵選單、或每輪跟其他置頂視窗搶最上層。
以 Win32 的 z-order 驗，不只驗 Tk 屬性。"""
import sys
import tkinter as tk
import unittest
from unittest import mock

from cc_quota_tracker import zorder
from tests.test_widget import WidgetTestCase

if sys.platform == "win32":
    import ctypes

    _user32 = ctypes.windll.user32
    _user32.GetWindow.restype = ctypes.c_void_p
    _user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    _user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_uint]

_GW_HWNDPREV, _GWL_EXSTYLE, _WS_EX_TOPMOST = 3, -20, 0x8
_HWND_TOPMOST = -1
_SWP_KEEP = 0x13  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE


def hwnd(window) -> int:
    return int(window.wm_frame(), 16)


def is_above(window, other) -> bool:
    """other 在 z-order 裡是否排在 window 上方。"""
    h, target = _user32.GetWindow(hwnd(window), _GW_HWNDPREV), hwnd(other)
    while h:
        if h == target:
            return True
        h = _user32.GetWindow(h, _GW_HWNDPREV)
    return False


def topmost_flag(window) -> bool:
    return bool(_user32.GetWindowLongW(hwnd(window), _GWL_EXSTYLE) & _WS_EX_TOPMOST)


def place_below(window, other):
    """模擬 Windows 讓視窗掉出置頂層：把它排到一般視窗 other 的下方。"""
    _user32.SetWindowPos(hwnd(window), hwnd(other), 0, 0, 0, 0, _SWP_KEEP)


def bring_to_top(window):
    _user32.SetWindowPos(hwnd(window), _HWND_TOPMOST, 0, 0, 0, 0, _SWP_KEEP)


@unittest.skipUnless(sys.platform == "win32", "只在 Windows 上驗 z-order")
class KeepTopmostTest(WidgetTestCase):
    def setUp(self):
        super().setUp()
        self.root.deiconify()
        self.root.update()  # 先讓視窗真的顯示出來；不然之後才顯示時會被排回最上面，測試就驗不到東西
        self.other = self.second_window()

    def second_window(self, topmost=False):
        window = tk.Tk()
        window.overrideredirect(True)
        window.geometry("50x50+0+0")
        if topmost:
            window.attributes("-topmost", True)
        window.update()
        self.addCleanup(window.destroy)
        return window

    def test_window_that_fell_below_a_normal_window_is_brought_back_on_the_next_round(self):
        place_below(self.root, self.other)
        self.assertTrue(is_above(self.root, self.other))
        # 這裡不能讀 Tk 的 -topmost 來確認它「仍以為自己置頂」：在 Windows 上連讀取都會重新套用置頂，測試就驗不到東西
        self.widget.refresh()
        self.assertFalse(is_above(self.root, self.other))
        self.assertTrue(topmost_flag(self.root))

    def test_window_still_in_the_topmost_band_is_left_where_it_is(self):
        # 開著的右鍵選單、其他置頂工具都排在置頂層裡的上方：沒掉層就不重新宣告，才不會蓋住它們
        menu_like = self.second_window(topmost=True)
        bring_to_top(menu_like)
        self.assertTrue(is_above(self.root, menu_like))
        self.widget.refresh()
        self.assertTrue(is_above(self.root, menu_like))

    def test_window_set_not_to_stay_on_top_is_not_brought_back(self):
        self.widget.set_preference("alwaysOnTop", False)
        place_below(self.root, self.other)
        self.widget.refresh()
        self.assertTrue(is_above(self.root, self.other))
        self.assertFalse(topmost_flag(self.root))


class FakeUser32:
    """z-order 的替身：windows 由上到下排列，每項是（hwnd, 是否置頂）。"""

    def __init__(self, *windows):
        self.order = [hwnd for hwnd, _ in windows]
        self.topmost = dict(windows)

    def GetWindow(self, hwnd, cmd):
        assert cmd == _GW_HWNDPREV
        at = self.order.index(hwnd)
        return self.order[at - 1] if at > 0 else None

    def GetWindowLongW(self, hwnd, index):
        assert index == _GWL_EXSTYLE
        return _WS_EX_TOPMOST if self.topmost[hwnd] else 0


@unittest.skipUnless(sys.platform == "win32", "判斷只在 Windows 上生效")
class OutOfTopmostBandTest(unittest.TestCase):
    """真的桌面重現不了「旗標還在、上方卻有一般視窗」（Windows 會一併清掉旗標），判斷本身用替身驗。"""

    def out(self, *windows):
        with mock.patch.object(zorder, "_user32", FakeUser32(*windows)):
            return zorder.out_of_topmost_band(1)

    def test_flag_still_set_but_a_normal_window_above_is_out_of_the_band(self):
        self.assertTrue(self.out((9, True), (8, False), (1, True)))

    def test_flag_cleared_is_out_of_the_band_even_with_nothing_above(self):
        self.assertTrue(self.out((1, False)))

    def test_only_topmost_windows_above_is_still_in_the_band(self):
        self.assertFalse(self.out((9, True), (8, True), (1, True)))
        self.assertFalse(self.out((1, True)))
