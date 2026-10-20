# 10: README：token 報表

**What to build:** 架設者與使用者能從 README 讀到 token 報表怎麼打開、數字從哪裡來、帳本放在哪裡、未歸屬是什麼意思、金額只是估算。英文與正體中文兩版在同一次編輯一起改。

**Blocked by:** 08, 09

**Status:** ready-for-agent

## Acceptance criteria

- [ ] 入口：右鍵選單「token 報表」與命令列 `report`、`report --no-open`
- [ ] 資料來源：Claude Code 的對話紀錄；本工具每天把用量記進用量帳本，Claude Code 刪掉舊紀錄後仍保留；帳本與報表 HTML 各放在哪裡
- [ ] 未歸屬時段的意思，以及切換紀錄開始之前、開始記錄上一次運作時間之前的限制
- [ ] cache 命中比例的算法；金額依內建單價表估算、可能過時，未知模型不計金額
- [ ] 報表不連網、不需要另外安裝任何東西
- [ ] 英文與正體中文兩版內容一致，既有的 README 檢查測試通過

## Comments
