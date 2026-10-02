"""查詢額度（ADR-0010）：開 Claude Code 子行程送 get_usage 控制請求，由它寫回額度快取。
成敗只看額度快取的觀測時間有沒有前進，不解析查詢的回應；回應只用來知道何時關閉輸入，以及 Claude Code 回報的錯誤。"""
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, List, Mapping, Optional

from . import claude_provider as provider
from .board import QueryFailure, UsageQueryResult

TIMEOUT = timedelta(seconds=20)  # 固定值：以核心的時鐘計
# print 模式＋stream-json 輸入輸出；一律關閉 hooks，查詢不觸發使用者自己的 hooks
ARGS = ("-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--settings", '{"disableAllHooks":true}')
_INITIALIZE, _GET_USAGE = "cc-quota-tracker-initialize", "cc-quota-tracker-get-usage"
_CREATE_NO_WINDOW = 0x08000000  # Windows：不開主控台視窗、不搶焦點


def find_command(settings: provider.ProviderSettings, env: Mapping[str, str]) -> Optional[str]:
    """有設定就只認那個路徑，檔案不存在或設定不合法都不退回 PATH（ADR-0008 同精神）；沒設定才從 PATH 找。"""
    configured = settings.claude_command
    if settings.claude_command_invalid:
        return None
    if configured is not None:
        return str(configured) if configured.is_file() else None
    return shutil.which("claude", path=env.get("PATH", ""))


def observed_at(cache: Path) -> Optional[datetime]:
    """額度快取目前的觀測時間；讀不到、還沒有讀數或讀不懂都是 None。"""
    try:
        reading = provider.parse(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # ValueError：不是 UTF-8，跟讀不懂一樣當成沒有讀數
        return None
    return reading.observed_at if isinstance(reading, provider.UsageReading) else None


class UsageQuery:
    """一次查詢。start 開子行程並送出請求；之後反覆呼叫 check，回傳 None 表示還在進行中。
    check 不會等待，GUI 每輪 poll 叫一次也不會凍結。"""

    def __init__(self, command: str, env: Mapping[str, str], cache: Path, deadline: datetime):
        self._command, self._env, self._cache, self._deadline = command, dict(env), cache, deadline
        self._before = observed_at(cache)
        self._events: "queue.Queue[dict]" = queue.Queue()
        self._stderr: List[bytes] = []
        self._error: Optional[str] = None
        self._process: Optional[subprocess.Popen] = None
        self._result: Optional[UsageQueryResult] = None

    def start(self) -> None:
        """開不起來（執行檔不見了、不能執行）丟 OSError。"""
        flags = _CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(
            [self._command, *ARGS], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=tempfile.gettempdir(), env=self._env, creationflags=flags, start_new_session=os.name != "nt")
        threading.Thread(target=self._read_stdout, args=(self._process.stdout,), daemon=True).start()
        self._stderr_reader = threading.Thread(target=self._read_stderr, args=(self._process.stderr,), daemon=True)
        self._stderr_reader.start()
        try:
            for request_id, subtype in ((_INITIALIZE, "initialize"), (_GET_USAGE, "get_usage")):
                line = {"type": "control_request", "request_id": request_id, "request": {"subtype": subtype}}
                self._process.stdin.write((json.dumps(line) + "\n").encode("utf-8"))
            self._process.stdin.flush()
        except OSError:
            pass  # 子行程已經結束；交給 check 依結束代碼判定

    def check(self, now: datetime) -> Optional[UsageQueryResult]:
        """結果一決定就關閉輸入，等 Claude Code 自己結束才回報，不留下還在跑的子行程；拖過逾時才強制結束。"""
        process = self._process
        assert process is not None
        if self._result is None:
            self._result = self._decide(process.poll(), now)
            if self._result is None:
                if now < self._deadline:
                    return None
                self._result = UsageQueryResult(QueryFailure.TIMEOUT)
        self._close_input()
        if process.poll() is None:
            if now < self._deadline:
                return None
            self._kill()
        return self._result

    def _decide(self, code: Optional[int], now: datetime) -> Optional[UsageQueryResult]:
        """code 要在看額度快取之前取：結束前剛寫回的，才不會被誤判成沒有寫回。"""
        if self._advanced():
            return UsageQueryResult(observed_at=observed_at(self._cache))
        self._drain_events()
        if self._error is not None:
            return UsageQueryResult(QueryFailure.REPORTED_ERROR, message=self._error)
        if code is None:
            return None
        if code != 0:
            if self._stderr_reader.is_alive() and now < self._deadline:
                return None  # 還沒讀完它印出的訊息；不在這裡等，check 才不會凍結 GUI。到了逾時就用已讀到的部分
            text = b"".join(self._stderr).decode("utf-8", errors="replace").strip()
            return UsageQueryResult(QueryFailure.REPORTED_ERROR, message=text or None)
        return UsageQueryResult(QueryFailure.NOT_WRITTEN)

    def _advanced(self) -> bool:
        current = observed_at(self._cache)
        return current is not None and (self._before is None or current > self._before)

    def _drain_events(self) -> None:
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                return
            response = event.get("response")
            if event.get("type") != "control_response" or not isinstance(response, dict):
                continue
            if response.get("request_id") not in (_INITIALIZE, _GET_USAGE):
                continue
            if response.get("subtype") == "error":
                self._error = str(response.get("error") or "")
            elif response.get("request_id") == _GET_USAGE:
                self._close_input()  # 收到回應就關閉輸入，Claude Code 隨之結束

    def _read_stdout(self, stream: IO[bytes]) -> None:
        with stream:
            for line in stream:
                try:
                    event = json.loads(line.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if isinstance(event, dict):
                    self._events.put(event)

    def _read_stderr(self, stream: IO[bytes]) -> None:
        with stream:
            for chunk in iter(lambda: stream.read(4096), b""):
                self._stderr.append(chunk)

    def _close_input(self) -> None:
        try:
            self._process.stdin.close()
        except OSError:
            pass

    def _kill(self) -> None:
        """連子行程一起結束：npm 裝的 claude 是批次檔，只結束 cmd.exe 的話，背後的 node 會留下來。"""
        process = self._process
        if os.name == "nt":
            taskkill = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32" / "taskkill.exe"
            subprocess.run([str(taskkill), "/T", "/F", "/PID", str(process.pid)], capture_output=True,
                           creationflags=_CREATE_NO_WINDOW)
        else:
            try:
                os.killpg(process.pid, 9)
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        self._close_input()
