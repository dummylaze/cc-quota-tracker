# 01: 唯讀取樣，驗證「登入會立刻更新 oauthAccount」的假設

**What to build:** 一支只讀取樣腳本，讓使用者手動切換帳號時，記錄切換前後的身分變化，並量出「讀數待更新」會持續多久。取樣只輸出識別碼的雜湊前綴，不輸出原值，也不寫入 Claude Code 維護的任何檔案。取樣結果決定 refreshToken 輪替判定（切換偵測）能不能照 spec 的假設實作。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] 切換帳號前後各記錄一次：憑證身分鍵、`oauthAccount` 識別碼、額度快取識別碼、各限額狀態，全部只輸出雜湊前綴
- [x] 切換後每分鐘記錄一次，直到額度快取的識別碼翻轉
- [x] 結論寫回 spec〈補充說明〉：`claude login` 是否立刻更新 `oauthAccount`；「讀數待更新」實際持續多久
- [x] 若假設不成立，明確列出對 ticket 06、07 的影響，再開始那兩張
- [x] 取樣紀錄不進 git（含任何可識別身分的值）
