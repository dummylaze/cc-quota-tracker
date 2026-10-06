# 08: 還原上一次切換與 `switch --previous`

**What to build:** 核心新增「還原上一次切換」入口：用切換前憑證把當前憑證和帳號資訊一起回到切換之前的狀態。還原本身也是一次切換，同樣會保存當下的憑證，所以再還原一次會回到剛才的帳號。切換前登入的是未監看帳號時，也能用還原回去，不必重新登入。命令列新增 `switch --previous`。

**Blocked by:** 06

**Status:** resolved

- [x] 沒有切換前憑證、或它已過期 → 拒絕，當前憑證與 Claude Code 設定檔的位元組完全不變；命令列結束代碼 1
- [x] 還原後，當前憑證與帳號資訊都回到切換前；Claude Code 設定檔只改帳號資訊那一個鍵，其他鍵逐字保留
- [x] 還原前先同步，並保存當下的憑證成為新的切換前憑證：連續還原兩次會回到還原之前的帳號
- [x] 切換前是未監看帳號 → 還原後回到它
- [x] 還原也追加切換紀錄，跟其他切換一樣，之後的 poll 不重複記
- [x] 寫入後替新帳號查詢額度的行為跟一般切換相同（含驗證失敗的結束代碼 3）
- [x] 命令列 `switch --previous --yes`；沒帶 `--yes` 時跟 `switch <帳號標籤>` 一樣處理
- [x] `--help` 的用法說明加上 `switch --previous`

## Comments

### 依賴補記（2026-10-05，切票時記）

「寫入後查詢額度、驗證失敗回 3」這一項沿用 `07-switch-queries.md` 的做法。如果本票先做、07 還沒完成，這一項委派給 07 驗證，07 結案時回頭勾選。

### 來自 06（2026-10-06）

切換前憑證存在納管目錄的 `.state/pre-switch.json`，格式 `{"credentials": <當前憑證原文>, "accountInfo": <帳號資訊或 null>}`，由 `ManagedDirectory.save_pre_switch` 寫入（`06-switch-core-and-cli.md`）。還原要寫回的是 `credentials` 原文，帳號資訊照 06 的做法只換 `oauthAccount` 一個鍵（`claude_provider.with_account_info`）。

### 來自 07（2026-10-06）

`Core.switch` 現在會替舊帳號、新帳號各查一次額度（`07-switch-queries.md`）。還原也是一次切換，要沿用同一套：結果值多了 `SwitchOutcome.VERIFY_FAILED`、`old_account_query_failed`、`verify_failure`；命令列「已寫入但驗證失敗」的訊息在 07 沒有提還原指令（當時 `switch --previous` 還不存在），本票做完後補上。舊帳號查詢之後要重讀當前憑證並再同步一次，再保存切換前憑證（查詢可能順便刷新憑證）；還原的路徑如果自己寫入當前憑證，也要注意這一點。

### 實作補記（2026-10-06）

- 核心入口是 `Core.restore_previous(on_step=None)`，跟 `Core.switch` 共用同一條流程（同步、查舊帳號、保存切換前憑證、寫入、記紀錄、查新帳號），只有「怎麼檢查目標」與「寫進去的憑證與帳號資訊從哪來」不同。
- 新增兩個拒絕原因：`SwitchRefusal.NO_PREVIOUS`（沒有切換前憑證、檔案讀不懂、或當時的帳號資訊是空的）、`PREVIOUS_EXPIRED`（切換前憑證的 refreshToken 已過期；沒寫到期時間不算過期，同憑證快照的判法）。切換前憑證檔讀不到（被鎖住）是 `UNREADABLE`。
- 與使用者確認：切換前的帳號資訊是空的時，**拒絕還原**（視同沒有可還原的切換前憑證），不寫任何檔；只還原憑證會讓帳號資訊錯配。
- 命令列：`switch --previous --yes`，結束代碼與 `switch <帳號標籤> --yes` 同一套；07 留下的「已寫入但驗證失敗」訊息已補上還原指令。
- 給 `10-gui-switch-menu.md`、`12-gui-restore.md`：子選單「還原上一次切換」要不要反灰，可以直接問核心（沒有切換前憑證、過期、帳號資訊空的都是反灰），但目前核心沒有不寫檔的探測入口；做 12 時再決定是加入口，還是讓畫面依 `restore_previous` 的拒絕結果呈現。
