"""設計 token：兩套主題的顏色、字型、字級、圓角、間距都在這裡。版面只引用 token，不寫死數值。

長度一律以 96 DPI 的像素為準，由版面乘上螢幕的縮放比例；字級是點數，tk 會自己依 DPI 換算。"""

# 透明色鍵：視窗底色設成它、再宣告為透明色，圓角外側就被挖空。不可與任何主題色相同
TRANSPARENT_KEY = "#010203"

# 以角色命名：一個 token 只用在它的角色，不因為色值剛好合適就借用；配色規則見 spec〈畫面層〉，tests/test_tokens.py 逐對量對比
THEMES = {
    "light": {
        "panel": "#eeeeeb", "card": "#ffffff", "shadow": "#dcdcd7",
        "fg": "#1d1d1f", "sub": "#6b6b70",
        "track": "#e1e1dd",  # 進度條底軌
        "neutral": "#80807d",  # 中性資訊的進度條填色（週窗口已過 %、額外用量）
        "accent": "#3b6fd8",  # 只代表使用中帳號：外框、使用中標籤；另用於未納管提示的色點
        "chip_active_fg": "#ffffff",  # 使用中標籤的文字，畫在 accent 上
        "chip_standby": "#ebebe7", "chip_standby_fg": "#6a6a6f",  # 待命標籤的底色與文字
        "normal": "#118246", "warning": "#916c00", "critical": "#cd3c3e",
        "banner": "#fbecc8", "banner_fg": "#5c4300",
        "active_row": "#f5f7fd",  # 版面 B 展開時使用中帳號那一列的淡色底；列上的文字與圖形對它另外量
    },
    # 深色不是淺色的反轉：每一對另外量過，對比不足時只調明度、保持色相
    "dark": {
        "panel": "#1d1d21", "card": "#26262a", "shadow": "#101013",
        "fg": "#ececec", "sub": "#b6b6be",
        "track": "#5a5a60",
        "neutral": "#ababb2",
        "accent": "#89affe",
        "chip_active_fg": "#0f1420",
        "chip_standby": "#34343a", "chip_standby_fg": "#bcbcc4",
        "normal": "#54cc86", "warning": "#f0c030", "critical": "#fe9b97",
        "banner": "#3d3218", "banner_fg": "#f5dc9a",
        "active_row": "#1e2130",  # 比卡片暗：提亮會讓 sub 與嚴重度文字跌破 Lc 60
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

# 多行文字的行高（行距 ÷ 字級像素）。tk 的 canvas 文字沒有行距選項，版面把多行文字拆成逐行 item 自己排
LINE_HEIGHT = 1.5

# 巢狀圓角同心：外層圓角＝內層圓角＋兩者之間的內距（panel 對 card 隔著 panel_pad；card 對版面 B 的列底色、版面 C 使用中格的外框隔著 row_inset）
RADIUS = {"panel": 18, "card": 6, "chip": 9, "row": 2, "cell": 2}  # cell：版面 C 使用中帳號那一格的外框

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
    # 版面 B：單行條的各段、表格的各欄
    "col_gap": 14,  # 欄與欄、單行條的段與段之間
    "cell_gap": 6,  # 同一段內：窗口名稱、進度條、百分比之間
    "cell_bar_width": 64,  # 單行條與表格裡的小進度條
    "row_pad_y": 8,  # 表格每一列（連同它的提示）上下的內距
    "row_inset": 4,  # 版面 B 的列底色、版面 C 使用中格的外框，與卡片邊緣的距離
    # 版面 C：環形儀表。一個帳號一格，展開模式每列三格
    "ring_size": 84,  # 外圈的外徑
    "ring_stroke": 8,  # 圈的線寬
    "ring_gap": 3,  # 外圈與內圈之間
    "ring_cell_width": 104,  # 一格的寬度（使用中帳號的外框就框住這一格）
    "ring_cell_pad": 8,  # 格內上下左右的內距
    "ring_compact_width": 256,  # 精簡模式格子區的寬度：一格置中，提示在它的內距之內折行
}
