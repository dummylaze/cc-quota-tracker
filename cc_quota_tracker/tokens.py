"""設計 token：兩套主題的顏色、字型、字級、圓角、間距都在這裡。版面只引用 token，不寫死數值。

長度一律以 96 DPI 的像素為準，由版面乘上螢幕的縮放比例；字級是點數，tk 會自己依 DPI 換算。"""

# 透明色鍵：視窗底色設成它、再宣告為透明色，圓角外側就被挖空。不可與任何主題色相同
TRANSPARENT_KEY = "#010203"

THEMES = {
    "light": {
        "panel": "#eeeeeb", "card": "#ffffff", "shadow": "#dcdcd7",
        "fg": "#1d1d1f", "sub": "#6b6b70", "track": "#e1e1dd",
        "accent": "#3b6fd8", "chip_fg": "#ffffff",
        "normal": "#2e9d5b", "warning": "#c99500", "critical": "#d64545",
        "banner": "#fbecc8", "banner_fg": "#5c4300",
    },
    "dark": {
        "panel": "#1d1d21", "card": "#26262a", "shadow": "#101013",
        "fg": "#ececec", "sub": "#9a9aa2", "track": "#3a3a40",
        "accent": "#6d9bff", "chip_fg": "#0f1420",
        "normal": "#4cc47f", "warning": "#f0c030", "critical": "#ff6b6b",
        "banner": "#3d3218", "banner_fg": "#f5dc9a",
    },
}

# (字型家族, 字級, 粗細)
FONTS = {
    "title": ("Microsoft JhengHei UI", 12, "bold"),
    "chip": ("Microsoft JhengHei UI", 8, "bold"),
    "body": ("Microsoft JhengHei UI", 9, "normal"),
    "small": ("Microsoft JhengHei UI", 8, "normal"),
    "percent": ("Segoe UI Semibold", 13, "bold"),
}

RADIUS = {"panel": 16, "card": 12, "chip": 9}

SPACE = {
    "panel_pad": 12,  # 視窗邊緣到卡片
    "card_width": 300,
    "card_pad_x": 16,
    "card_pad_top": 14,
    "card_pad_bottom": 10,
    "shadow_offset": 2,
    "card_gap": 10,  # 展開模式卡片之間
    "highlight": 2,  # 使用中帳號卡片的外框線寬
    "banner_pad": 10,
    "chip_gap": 10,  # 帳號標籤與狀態標籤之間
    "chip_pad_x": 7,
    "chip_height": 18,
    "section_gap": 10,  # 標題列與第一個窗口、窗口與窗口之間
    "bar_gap": 4,  # 窗口名稱列與進度條之間
    "bar_height": 7,
    "line_gap": 3,  # 同一區塊內的文字列之間
    "dot": 6,  # 提示前的嚴重度色點直徑
    "dot_gap": 6,
}
