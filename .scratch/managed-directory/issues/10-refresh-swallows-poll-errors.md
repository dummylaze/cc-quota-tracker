# 10: poll 丟出例外時看板靜默停在最後一次成功的畫面

**What to build:** GUI 每輪 refresh 只有 `try/finally`，poll 丟出任何未預期的例外時，例外跑出 Tk 的回呼（以 `pythonw` 啟動時看不到），排程照樣排下一輪，看板停在最後一次成功的畫面且不顯示任何橫幅。要讓使用者看得出看板已經不在更新。

**Blocked by:** None (can start immediately)

**Status:** needs-triage

- [ ] 實作前與使用者確認：poll 失敗時看板呈現什麼（例如橫幅附上最後一次成功的時間），以及連續幾輪失敗才顯示
- [ ] poll 恢復成功的那一輪，失敗的呈現就消失
- [ ] 例外不再跑出 Tk 的回呼；排程維持「永遠只有一個、出錯也照樣排下一輪」
- [ ] 以注入會丟例外的 poll 驗證上述行為

## Comments

### 來源（2026-10-03）

在 `02-non-acl-filesystem.md` 的 triage 中讀碼發現（未在 GUI 實跑）。不限於權限：任何讓 poll 失敗的例外都會這樣。`08-untightened-warning.md` 完成後，權限這條路徑不再丟到 GUI，但其他例外仍會。
