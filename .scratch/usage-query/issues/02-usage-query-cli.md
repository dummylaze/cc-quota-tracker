# 02: 命令列 `query` 子指令與 `list` 的查詢說明

**What to build:** 使用者可以在命令列執行 `query`：同步查詢一次並等它結束。成功時印出新的觀測時間、結束代碼 0；失敗時印出原因與「可改在 Claude Code 執行 `/usage`」、結束代碼 1，讓別的腳本能依結束代碼判斷。命令列不受 GUI 冷卻限制。命令列 `list` 在有落後讀數或讀數待更新時，寫出一句完整說明：可以執行 `query`，或在 Claude Code 執行 `/usage`。新文案兩個語系都要有，實作前先與使用者確認文案。

**Blocked by:** `01-usage-query-core.md`

**Status:** resolved

- [x] 文案已與使用者確認
- [x] 命令列測試（呼叫 main、比對輸出與結束代碼）：成功印出觀測時間且結束代碼 0；四種失敗各自印出原因、含 `/usage` 退路且結束代碼 1；Claude Code 回報的原始訊息不被翻譯
- [x] `list` 在落後與讀數待更新時都出現完整說明，沒有落後時不出現；兩個語系
- [x] 手動驗證：真實 Claude Code 上執行一次 `query`，額度快取被寫回、觀測時間前進
- [x] 手動驗證：開機自動啟動的環境也找得到 `claude`，或依設定填路徑後找得到
- [x] 既有命令列測試一行未改、全部通過

## Comments

- 實作：`__main__.py` 的 `query`（呼叫 `Core.query_usage()`，同步）、`render_text.render` 的 `list.query_hint`（任一卡片落後或讀數待更新時，在各卡片之後、「納管帳號」之前出現一次；待命卡片的「切換前已落後」由 07 加上 `lagging` 後自動涵蓋）。測試在新檔 `tests/test_cli_query.py`，既有的 `tests/test_cli.py` 一行未改。
- 實作前與使用者確認：兩個語系的文案；`query` 等待期間不印進度提示（stdout 只有成功那一行，方便腳本解析）；成功輸出 stdout、失敗輸出 stderr。
- 設定檔讀不懂時，`query` 比照 `add`／`remove` 先印「設定檔無法讀取」：此時 `claudeCommand` 會被當成沒填，使用者要知道自己填的路徑沒生效。spec 沒寫，補上。
- 時間格式沿用 `list` 的完整日期時間（精度到分鐘），從 `render_text` 搬到 `fmt.date_time` 共用。
- 手動驗證：真實 Claude Code 上執行 `query`，約 3 秒、結束代碼 0，使用中帳號的讀數年齡由 16 分鐘變 0，`list` 的說明隨之消失。開機自動啟動：開機啟動的行程拿到的是登錄裡的 Machine＋User PATH，`claude` 所在的 npm 全域目錄在 User PATH 裡，找得到；找不到時依 `claudeCommand` 填路徑。
- 專案沒有型別檢查器，以 `compileall` 當語法檢查。
- README 的命令列說明由 08 一併更新，本票未動。
