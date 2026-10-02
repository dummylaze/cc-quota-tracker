# 08: README 雙語更新：查詢額度、設定欄位、適用情境與已知限制

**What to build:** README 英文版與正體中文版（同一次編輯）反映查詢額度：開頭的承諾改成「預設不發任何請求、不修改 Claude Code 設定；只有你按下按鈕或開啟自動查詢時，才會請 Claude Code 代查」；新增一段說明查詢額度的作用、成本與限流風險（打的是與 `/usage` 相同的端點，太頻繁可能被限流，限流期間連自己打的 `/usage` 也會失敗）；設定欄位表加三個新欄位的意義、預設值與下限；〈目前版本的範圍外〉的「任何網路請求」改成與新承諾一致的說法；新增〈適用情境與已知限制〉，寫明本工具是依 Windows、Claude Code（訂閱方案）、對話主要在 VS Code 面板、同一台電腦輪流使用多個帳號這個情境設計與測試，其他情境未測試，並列出已知限制（只能查詢與即時判斷使用中帳號、別的裝置或網頁用掉的額度看不出落後、「更新」只在落後或讀數待更新時出現、依賴未公開欄位與實驗性介面）。

**Blocked by:** `01-usage-query-core.md`、`02-usage-query-cli.md`、`04-manual-query-entry-layout-a.md`、`05-auto-usage-query.md`、`06-query-entry-layouts-b-c.md`、`07-pre-switch-lagging.md`

**Status:** resolved

- [x] 兩個語言版本的內容對應一致，同一次編輯
- [x] 開頭承諾、查詢額度段落、三個欄位的表格、範圍外措辭、〈適用情境與已知限制〉都已更新
- [x] 全文用「查詢額度」，不用「刷新」指這件事
- [x] 不出現任何真實帳號、email、token 片段或本機使用者名稱
- [x] 文字與實作行為逐項對照一致（預設值、下限、冷卻、暫停）

## Comments

- 逐項對照實作的值：預設（`claudeCommand` null、`autoUsageQuery` false、`autoUsageQueryMinutes` 15）、下限 5、手動冷卻 30 秒（右鍵選單共用）、連續 3 次自動查詢失敗暫停（手動失敗不累計）、逾時 20 秒。
- 順手修正既有英文句：把 "new conversation, quota not yet updated" 改成實際文案 "New activity; usage not updated"，"refreshes its cache" 改成 "updates its cache"（避開「刷新」一詞）。
- AI 自補（spec 沒逐項要求，審查判為合理）：開頭功能列表加「查詢額度」、命令列清單加 `query`、右鍵選單加兩項、〈範圍外〉加「查詢待命帳號」、`claudeCommand` 與開機自動啟動只看得到使用者層級 `PATH` 的提醒。
- spec 的「不讀查詢的回應」比實作絕對（實作會讀回應以得知何時關閉輸入與 Claude Code 回報的錯誤），README 改成「不拿回應當資料來源，成敗只看額度快取的觀測時間」，與 ADR-0010 一致。spec 本身不改。
- spec〈測試決策〉的三項手動驗證不屬於本票：真實 Claude Code 按鈕（04 已驗）、開機自動啟動找 `claude`（02 已驗，README 的 `claudeCommand` 說明即其退路）、閒置一小時（05 仍未勾，tracker 的 S5 警告即此）。
