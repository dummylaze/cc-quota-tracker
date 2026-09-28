# Python 標準庫＋純 tk，記憶體上限列為驗收項

這個懸浮視窗要全天候常駐，所以選擇 Python 標準庫加上純 `tk` widget 與 Canvas，執行期不依賴任何 pip 套件，以 `pythonw` 啟動。記憶體上限是驗收項：展開模式、顯示所有帳號卡片時，Private Memory ≤ 20 MB、WorkingSet ≤ 35 MB。為了守住這個上限，**刻意不用** `tkinter.ttk`（主題引擎較重）和 Pillow（光是拿來做進度條反鋸齒就會多 15–20 MB）；進度條用 Canvas 的矩形自己畫。

## Considered Options

- **Electron／Tauri 之類的 web 殼**：Electron 常駐約 150–300 MB，對一個只顯示幾條進度條的視窗來說代價太高。
- **.NET（WinForms／WPF）**：執行時本身就佔 25–40 MB，而且會把工具綁死在 Windows，以後要支援 macOS／Linux 就走不通。

## Consequences

常駐時間長，洩漏會一路累積。畫面更新一律改寫既有 Canvas item 的屬性，不重建；驗收指標是「重複更新 N 輪之後 Canvas item 數量不變」，比觀察記憶體曲線靈敏。
