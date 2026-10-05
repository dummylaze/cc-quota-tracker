"""假的 claude：扮演 Claude Code 的 stream-json 控制請求端，依測試寫的劇本回應。

劇本與紀錄放在環境變數 FAKE_CLAUDE_DIR 指的目錄（由 claude.cmd 設定）：
- script.json：{"usage": "write" | "error" | "silent" | "hang" | "crash", "cache": 額度快取所在的檔案,
  "cache_text": 寫回的內容, "message": 錯誤訊息, "exit": 結束代碼,
  "gate": 選填，這個檔案出現之前不回應 get_usage（讓測試停在查詢進行中）,
  "runs": 選填，第 n 次被啟動時（從 0 起算）用 runs[n] 的欄位蓋掉上面的；沒有那一筆就用上面的,
  "usage_cache": 選填，寫回時改成「只把 cachedUsageUtilization 換成這份、其餘鍵留著，accountUuid 取當下登入的帳號」，
  比整份覆蓋貼近真的 Claude Code,
  "credential_path": 選填，當前憑證所在的檔案：被啟動當下記下它的內容,
  "credential_text": 選填，get_usage 時把它寫進 credential_path，模擬查詢順便刷新了憑證}
- record.json：收到的參數、CLAUDE_CONFIG_DIR、工作目錄、pid、有沒有主控台視窗，給測試斷言
- starts.log：每次被啟動追加一行，給測試數查詢的次數
- credential-at-start-<n>.txt：有 "credential_path" 時，第 n 次被啟動當下當前憑證的內容（查詢用的是哪份憑證）
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
    starts_log = ROOT / "starts.log"
    run = len(starts_log.read_text(encoding="utf-8").splitlines()) if starts_log.exists() else 0
    runs = script.get("runs", [])
    if run < len(runs):
        script = {**script, **runs[run]}
    console = bool(ctypes.windll.kernel32.GetConsoleWindow()) if os.name == "nt" else False
    (ROOT / "record.json").write_text(json.dumps({
        "argv": sys.argv[1:], "cwd": os.getcwd(), "pid": os.getpid(), "console_window": console,
        "has_config_dir": "CLAUDE_CONFIG_DIR" in os.environ,
        "config_dir": os.environ.get("CLAUDE_CONFIG_DIR")}), encoding="utf-8")
    credential_path = script.get("credential_path")
    if credential_path:
        (ROOT / f"credential-at-start-{run}.txt").write_text(
            Path(credential_path).read_text(encoding="utf-8"), encoding="utf-8")
    with starts_log.open("a", encoding="utf-8") as starts:  # 每次被啟動記一行：測試數查了幾次
        starts.write("start\n")
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
            while "gate" in script and not Path(script["gate"]).exists():
                time.sleep(0.02)
            if usage == "hang":
                time.sleep(60)
            elif usage == "error":
                respond(request_id, script["message"])
            else:
                if usage == "write" and "usage_cache" in script:
                    cache = Path(script["cache"])
                    data = json.loads(cache.read_text(encoding="utf-8"))
                    usage_cache = dict(script["usage_cache"], accountUuid=data["oauthAccount"]["accountUuid"])
                    cache.write_text(json.dumps({**data, "cachedUsageUtilization": usage_cache}), encoding="utf-8")
                elif usage == "write":
                    Path(script["cache"]).write_text(script["cache_text"], encoding="utf-8")
                if "credential_text" in script:
                    Path(credential_path).write_text(script["credential_text"], encoding="utf-8")
                respond(request_id)
    sys.exit(script.get("exit", 0))


if __name__ == "__main__":
    main()
