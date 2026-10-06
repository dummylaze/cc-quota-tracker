# PyInstaller 設定（ADR-0012）：資料夾模式，視窗與命令列兩個 exe 放在同一個資料夾。
# 建置：在 repo 根目錄執行 `python -m PyInstaller packaging/cc-quota-tracker.spec --noconfirm`，產出在 dist/cc-quota-tracker/。
# 兩個 exe 的檔名一發佈就會有人依賴（開機自動啟動的登錄值、使用者的腳本）；視窗 exe 的檔名也寫在 cc_quota_tracker/autostart.py。
from pathlib import Path

root = Path(SPECPATH).parent  # SPECPATH 由 PyInstaller 提供：這個 spec 所在的資料夾


def analysis(entry):
    return Analysis([str(root / "packaging" / entry)], pathex=[str(root)], noarchive=False)


def executable(a, name, console):
    return EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True, name=name, console=console, upx=False)


gui, cli = analysis("gui_entry.py"), analysis("cli_entry.py")
gui_exe = executable(gui, "cc-quota-tracker", console=False)
cli_exe = executable(cli, "cc-quota-tracker-cli", console=True)

COLLECT(gui_exe, gui.binaries, gui.datas, cli_exe, cli.binaries, cli.datas, upx=False, name="cc-quota-tracker")
