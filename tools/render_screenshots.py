"""重出 README 用的截圖：docs/images/ 底下六張 PNG（三種版面 × 中英文介面，各一張精簡模式）。

用法（在 repo 根目錄，要在有桌面的 Windows 上跑）：

    python tools/render_screenshots.py

只有這支腳本需要 Pillow（pip install pillow），不是專案依賴；專案本身與測試都不需要它。

做法：用真的版面類別在真的 Tk 視窗上渲染，再用 Pillow 把那塊螢幕區域擷取下來。擷取當下視窗會短暫出現在螢幕左上角，
請不要擋住它。所有資料都寫在這個檔案裡，不讀任何真實檔案、設定或憑證；帳號標籤是一看就知道是範例的名字。
放大成兩倍畫（tk 的縮放比例），README 以一半的寬度顯示，高解析螢幕上才不糊。
"""
import sys
import time
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cc_quota_tracker.board import Board, Card, Limit, ReadingState, Role, Severity  # noqa: E402
from cc_quota_tracker.i18n import EN, ZH_TW  # noqa: E402
from cc_quota_tracker.layout_a import LayoutA  # noqa: E402
from cc_quota_tracker.layout_b import LayoutB  # noqa: E402
from cc_quota_tracker.layout_c import LayoutC  # noqa: E402
from cc_quota_tracker.tokens import TRANSPARENT_KEY  # noqa: E402
from cc_quota_tracker.widget import enable_dpi_awareness  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
THEME = "light"  # 三張一致
ZOOM = 2  # 以 96 DPI 為 1 倍
LAYOUTS = {"cards": LayoutA, "table": LayoutB, "ring": LayoutC}
LANGUAGES = {"en": EN, "zh": ZH_TW}

# 假的「現在」用本機時區的固定時刻：畫面上的時刻（例如 12:15）是轉成本機時區顯示的，這樣在哪個時區跑都一樣
NOW = datetime(2026, 10, 5, 10, 0).astimezone()


def fake_board() -> Board:
    """使用中帳號 work：工作階段用了四成多，週額度已接近上限（紅色）；憑證快照還有 25 天。"""
    work = Card(
        "claude:work", Role.ACTIVE, ReadingState.HAS_READING, reading_age=timedelta(minutes=3),
        limits=(Limit("session", 42, Severity.NORMAL, NOW + timedelta(hours=2, minutes=15)),
                Limit("weekly_all", 88, Severity.CRITICAL, NOW + timedelta(days=2, hours=5))),
        snapshot_expires_at=NOW + timedelta(days=25))
    return Board(cards=(work,), as_of=NOW)


def render(layout_class, lang: str, path: Path) -> None:
    from PIL import ImageGrab  # 只有這支腳本需要

    root = tk.Tk()
    try:
        root.overrideredirect(True)
        root.tk.call("tk", "scaling", ZOOM * 96 / 72)
        root.attributes("-topmost", True)
        canvas = tk.Canvas(root, bg=TRANSPARENT_KEY, highlightthickness=0, borderwidth=0)
        canvas.pack()
        layout = layout_class(canvas)
        layout.render(fake_board(), THEME, False, lang)
        width, height = int(canvas["width"]), int(canvas["height"])
        if width > root.winfo_screenwidth() - 100 or height > root.winfo_screenheight() - 100:
            raise SystemExit(f"螢幕放不下 {width}×{height} 的畫面；把 ZOOM 改成 1 再試")
        root.geometry(f"{width}x{height}+40+40")
        for _ in range(5):  # 讓視窗真的畫完、到最上層，再擷取
            root.update()
            time.sleep(0.1)
        left, top = root.winfo_rootx(), root.winfo_rooty()
        shot = ImageGrab.grab(bbox=(left, top, left + width, top + height)).convert("RGBA")
        layout.destroy()
    finally:
        root.destroy()
    # 圓角外側是透明色鍵的顏色：換成透明，貼在任何底色上都不會留下方框
    key = tuple(int(TRANSPARENT_KEY[i:i + 2], 16) for i in (1, 3, 5))
    shot.putdata([(0, 0, 0, 0) if px[:3] == key else px for px in shot.getdata()])
    shot.save(path)
    print(f"{path.relative_to(OUT.parent.parent)}  {width}×{height}")


def main() -> None:
    enable_dpi_awareness()  # 必須在建立 Tk 之前
    OUT.mkdir(parents=True, exist_ok=True)
    for name, layout_class in LAYOUTS.items():
        for tag, lang in LANGUAGES.items():
            render(layout_class, lang, OUT / f"{name}-{tag}.png")


if __name__ == "__main__":
    main()
