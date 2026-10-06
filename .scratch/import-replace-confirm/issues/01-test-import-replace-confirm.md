# 01: 補測試：匯入憑證檔時，標籤與既有監看帳號同名要先確認

**What to build:** 右鍵選單「匯入憑證檔…」在標籤與既有監看帳號同名（Windows 檔名不分大小寫，所以不分大小寫比對）時，會先問「要用這個檔案取代它的憑證快照嗎？」，使用者回答否就什麼都不寫。這段守衛（`cc_quota_tracker/widget.py` 的 `import_credential_file`）目前完全沒有測試：把「已存在標籤」的集合換成空集合、整段確認被繞過，全套測試仍然全綠。只補測試，不改程式行為。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 標籤與既有監看帳號同名時，匯入前會顯示確認對話框，內容含該標籤
- [x] 使用者回答「否」：不匯入，既有的憑證快照與綁定位元組完全不變，也不顯示成功訊息
- [x] 使用者回答「是」：匯入並取代該帳號的憑證快照，顯示成功訊息
- [x] 同名只差大小寫（例如既有 `work`、輸入 `Work`）也要確認
- [x] 標籤沒有同名時不跳確認對話框
- [x] 測試走「視窗＋真的核心」這層，用假 home 與假憑證；沿用 `tests/test_widget.py` 的 `ManageAccountsTest`（它已經有「匯入」的前例，但只驗綁定檔被鎖的錯誤）
- [x] 補完後自己做一次變異確認有鑑別力：把 `import_credential_file` 的已存在標籤集合改成空集合，至少一個新測試要轉紅（做完還原，不留在 commit 裡）
- [x] 不改任何程式行為：`cc_quota_tracker/` 底下沒有任何改動

## Comments

- 缺口的來源：審查另一張票（`account-switch/01-rename-watched-unwatched-active.md`）時，變異檢查發現這段守衛沒有測試。與那張票的改名無關，所以另開票，不併進去。
- 結案說明：新增 `tests/test_widget.py` 的 `ImportReplaceConfirmTest`（5 條）。變異（把已存在標籤集合改成空集合）使其中 3 條轉紅，已還原；審查另做 9 個變異（拿掉不分大小寫、取反確認結果、「否」之後仍匯入、確認／成功訊息不含標籤、永遠詢問、匯入時改標籤）皆有測試轉紅。`cc_quota_tracker/` 沒有任何改動。
