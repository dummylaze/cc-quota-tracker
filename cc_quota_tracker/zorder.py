"""Windows 的 z-order：判斷視窗是否還在置頂層。

Windows 偶爾會讓視窗掉出置頂層，Tk 那邊的 -topmost 卻仍是真，程式的狀態就以為自己還在置頂。
置頂層的視窗在 z-order 裡一律排在一般視窗之前，所以只要自己上方出現任何一般視窗，就是已經掉出置頂層。"""
import sys

_GW_HWNDPREV = 3
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x8

if sys.platform == "win32":
    import ctypes

    _user32 = ctypes.windll.user32
    _user32.GetWindow.restype = ctypes.c_void_p
    _user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]


def _topmost(hwnd: int) -> bool:
    return bool(_user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOPMOST)


def out_of_topmost_band(hwnd: int) -> bool:
    """hwnd（頂層視窗）已不在置頂層：自己的置頂旗標掉了，或上方有一般視窗。不是 Windows 一律回 False。"""
    if sys.platform != "win32":
        return False
    if not _topmost(hwnd):
        return True
    above = _user32.GetWindow(hwnd, _GW_HWNDPREV)
    while above:
        if not _topmost(above):
            return True
        above = _user32.GetWindow(above, _GW_HWNDPREV)
    return False
