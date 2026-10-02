# 01: 查詢額度核心：請 Claude Code 代查並以額度快取的觀測時間判定成敗

**What to build:** 核心可以同步執行一次查詢額度（Usage Query）：開 Claude Code 子行程，送出查詢請求，等它結束，再依額度快取的觀測時間有沒有前進回報成功或失敗。新增設定 `providers.claude.claudeCommand`（`claude` 執行檔完整路徑，`null` 從 PATH 找；有填但檔案不存在時失敗，不退回 PATH）。成功只看觀測時間，不解析回應；失敗分四類：找不到執行檔、逾時（20 秒，以核心時鐘計）、Claude Code 回報錯誤（附原始訊息，不翻譯）、沒有寫回額度快取。子行程關閉所有 hooks、不開主控台視窗、工作目錄不屬於任何專案，並依 Claude Code 目錄的來源設定或移除 `CLAUDE_CONFIG_DIR`，讓查詢寫回的正是工具在讀的那份額度快取。（ADR-0010）

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 縫 ① 測試（假 home＋假 `claude` 腳本，在設定檔的 `claudeCommand` 指向它）：成功時額度快取的觀測時間前進、讀數變新
- [x] 四種失敗原因各一個測試；失敗時既有讀數不變；逾時以 FakeClock 推進、不實際等 20 秒，且子行程被結束
- [x] 設定的路徑不存在時失敗，不退回 PATH 裡的另一個 `claude`
- [x] 假 `claude` 寫出收到的參數與環境，斷言：hooks 關閉參數存在；Claude Code 目錄來源是 home 預設時環境沒有 `CLAUDE_CONFIG_DIR`，來源是設定檔欄位或環境變數時等於工具解析出的目錄
- [x] 查詢不產生對話紀錄：假 `claude` 不寫對話紀錄，查詢成功後讀數不落後
- [x] 縫 ③ 測試：`claudeCommand` 的預設值（`null`）、不合法值、設定檔寫出的預設內容；執行中改了下一輪生效，不必重新啟動
- [x] 不開主控台視窗、不搶焦點（Windows 的建立旗標有測試或明確的手動確認）
- [x] 既有測試全部通過

## Comments

- 實作：`cc_quota_tracker/usage_query.py`（子行程與 stream-json 控制請求）、`Core.query_usage()`（同步）、`providers.claude.claudeCommand`。`UsageQuery` 分成 `start`／不阻塞的 `check`，03 的非同步查詢直接沿用。
- 控制請求格式依 Claude Code 擴充套件 2.1.287 的原始碼：`control_request`（`initialize`、`get_usage`）與 `control_response`（`subtype` 為 `success`／`error`）。
- 實作前與使用者確認：`claudeCommand` 不合法（非字串、空字串、相對路徑）→ 列入不合法設定，查詢回報「找不到 `claude` 執行檔」，不退回 PATH；指向目錄或不存在的檔案不算不合法設定，查詢一樣回報找不到。「Claude Code 回報錯誤」的訊息：控制回應的 `error` 優先，沒有就取 stderr 全文；核心不截斷，截斷交給畫面層。
- 逾時用 `taskkill /T /F` 結束整棵行程樹：npm 裝的 `claude` 是批次檔，只結束 `cmd.exe` 的話，背後的 node 會留下來。測試的假 `claude` 也是批次檔包一支 Python。
- 不開主控台視窗：自動測試只在測試執行器本身有主控台視窗時才跑（沒有的話，子行程不加旗標也偵測不到視窗，測試會空轉）。手動確認：在有主控台的視窗中，加 `CREATE_NO_WINDOW` 時子行程沒有主控台視窗，拿掉時有；在有主控台的視窗中跑該測試，通過、沒有 skip。
- 真實 Claude Code 上跑過一次：約 3.6 秒成功，額度快取的觀測時間前進，下一輪 poll 讀到新的值。
