"""假的 claude：扮演 Claude Code 的 stream-json 控制請求端，依測試寫的劇本回應。

劇本與紀錄放在環境變數 FAKE_CLAUDE_DIR 指的目錄（由 claude.cmd 設定）：
- script.json：{"usage": "write" | "error" | "silent" | "hang" | "crash", "cache": 額度快取所在的檔案,
  "cache_text": 寫回的內容, "message": 錯誤訊息, "exit": 結束代碼}
- record.json：收到的參數、CLAUDE_CONFIG_DIR、工作目錄、pid、有沒有主控台視窗，給測試斷言
永遠不碰真實的額度快取：寫回的路徑一律由劇本指定。
"""
import ctypes
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ["FAKE_CLAUDE_DIR"])


def respond(request_id, error=None):
    response = {"subtype": "error", "request_id": request_id, "error": error} if error else \
        {"subtype": "success", "request_id": request_id, "response": {}}
    print(json.dumps({"type": "control_response", "response": response}), flush=True)


def main():
    script = json.loads((ROOT / "script.json").read_text(encoding="utf-8"))
    console = bool(ctypes.windll.kernel32.GetConsoleWindow()) if os.name == "nt" else False
    (ROOT / "record.json").write_text(json.dumps({
        "argv": sys.argv[1:], "cwd": os.getcwd(), "pid": os.getpid(), "console_window": console,
        "has_config_dir": "CLAUDE_CONFIG_DIR" in os.environ,
        "config_dir": os.environ.get("CLAUDE_CONFIG_DIR")}), encoding="utf-8")
    usage = script["usage"]
    if usage == "crash":
        print(script["message"], file=sys.stderr, flush=True)
        sys.exit(script.get("exit", 1))
    for line in sys.stdin:
        message = json.loads(line)
        if message.get("type") != "control_request":
            continue
        subtype, request_id = message["request"]["subtype"], message["request_id"]
        if subtype == "initialize":
            respond(request_id)
        elif subtype == "get_usage":
            if usage == "hang":
                time.sleep(60)
            elif usage == "error":
                respond(request_id, script["message"])
            else:
                if usage == "write":
                    Path(script["cache"]).write_text(script["cache_text"], encoding="utf-8")
                respond(request_id)
    sys.exit(script.get("exit", 0))


if __name__ == "__main__":
    main()
