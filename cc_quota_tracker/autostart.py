"""開機自動啟動：在目前使用者的 Windows 登錄 Run 機碼寫入本工具自己的一個值，只動這一個值。
開關狀態一律問登錄，不另存一份，使用者自己刪掉啟動項時兩邊才不會不同步。"""
import subprocess
import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # 在 HKEY_CURRENT_USER 底下：只影響目前使用者，不需要系統管理員
VALUE_NAME = "cc-quota-tracker"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def pythonw_for(python: Path) -> Path:
    """與直譯器同目錄的 pythonw（不會開主控台視窗）；找不到就沿用原直譯器，總比寫進去啟動不了好。"""
    python = Path(python)
    pythonw = python.with_name("pythonw.exe")
    return pythonw if pythonw.exists() else python


def launch_command(python: Path, root: Path = PROJECT_ROOT) -> str:
    """登錄裡的啟動命令。開機啟動時的工作目錄不是專案根目錄，而專案是原始碼部署、沒有安裝進 site-packages，
    所以不能寫 -m，要先把專案根目錄放進 sys.path 再呼叫命令列的 gui。list2cmdline 處理路徑裡的空白與引號。"""
    code = f"import sys; sys.path.insert(0, {str(root)!r}); from cc_quota_tracker.__main__ import main; sys.exit(main(['gui']))"
    return subprocess.list2cmdline([str(python), "-c", code])


class RegistryAutostart:
    def __init__(self, name: str = VALUE_NAME, command: str = None, key_path: str = RUN_KEY):
        self._name = name
        self._command = command or launch_command(pythonw_for(Path(sys.executable)))
        self._key_path = key_path

    def is_enabled(self) -> bool:
        """登錄裡有這個值，而且指向現在這份程式。專案搬家或換了 Python 之後，舊的啟動項開機時啟動不了，
        所以顯示成關閉；再開一次就會改寫成正確的。"""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._key_path) as key:
                value, _ = winreg.QueryValueEx(key, self._name)
        except OSError:
            return False
        return value == self._command

    def enable(self):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self._key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, self._name, 0, winreg.REG_SZ, self._command)

    def disable(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, self._name)
        except FileNotFoundError:
            pass  # 本來就沒有
