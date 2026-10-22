# 07: 報表分頁「每日明細」

**What to build:** 報表多一個分頁「每日明細」：一張按日的表，點日期展開各模型，最後一列是區間合計。共用總覽建好的區間與單看或合計的選擇。版面參考原型 `?variant=B`，以 spec 為準。

**Blocked by:** 06

**Status:** ready-for-agent

## Acceptance criteria

- [ ] 每一列是一天（本機日），欄位：合計 token、cache 寫入、cache 讀取、命中比例、input、output、金額
- [ ] 點日期展開該日各模型的列，再點收合
- [ ] 最後一列是區間合計
- [ ] 合計時，有未歸屬用量的日子在該列註明未歸屬的量
- [ ] 跟總覽共用區間與單看或合計的選擇
- [ ] 淺色、深色兩種主題都正確
- [ ] 頁面層級的網頁規範，整個頁面（含總覽）一併處理：
  - 強制色彩模式（`forced-colors: active`）下，選中的按鈕與分頁仍分辨得出來，不只靠背景色
  - 非緊急的示警橫幅用 `role="status"`，`role="alert"` 只給緊急錯誤
  - 分頁列可用方向鍵切換，分頁與面板以 `aria-controls`／`aria-labelledby` 關聯
  - 內文字級用 `rem`；標題用 `text-wrap: balance`、附註段落用 `text-wrap: pretty`
  - 按鈕的 hover 回饋包在 `@media (hover: hover)`
  - 視窗寬 320px 與縮放 200% 時，頁面本身沒有橫向捲動、內容不裁切（圖表與表格在自己的容器內捲動不算）
- [ ] 審美驗證（對比度、留白、高彩度面積等量測，兩種主題）達標
- [ ] 既有測試全部通過

## Comments
