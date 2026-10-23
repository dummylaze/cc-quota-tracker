# 01: 帳號標籤對照的已知缺口

**What to build:** 票 05（帳號標籤對照）結案審查時發現兩個缺口，spec 沒要求、使用者決定先不改，這張票只是記下來。要不要處理、怎麼處理，等實際遇到再分流。

**Blocked by:** None

**Status:** needs-triage

## 缺口

- **同名的兩個帳號**：兩個不同的帳號識別碼用了同一個帳號標籤時（例如舊帳號的憑證快照移除後，同一個標籤被新帳號納管），報表會列出兩欄同名的帳號，只能靠顏色與排序分辨。目前沒有去重或加註。
- **對照的讀改寫沒有鎖**：兩個 `report`（例如選單開報表與每日更新）同時跑時，各自讀到同一份對照、各自寫回，後寫的蓋掉先寫的；兩邊各自替不同的新帳號領了同一個「未監看帳號 n」時，編號會撞號。機率低，帳本本身有跨行程的鎖，對照沒有。

## Acceptance criteria

（待分流後再寫）

## Comments

- 2026-10-22：由 `token-report/05-account-label-mapping` 的審查提出，使用者決定先記下、不改。05 的 Comments 指到這張。
- 2026-10-23：token 報表結案時從 `token-report/11-account-label-gaps` 搬到這個獨立 feature（結案審查前就存在的備忘票，不屬於 token 報表的範圍）；內容不變，仍待分流。舊路徑在 `token-report/05`、`09` 的 Comments 裡已追加指向這裡的註記。
- 2026-10-23：架構審查開了 `.scratch/architecture-review/issues/07-usage-ledger-module.md`（用量帳本收成一個 module），方向包括把對照的讀改寫放進帳本的鎖，可能順帶補上第二個缺口；分流時一起看。
