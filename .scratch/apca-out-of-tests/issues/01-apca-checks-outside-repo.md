# 01: token 測試只量 WCAG，APCA 目標改在 repo 外量

**What to build:** `tests/test_tokens.py` 原本自帶一份 APCA-W3 的 Lc 實作，用來驗 `.scratch/m1-readonly-monitor/spec.md`〈畫面層〉配色規則裡的 APCA 目標。APCA-W3 的授權（https://github.com/Myndex/apca-w3 的 LICENSE.md）只允許用在網頁內容的 WCAG 對比預測，不涵蓋桌面程式，也不適合放在公開 repo 裡散布。改成：token 測試只守 WCAG 下限；`PAIRS` 照舊列出每一組「前景＋它實際畫在上面的底色」與兩個門檻（WCAG 下限、APCA 目標），APCA 目標由維護者在 repo 外的量測工具讀同一份 `PAIRS` 量。spec 的配色規則不變：APCA 仍是設計目標，只是不再由公開測試執行。

**Category:** chore

**Blocked by:** None (can start immediately)

**Acceptance criteria:**

- [x] `tests/test_tokens.py` 不含 APCA 的實作與測試；WCAG 的逐對測試照舊，兩套主題都量
- [x] `PAIRS` 與門檻常數保留 APCA 目標值，檔頭註解說明 APCA 改在 repo 外量
- [x] repo 外的 APCA 檢查讀同一份 `PAIRS`，兩套主題全部通過
- [x] 全套測試通過

**Status:** resolved

## Comments

- 2026-10-23：在 commit `92ef911` 完成（先改後補票）。全套測試 1394 項通過（略過 3 項）；repo 外的 APCA 檢查 58／58 對通過。舊的實作仍留在 git 歷史裡，沒有改寫歷史。
