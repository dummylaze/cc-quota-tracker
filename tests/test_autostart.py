"""開機自動啟動：只動登錄裡本工具自己的那一個值，開關狀態以登錄的實際值為準。
測試用真的 Windows 登錄，但寫在測試專用的暫存機碼，不碰使用者真實的啟動項。"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

if sys.platform == "win32":
    import winreg
    from cc_quota_tracker.autostart import RegistryAutostart, launch_command, pythonw_for

STUB_MAIN = '''import os, sys

def main(argv):
    with open(os.environ["MARKER"], "w", encoding="utf-8") as f:
        f.write(repr((argv, sys.path[0])))
    return 0
'''


@unittest.skipUnless(sys.platform == "win32", "開機自動啟動只支援 Windows 登錄")
class RegistryAutostartTest(unittest.TestCase):
    def setUp(self):
        self.key_path = rf"Software\cc-quota-tracker-test\{uuid.uuid4().hex}"
        self.addCleanup(self.drop_key)
        self.autostart = RegistryAutostart("cc-quota-tracker", "pythonw.exe -m demo", key_path=self.key_path)

    def drop_key(self):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.key_path)
        except OSError:
            pass

    def values(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path) as key:
                return dict(winreg.EnumValue(key, i)[:2] for i in range(winreg.QueryInfoKey(key)[1]))
        except OSError:
            return {}

    def put(self, name, value):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def test_off_by_default(self):
        self.assertFalse(self.autostart.is_enabled())

    def test_enable_writes_only_its_own_value(self):
        self.put("SomeOtherApp", "other.exe")
        self.autostart.enable()
        self.assertTrue(self.autostart.is_enabled())
        self.assertEqual(self.values(), {"SomeOtherApp": "other.exe", "cc-quota-tracker": "pythonw.exe -m demo"})

    def test_disable_removes_only_its_own_value(self):
        self.put("SomeOtherApp", "other.exe")
        self.autostart.enable()
        self.autostart.disable()
        self.assertFalse(self.autostart.is_enabled())
        self.assertEqual(self.values(), {"SomeOtherApp": "other.exe"})

    def test_disable_when_already_off_is_not_an_error(self):
        self.autostart.disable()
        self.autostart.disable()
        self.assertFalse(self.autostart.is_enabled())

    def test_state_follows_the_registry_when_the_value_is_deleted_by_hand(self):
        self.autostart.enable()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, "cc-quota-tracker")  # 使用者在工作管理員或登錄編輯器自己關掉
        self.assertFalse(self.autostart.is_enabled())

    def test_value_pointing_at_a_different_command_is_not_enabled(self):
        # 專案搬家或換了 Python：舊的啟動項開機時啟動不了，顯示成關閉，再開一次就修好
        self.put("cc-quota-tracker", r"C:\old\place\pythonw.exe -m demo")
        self.assertFalse(self.autostart.is_enabled())
        self.autostart.enable()
        self.assertTrue(self.autostart.is_enabled())
        self.assertEqual(self.values(), {"cc-quota-tracker": "pythonw.exe -m demo"})


@unittest.skipUnless(sys.platform == "win32", "開機自動啟動只支援 Windows 登錄")
class DeploymentCommandTest(unittest.TestCase):
    """預設的啟動命令依部署形式而定：原始碼版是 pythonw 加專案路徑，打包版是視窗 exe（ADR-0012）。"""

    EXE_DIR = r"C:\Program Files\cc quota tracker"

    def setUp(self):
        self.key_path = rf"Software\cc-quota-tracker-test\{uuid.uuid4().hex}"
        self.addCleanup(self.drop_key)

    def drop_key(self):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.key_path)
        except OSError:
            pass

    def stored(self):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path) as key:
            return winreg.QueryValueEx(key, "cc-quota-tracker")[0]

    def frozen(self, executable):
        """假裝在打包狀態下由 executable 這支 exe 執行。"""
        stack = ExitStack()
        stack.enter_context(mock.patch.object(sys, "frozen", True, create=True))
        stack.enter_context(mock.patch.object(sys, "executable", executable))
        return stack

    def test_frozen_writes_the_quoted_full_path_of_the_window_exe(self):
        with self.frozen(rf"{self.EXE_DIR}\cc-quota-tracker.exe"):
            RegistryAutostart(key_path=self.key_path).enable()
        self.assertEqual(self.stored(), rf'"{self.EXE_DIR}\cc-quota-tracker.exe"')

    def test_frozen_from_the_cli_exe_still_registers_the_window_exe(self):
        with self.frozen(rf"{self.EXE_DIR}\cc-quota-tracker-cli.exe"):
            RegistryAutostart(key_path=self.key_path).enable()
        self.assertEqual(self.stored(), rf'"{self.EXE_DIR}\cc-quota-tracker.exe"')

    def test_not_frozen_keeps_the_pythonw_command_for_this_project(self):
        RegistryAutostart(key_path=self.key_path).enable()
        self.assertEqual(self.stored(), launch_command(pythonw_for(Path(sys.executable))))
        self.assertNotIn("cc-quota-tracker.exe", self.stored())

    def test_each_deployment_sees_the_other_ones_command_as_off_without_migrating_it(self):
        source = RegistryAutostart(key_path=self.key_path)
        source.enable()
        source_command = self.stored()
        with self.frozen(rf"{self.EXE_DIR}\cc-quota-tracker.exe"):
            packaged = RegistryAutostart(key_path=self.key_path)
            self.assertFalse(packaged.is_enabled())
            self.assertEqual(self.stored(), source_command)  # 沒有被改寫
            packaged.enable()
            self.assertTrue(packaged.is_enabled())
        self.assertFalse(source.is_enabled())


@unittest.skipUnless(sys.platform == "win32", "開機自動啟動只支援 Windows 登錄")
class LaunchCommandTest(unittest.TestCase):
    def run_command(self, root: Path) -> tuple:
        """照登錄裡的寫法真的執行一次（改用 python.exe 以便同步等它結束），回傳 stub 記下的 (argv, sys.path[0])。"""
        marker = root.parent / "marker.txt"
        command = launch_command(sys.executable, root)
        # 開機啟動時的工作目錄不是專案根目錄：在別處執行才能證明不靠工作目錄
        subprocess.run(command, cwd=tempfile.gettempdir(), env={**os.environ, "MARKER": str(marker)}, check=True)
        return eval(marker.read_text(encoding="utf-8"))

    def make_project(self, name: str) -> Path:
        base = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(base, ignore_errors=True))
        package = base / name / "cc_quota_tracker"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "__main__.py").write_text(STUB_MAIN, encoding="utf-8")
        return base / name

    def test_starts_the_gui_from_the_project_without_relying_on_the_working_directory(self):
        root = self.make_project("project")
        argv, first_path = self.run_command(root)
        self.assertEqual(argv, ["gui"])
        self.assertEqual(Path(first_path), root)

    def test_survives_spaces_and_apostrophes_in_the_path(self):
        root = self.make_project("O'Brien's tools")
        argv, first_path = self.run_command(root)
        self.assertEqual((argv, Path(first_path)), (["gui"], root))

    def test_prefers_pythonw_next_to_the_interpreter(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(base, ignore_errors=True))
        python = base / "python.exe"
        python.write_text("")
        self.assertEqual(pythonw_for(python), python)  # 旁邊沒有 pythonw：退回原直譯器，總比寫進去啟動不了好
        (base / "pythonw.exe").write_text("")
        self.assertEqual(pythonw_for(python), base / "pythonw.exe")
        self.assertEqual(pythonw_for(base / "pythonw.exe"), base / "pythonw.exe")


if __name__ == "__main__":
    unittest.main()
