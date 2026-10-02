# 03: 建立納管目錄 module，先搬「上一輪觀測」與「切換紀錄」

**What to build:** 新增納管目錄（Managed Directory）module，並讓每輪 poll 的切換偵測改由它讀寫上一輪觀測、追加切換紀錄。module 內部集中三態讀取（不存在／讀不懂視為空的，讀不到視為「未知」）、原子寫入、暫存檔在替換前收緊權限、目錄先收緊再往裡面寫，以及唯一一套會事後驗證的權限政策。使用者看到的看板、命令列輸出與納管目錄裡的檔案格式都不變。

**Blocked by:** `01-add-remove-binding-guard.md`

**Status:** resolved

- [x] 核心的切換偵測不再直接讀寫上一輪觀測檔與切換紀錄，改呼叫 module 的領域操作
- [x] 三態讀取在 module 內只有一份實作，之後的票（待命讀數、綁定、視窗位置）沿用同一份
- [x] 縫 ④ 測試（暫存目錄裡的真實納管目錄）：觀測檔被鎖住時回傳「讀不到」、內容讀不懂時回傳「沒有」、不存在時回傳「沒有」
- [x] 縫 ④ 測試：切換紀錄只追加，既有行原封不動；寫入失敗時丟出例外、既有內容不變
- [x] 切換紀錄的讀檔黑箱斷言（ADR-0009 的格式契約）保留，不改走 module 的讀取
- [x] 觀測檔與切換紀錄的 Windows 實際權限斷言照舊通過
- [x] 既有縫 ① 測試一行未改、全部通過

## Comments

- 三態讀取的唯一一份是 `managed_directory.py` 內的 `_read_state`。核心的綁定（`_load_bindings`）與待命讀數（`_load_readings`）仍各有一份副本，視窗位置也是；票 04、05、07 搬進 module 時改用 `_read_state` 並刪掉副本。
- 過渡期 module 對外多公開了 `STATE_DIR`、`tighten`、`mkdir_private`、`ManagedDirectory.write_state`，給核心還沒搬的綁定、待命讀數、憑證快照使用；核心的 `_write_state` 只剩一行轉手。這些隨票 04～06 收回 module 內部，檔頭 docstring 有註記。
- 權限政策只有 `tighten` 一套；視窗位置改用它是票 07。
