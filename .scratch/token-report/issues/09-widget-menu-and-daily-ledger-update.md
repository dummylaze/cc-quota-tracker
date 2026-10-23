# 09: 懸浮視窗選單「token 報表」與每日帳本更新

**What to build:** 使用者從懸浮視窗的右鍵選單點「token 報表」，本工具在背景產生報表並用預設瀏覽器打開。懸浮視窗啟動後、以及之後每 24 小時，在背景啟動一次只更新帳本的子行程，使用者不必記得開報表也不會漏掉用量。

**Blocked by:** 03

**Status:** resolved

## Acceptance criteria

- [x] 右鍵選單新增「token 報表」：在背景啟動子行程產生報表，完成後用預設瀏覽器打開
- [x] 懸浮視窗啟動後，以及之後每 24 小時，啟動一次只更新帳本的子行程
- [x] 子行程不顯示主控台：exe 版呼叫命令列的 exe，原始碼版呼叫 `python -m`
- [x] 子行程失敗只寫進錯誤紀錄，懸浮視窗不跳任何提示
- [x] 每日更新的子行程除了帳本，也更新帳號標籤的對照（`.state/account-labels.json`，沿用 05 的更新規則），讓報表一直沒產生過的帳號，移除憑證快照後也有最後的標籤可沿用；對照讀不到或寫不成時只寫進錯誤紀錄，不影響帳本更新的結果
- [x] 選單開報表與每日更新同時發生時，兩者都能完成（帳本的單一寫入在 03）
- [x] 解析在子行程裡跑，懸浮視窗行程的記憶體不因報表增加
- [x] 測試以假的子行程取代，驗證選單項目、啟動時機與參數；前例是既有懸浮視窗查詢額度的測試
- [x] 既有測試全部通過

## Comments

- 2026-10-23：**實作完成**。子行程在 `report_jobs.py`（`launch`／`base_command`／`Job`）：打包版呼叫同資料夾的 `cc-quota-tracker-cli.exe report`，原始碼版 `sys.executable -m cc_quota_tracker report`（cwd 是專案根目錄，原始碼部署沒裝進 site-packages），Windows 帶 `CREATE_NO_WINDOW`；stdout 丟掉、stderr 寫暫存檔（不用管線，輸出再多也不卡子行程），結束後取最後 2000 bytes。`Widget` 多一個 `report_launcher` 參數，`gui()` 傳真的 `report_jobs.launch`。選單項「token 報表」放在「自動查詢額度」後面；每日更新在每輪 `refresh` 以注入的時鐘判斷到期。「每日更新也更新帳號標籤對照」做在 `report --update-ledger`（對照失敗印 stderr＋寫錯誤紀錄，結束代碼不變；帳本失敗仍是 1）。
- 票面外、實作時自補的決定（審查者逐條判斷過，皆認為合理）：
  - 沒給 `report_launcher` 的視窗不放選單項、也不排每日更新（類比 `autostart=None`）；既有視窗測試因此不必動（它們斷言只有一個 pending `after`）。
  - 上一份報表還在產生時，再點選單什麼都不做（免得連點開出一排瀏覽器分頁）；每日更新也等前一個帳本更新結束。
  - 每日排程不用 Tk `after`，改在每輪 `refresh` 比對時鐘；子行程開不起來（任何例外）也排到下一個 24 小時週期，不每輪重試。
  - 子行程非 0 結束時視窗另寫一筆錯誤紀錄（含結束代碼與 stderr 尾段）；子行程自己也會寫，所以同一件事可能兩筆，但視窗這筆涵蓋子行程來不及寫的失敗（開不起來、被強制結束）。
- 審查（兩軸＋變異）：Standards 無硬違規；採納：抽出 `__main__._warn`（兩處同形的示警迴圈）、選單命令的例外不外漏、`_start_job` 改接所有例外、`_reap_jobs` 註明兩筆紀錄的由來。未採納的判斷題：`_CREATE_NO_WINDOW` 與 `usage_query` 重複（兩處各一行常數，抽共用要動既有模組）、`(args, Job)` 元組（只用在視窗內部）。Spec 九條驗收逐條屬實。變異 13 個，11 個轉紅、2 個全綠（拿掉 `CREATE_NO_WINDOW`、`cwd` 改 `None`：真的子行程測試看不出旗標，pytest 的 cwd 剛好是專案根目錄掩蓋了 cwd）——已補以 mock `Popen` 斷言選項的測試，我重跑這兩個變異確認都轉紅。
- 已知未處理（審查提出，使用者決定）：
  - 子行程 `report` 結束代碼 0 但 `webbrowser.open` 回傳 False 時，只印 stderr，視窗在結束代碼 0 時不讀 stderr，所以使用者點了選單什麼都沒發生、也沒有紀錄。要補的話是子行程在開瀏覽器失敗時也寫錯誤紀錄。
  - 標籤對照的讀改寫沒有鎖（`token-report/11-account-label-gaps`）：每日更新現在也寫對照，視窗啟動那次與使用者同時點選單時，編號撞號的機率比 05 時高一些。
- 真實啟動：在 `pythonw.exe` 下用 `report_jobs.launch(("--no-open",))` 對暫存 home 實測，報表產出、結束代碼 0；瀏覽器實際打開沒有自動化驗證（子行程開瀏覽器的分支只有行程內測試）。

- 2026-10-23：`token-report/11-account-label-gaps` 已搬到 `token-report-backlog/01-account-label-gaps`（內容不變）。
