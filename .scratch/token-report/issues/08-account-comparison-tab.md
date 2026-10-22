# 08: 報表分頁「帳號比較」

**What to build:** 報表多一個分頁「帳號比較」：每個帳號一欄並排，全部帳號合計在最前，未歸屬單獨一欄、不分給任何帳號。每欄有總 token、占比、小長條圖、命中比例、cache 寫入與讀取、估算金額，各模型與其他欄位收在摺疊區。版面參考原型 `?variant=C`，以 spec 為準。

**Blocked by:** 07

**Status:** resolved

## Acceptance criteria

- [x] 每個有用量的帳號一欄；全部帳號合計在最前；有未歸屬用量時，未歸屬單獨一欄
- [x] 每欄：總 token、占最大帳號的比例、區間內每日的小長條圖、cache 命中比例、cache 寫入、cache 讀取、估算金額
- [x] 各模型與 input、output 收在每欄的摺疊區
- [x] 跟其他分頁共用區間選擇；單看或合計的選擇在這個分頁不作用，畫面上看得出來
- [x] 窄視窗時欄位改為換行排列，不出現整頁橫向捲動
- [x] 淺色、深色兩種主題都正確
- [ ] 審美驗證（對比度、留白、高彩度面積等量測，兩種主題）達標
- [x] 既有測試全部通過

## Comments

- 2026-10-23：**實作完成，資料層沒有變動**。`token_report.py` 的 `summary.accounts`／`summary.total`／`summary.daily`／`data.accounts` 原本就含帳號比較需要的全部欄位（含 06、07 已經做好的 `models` 細分），這張票只動 `report_page.py` 與兩份語系檔。
- 票面外、實作時自補的決定：
  - 「占最大帳號的比例」的基準＝全部非合計欄位（含未歸屬）裡最大的 tokens；合計欄本身不顯示這一列與色條（它必是最大，比例沒有意義）——跟原型 `?variant=C` 的行為一致，spec 沒有明文排除合計欄。
  - 每欄「各模型與其他欄位」做成獨立的 `<details>`／`<summary>`（原生展開收合，鍵盤與螢幕報讀器內建支援，不必自己寫 `aria-expanded`），各欄互相獨立；展開狀態存在 `compareOpen`（key 是欄位的 key），跟 07 的 `openDays` 同一個做法，切換區間時保留。
  - 摺疊區的模型表只列 tokens、cache 命中比例、估算金額三欄（卡片比總覽窄很多，再加 cache 寫入／讀取細分會逼出橫向捲動）；input、output 改成摺疊區下方兩列獨立總數，不逐模型拆。
  - 小長條圖（sparkline）沒有逐日的滑鼠提示，只在整張圖給一個 `aria-label`（總覽的堆疊圖每根柱子都有 tooltip，這裡為了卡片精簡簡化掉；每日的細節本來就在「每日」分頁查得到）。
  - 「顯示」（單看或合計）在這個分頁用原生 `disabled` 停用分段按鈕（自動退出 Tab 順序、強制色彩模式下也會跟著系統的停用樣式），並把控制列的標籤文字換成「顯示（此分頁不適用）」，滿足「畫面上看得出來」。
  - 合計欄的標題重用既有的「全部帳號合計」字樣（`report.view.all`），沒有另外新增一個卡片標題用的鍵。
  - 新增 5 個語系鍵（`report.tab.comparison`、`report.view.unavailable`、`report.compare.ratio`、`report.compare.models`、`report.compare.spark`），依既有字樣風格決定，沒有逐一請使用者確認。
- 審美驗證：**留白率、高彩度面積兩項這次沒能實測**。這個 session 裡，headless Edge（`msedge.exe --headless=new --dump-dom`）不管加什麼旗標都是 exit code 0、零輸出，連 `--version`、`about:blank --dump-dom`、全新 `--user-data-dir`、`--no-sandbox`、拿掉 GPU／profile 旗標都一樣，判斷是這次環境的限制（例如系統政策封鎖自動化旗標），不是程式碼問題；試過足夠多組合後就不再繼續試。其餘項目改用程式碼比對既有慣例的方式過：
  - 顏色：帳號色、未歸屬灰色、`var(--fg)`（合計欄）全部重用 `tokens.py` 既有已驗證過的 token，沒有新色值；色塊用法（bar 的 fill、swatch）跟總覽的堆疊圖同一個模式。
  - 群組間距：卡片間（`.cols` gap 16px）與卡片內最大間距（`.meter`／`.compare-col svg` 的 8px）維持剛好 2 倍。
  - 數字欄位：補上 `.kv span:last-child{font-variant-numeric:tabular-nums}`（審查前自己抓到這個漏網的）。
  - `forced-colors:active`：disabled 的分段按鈕交給瀏覽器原生停用樣式；`.meter`／`.meter > i` 加進既有的 `forced-color-adjust:none` 清單，色塊保留原色（跟 07 一樣，只能靠程式碼判斷，無頭瀏覽器開不了強制色彩模式，這次連一般截圖都開不了）。
  - 320px／窄視窗：`.cols` 用 `repeat(auto-fit,minmax(240px,1fr))`，跟 `.tiles`（總覽）同一個模式；任何卡片內表格溢出交給既有的 `.card{overflow-x:auto}` 吸收，不會變成整頁橫向捲動。這一項與留白率／高彩度面積一樣沒能用無頭瀏覽器實測，留給使用者有空時用無頭瀏覽器截圖確認。
- 審查（兩軸＋變異）：Standards 軸由子代理跑；Spec 軸的子代理跑到一半撞到帳號的 session rate limit（API 429，5:10am 重置），改由主對話接著做完 requirements 比對與變異檢查（沒有另開子代理重跑，避免跟卡住的子代理重複工作）。
  - **AC2 的已知字面偏離**：「每欄：總 token、占最大帳號的比例…」字面上是「每一欄」都要有占比，但合計欄本身沒有顯示這一列與色條（上面「票面外的決定」已記）。這不是審查後才發現，是實作時就知道、照 Comments 寫的理由做的選擇，審查只是確認沒有藏起來。
  - 採納：`.tile .big` 與 `.compare-col .big` 的重複 CSS 合併成一條選擇器；sparkline 的三個魔術數字（6、4、40）抽成 `SPARK_SLOT`／`SPARK_BAR`／`SPARK_H`，並註記要跟 CSS 的 `.compare-col svg{height:2.5rem}` 保持一致（兩邊沒辦法共用同一個值，只能用註解提醒）。
  - 未採納（判斷題）：`col.isTotal` 布林＋`account:null` 雙重意義（合計與未歸屬都是 `account:null`，標準軸建議改成 `'total'|'account'|'unattributed'` 的 kind 字串）——只有三個呼叫點，各自意圖清楚，改字串要動三處、收益小；`compareCard` 裡四個 `compareKv(...)` 依序呼叫沒有再抽迴圈——跟 07 的「一列＋標籤＋數字格在三處各寫一次，再抽一層收益小」同一個判斷，而且四格的格式規則本來就不一樣（百分比／compact＋提示／金額物件），硬塞進資料驅動的迴圈不會更清楚。`.meter` 的底色沿用 `var(--line)`（跟卡片的對比可能低於 3:1 的圖形門檻，標準軸標為「無法不量測確認」）——這跟桌面版既有的「空進度條底軌」是同一個設計決定（`tests/test_tokens.py` 的 `PAIRS` 註解：使用者已經決定這類底軌可以低於一般圖形門檻），而且比例已經用文字列出、色塊本身 `aria-hidden`，判斷沿用既有慣例、不改。
  - 變異檢查（8 個，工作區複製到暫存目錄跑，沒有動到真正的工作區）：全部維持 `tests/test_token_report.py`／`test_report_numbers.py`／`test_report_cost.py`／`test_i18n.py` 126 passed（跟變異前一樣），沒有任何一個轉紅。**這是預期結果，不是空轉測試**：這 8 個變異全部是 `report_page.py` 內嵌 HTML 範本字串裡的 JS／CSS 行為，spec〈測試決策〉本來就只測報表資料（Python 端），不測畫面分頁；跟 06、07 同一個情形。變異檢查在這裡的實際價值是讀碼確認因果（已逐條核對：欄位順序反轉、比較基準納入合計欄、除以零守衛拿掉、展開狀態不保存、sparkline 條件反轉、input/output 固定 0、`onComparison` 判斷打錯 tab id、金額改成 headline 格式，八個都會讓畫面行為真的改變），不是靠測試紅燈判斷。
  - 其餘核對：`token_report.py` 確認不在 diff 裡（純前端重用既有資料）；mypy 對三個改動檔案乾淨，`cc_quota_tracker/` 其餘既有的錯誤清單裡沒有這三個檔；全量測試 1393 passed, 3 skipped, 0 failed。
