# 02: Tracer：使用中帳號的讀數，從 poll 走到 list

**What to build:** 核心接收 home 目錄與時鐘，讀出本機 Claude Code 維護的額度快取，把使用中帳號的工作階段窗口與週窗口（百分比、重置時間）放進看板，並能用 `list` 在終端機顯示成文字。額度快取不存在時，看板是「尚無讀數」，不告警。同時建立 unittest 與假 home 的測試骨架，之後所有核心票都沿用。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] 核心只提供 poll、add、remove 三個操作；本票只需 poll 有實作
- [x] 解析層是唯一接觸原始資料的地方，對外回傳用量讀數或三類解析結果之一
- [x] 看板只帶語意狀態，不帶文案
- [x] `list` 把看板渲染成文字
- [x] 額度快取不存在 → 「尚無讀數」，不告警
- [x] 測試把 home 指到暫存目錄、由測試控制時鐘，只透過看板與工具狀態目錄觀察外部行為
- [x] 只用標準庫與 unittest
- [x] 不寫入 Claude Code 維護的任何檔案
