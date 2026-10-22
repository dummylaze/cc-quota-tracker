"""懸浮視窗的背景子行程：產生 token 報表、更新用量帳本都在子行程裡跑，解析對話紀錄的記憶體不算在視窗行程上（ADR-0004）。
子行程不開主控台：打包版呼叫與視窗 exe 同資料夾的命令列 exe（ADR-0012），原始碼版呼叫 `python -m`。
子行程的輸出不接管：stdout 丟掉，stderr 寫進暫存檔（不是管線，輸出再多也不會卡住子行程），結束後由呼叫端讀一小段記進錯誤紀錄。"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO, List, Mapping, Optional, Sequence

CLI_EXE = "cc-quota-tracker-cli.exe"  # 打包版的命令列 exe 檔名；與 packaging/cc-quota-tracker.spec 一致
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # 原始碼部署沒有安裝進 site-packages：-m 要從專案根目錄找得到套件
REPORT_ARGS: Sequence[str] = ()  # 產生報表並用預設瀏覽器打開
LEDGER_ARGS: Sequence[str] = ("--update-ledger",)  # 只更新用量帳本與帳號標籤的對照
_CREATE_NO_WINDOW = 0x08000000  # Windows：不開主控台視窗
_ERROR_TAIL_BYTES = 2000  # 固定值：記進錯誤紀錄的 stderr 最多取最後這麼多


def base_command(frozen: bool, executable: str) -> List[str]:
    """子行程的命令（不含參數）。executable 是目前這個行程的執行檔。"""
    if frozen:
        return [str(Path(executable).with_name(CLI_EXE)), "report"]
    return [executable, "-m", "cc_quota_tracker", "report"]


class JobFailed(Exception):
    """子行程以非 0 結束：訊息帶參數、結束代碼與它印到 stderr 的最後一小段，給錯誤紀錄用。"""

    def __init__(self, args: Sequence[str], code: int, output: str):
        super().__init__(f"report {' '.join(args)} exited with code {code}" + (f": {output}" if output else ""))


class Job:
    """一個執行中的子行程。poll 不等待，回傳結束代碼；還在跑回傳 None。"""

    def __init__(self, process: subprocess.Popen, errors: BinaryIO):
        self._process, self._errors = process, errors

    def poll(self) -> Optional[int]:
        return self._process.poll()

    def error_output(self) -> str:
        """子行程印到 stderr 的最後一小段，結束後才呼叫；讀完就關掉暫存檔。"""
        try:
            self._errors.seek(0, os.SEEK_END)
            self._errors.seek(max(0, self._errors.tell() - _ERROR_TAIL_BYTES))
            return self._errors.read().decode("utf-8", errors="replace").strip()
        finally:
            self._errors.close()


def launch(args: Sequence[str], env: Optional[Mapping[str, str]] = None) -> Job:
    """啟動一個子行程跑 `report <args>`。開不起來（執行檔不見了、不能執行）丟 OSError。"""
    frozen = getattr(sys, "frozen", False)
    errors = tempfile.TemporaryFile()
    try:
        process = subprocess.Popen(
            [*base_command(frozen, sys.executable), *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=errors, env=None if env is None else dict(env), cwd=None if frozen else PROJECT_ROOT,
            creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0)
    except BaseException:
        errors.close()
        raise
    return Job(process, errors)
