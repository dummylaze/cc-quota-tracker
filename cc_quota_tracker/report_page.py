"""token 報表的 HTML：單一檔案，樣式與腳本都內嵌，不載入任何外部資源，不自動刷新。

畫面全部由內嵌的報表資料（JSON）算出；頁面的文字依語系放在另一份內嵌的 JSON，腳本只取字串、不寫死任何語言。
顏色沿用視窗的 token（tokens.THEMES），跟著系統的淺色／深色。"""
import json
import re

from . import i18n
from .tokens import ACCOUNT_COLORS, FONTS, THEMES

REPORT_FILE = "token-report.html"  # 放在設定檔所在的目錄，每次覆寫

# 頁面文字：腳本用的名稱 → 語系鍵。{n}、{date} 留給腳本填
_PAGE_TEXT = {
    "title": "report.title",
    "generatedAt": "report.generated_at",
    "ledgerUpdatedAt": "report.ledger.updated_at",
    "ledgerNever": "report.ledger.never",
    "earliest": "report.ledger.earliest",
    "range": "report.range",
    "range.7d": "report.range.7d",
    "range.30d": "report.range.30d",
    "range.all": "report.range.all",
    "tab.overview": "report.tab.overview",
    "tab.daily": "report.tab.daily",
    "view": "report.view",
    "view.all": "report.view.all",
    "units": "report.units",
    "tileTokens": "report.tile.tokens",
    "tileCacheSplit": "report.tile.cache_split",
    "tileHitFormula": "report.tile.hit_formula",
    "tileCostBasis": "report.tile.cost_basis",
    "tileCostPartial": "report.tile.cost_partial",
    "chartDaily": "report.chart.daily",
    "chartTip": "report.chart.tip",
    "models": "report.models",
    "daily": "report.daily",
    "dayCol": "report.col.day",
    "model": "report.col.model",
    "tokens": "report.col.tokens",
    "cacheWrite": "report.col.cache_write",
    "columnsMore": "report.columns.more",
    "columnsFewer": "report.columns.fewer",
    "input": "report.col.input",
    "output": "report.col.output",
    "cacheWrite5m": "report.col.cache_write_5m",
    "cacheWrite1h": "report.col.cache_write_1h",
    "cacheRead": "report.col.cache_read",
    "cacheHitRatio": "report.col.cache_hit",
    "total": "report.row.total",
    "unattributed": "report.row.unattributed",
    "empty": "report.empty",
    "cacheNote": "report.cache_note",
    "unattributedNote": "report.unattributed_note",
    "downtimeSince": "report.note.downtime_since",
    "downtimeNever": "report.note.downtime_never",
    "pricesVersion": "report.prices.version",
    "cost": "report.col.cost",
    "costNote": "report.cost_note",
    "costPartial": "report.cost.partial",
    "costExcludes": "report.cost.excludes",
    "listSep": "report.list_sep",
}
# 示警的種類（報表資料 notices[].kind）→ 語系鍵
NOTICE_KEYS = {
    "schemaMismatch": "report.notice.schema_mismatch",
    "transcriptUnreadable": "report.notice.transcript_unreadable",
    "switchLogUnreadable": "report.notice.switch_log_unreadable",
    "switchLogSkipped": "report.notice.switch_log_skipped",
    "ledgerUpdateFailed": "report.notice.ledger_failed",
    "ledgerSkipped": "report.notice.ledger_skipped",
    "labelsUnavailable": "report.notice.labels_unavailable",
    "costUnknown": "report.notice.cost_unknown",
}
_HOLES = {name: "{" + name + "}" for name in ("n", "date", "reason", "cost", "read", "write", "day", "account")}  # 讓 text() 把佔位符原樣留下，由腳本填


def notice_text(lang: str, notice: dict) -> str:
    """命令列印到 stderr 的示警；與頁面橫幅是同一份語系文字。"""
    return i18n.text(lang, NOTICE_KEYS[notice["kind"]], n=notice.get("count", ""), reason=notice.get("reason", ""))


def render(data: dict, lang: str) -> str:
    texts: dict = {name: i18n.text(lang, key, **_HOLES) for name, key in _PAGE_TEXT.items()}
    texts["notices"] = {kind: i18n.text(lang, key, **_HOLES) for kind, key in NOTICE_KEYS.items()}
    values = {"LANG": lang, "TITLE": i18n.text(lang, "report.title"), "THEMES": _theme_css(),
              "DATA": _json(data), "TEXTS": _json(texts)}
    # 一次代換：資料裡剛好出現 {{TEXTS}} 之類的字樣，也不會被當成佔位符再換一次
    return re.sub(r"\{\{([A-Z]+)\}\}", lambda m: values[m.group(1)], _PAGE)


def _json(value) -> str:
    # 放進 <script> 的 JSON：< 一律跳脫，資料裡出現 </script> 或 <!-- 也跳不出去
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")


def _theme_css() -> str:
    def block(theme):
        t = THEMES[theme]
        accounts = "".join(f"--{role}:{t[role]};" for role in ACCOUNT_COLORS)
        return (f"--panel:{t['panel']};--card:{t['card']};--fg:{t['fg']};--sub:{t['sub']};"
                f"--banner:{t['banner']};--banner-fg:{t['banner_fg']};{accounts}--unattributed:{t['unattributed']};")
    family = FONTS["body"][0]
    return (f':root{{--font:"{family}","Segoe UI",system-ui,sans-serif;}}'
            f":root{{{block('light')}}}"
            f"@media (prefers-color-scheme:dark){{:root{{{block('dark')}}}}}")



# 腳本裡的 — 等跳脫序列要原樣留給 JavaScript，所以整頁用 raw 字串
_PAGE = r"""<!doctype html>
<html lang="{{LANG}}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}}</title>
<style>
{{THEMES}}
:root{--text-xs:.75rem;--text-sm:.8125rem;--text-md:.875rem;--text-base:.9375rem;--text-title:1.375rem;--text-display:1.75rem;  /* 字級只有這幾階，依用途命名；rem 跟著使用者設定的字級 */
  color-scheme:light dark;--line:color-mix(in srgb,var(--fg) 14%,transparent)}  /* 線不另立顏色，由文字色淡化而來 */
*{box-sizing:border-box}
body{margin:0;background:var(--panel);color:var(--fg);font:var(--text-base)/1.6 var(--font)}
main{max-width:1040px;margin:0 auto;padding:32px 16px 48px}
h1{margin:0 0 4px;font-size:var(--text-title);line-height:1.2;font-weight:700;text-wrap:balance}
h2{margin:0 0 8px;font-size:var(--text-base);line-height:1.3;font-weight:700;text-wrap:balance}
.meta{margin:0 0 24px;color:var(--sub);font-size:var(--text-sm);text-wrap:pretty}
.banners{display:grid;gap:8px;margin:0 0 24px}
.banner{margin:0;padding:12px 16px;border-radius:8px;background:var(--banner);color:var(--banner-fg);font-size:var(--text-md);text-wrap:pretty}
button{font:inherit;color:inherit;cursor:pointer}
.tabs button,.seg button,.day{white-space:nowrap}  /* 標籤不斷行 */
button:focus-visible{outline:2px solid var(--fg);outline-offset:2px}
.tabs{display:flex;gap:8px;margin:0 0 16px;border-bottom:1px solid var(--line)}
.tabs button{margin-bottom:-1px;padding:8px 16px;background:none;border:0;border-bottom:1px solid transparent;
  color:var(--sub);font-size:var(--text-base)}
.tabs button[aria-selected=true]{color:var(--fg);font-weight:700;border-bottom-color:var(--fg)}
.controls{display:flex;flex-wrap:wrap;align-items:center;gap:8px 24px;margin:0 0 24px}
.group{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.group > span{color:var(--sub);font-size:var(--text-sm)}
.seg{display:inline-flex;flex-wrap:wrap;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--card)}
.seg button{display:inline-flex;align-items:center;gap:8px;padding:4px 12px;background:none;border:0;font-size:var(--text-md)}
.seg button + button{border-left:1px solid var(--line)}
.seg button[aria-pressed=true]{background:var(--fg);color:var(--panel)}
.swatch{display:inline-block;width:10px;height:10px;border-radius:2px;flex:none}
.stack > * + *{margin-top:24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;overflow-x:auto}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.tile .label{color:var(--sub);font-size:var(--text-sm)}
.tile .big{margin:4px 0;font-size:var(--text-display);line-height:1.2;font-weight:700;font-variant-numeric:tabular-nums}
.tile .sub{color:var(--sub);font-size:var(--text-sm);text-wrap:pretty}
svg{display:block;width:100%;height:auto;min-width:560px}
svg text{fill:var(--sub);font-size:var(--text-xs);font-family:var(--font)}
svg .grid{stroke:var(--line);stroke-width:1}
.legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin:8px 0 0;color:var(--sub);font-size:var(--text-sm)}
.legend span{display:inline-flex;align-items:center;gap:8px}
table{width:100%;border-collapse:collapse;font-size:var(--text-md)}
th,td{padding:12px 8px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
th{color:var(--sub);font-size:var(--text-sm);font-weight:600;white-space:normal;word-break:keep-all;vertical-align:bottom}
th:first-child,td:first-child{text-align:left;padding-left:0}  /* 表的左右邊與卡片內的標題對齊 */
th:last-child,td:last-child{padding-right:0}
td{font-variant-numeric:tabular-nums}
tr.total td{font-weight:700;border-bottom:0}
.toggle{margin:8px 0 0;padding:4px 0;background:none;border:0;color:var(--sub);font-size:var(--text-sm);text-decoration:underline}
.daily td:first-child,.daily th:first-child{position:sticky;left:0;background:var(--card)}  /* 窄視窗時表在卡片內橫向捲動，日期欄留在左邊 */
.day{display:inline-flex;align-items:center;gap:.5rem;padding:4px 0;background:none;border:0;font-variant-numeric:tabular-nums}
.day-text{text-decoration:underline;text-decoration-color:var(--sub);text-underline-offset:.25rem}  /* 底線與前面的 ▸ 讓日期看得出能點 */
.chev{display:inline-block;width:1rem;text-align:center;color:var(--sub)}
.day-note{display:block;padding-left:1.5rem;color:var(--sub);font-size:var(--text-sm)}
tr.model td{color:var(--sub)}
tr.model td:first-child{padding-left:1.5rem}
.empty{margin:0;padding:24px 8px;color:var(--sub);text-wrap:pretty}
.notes{margin:24px 0 0;display:grid;gap:8px}
.notes p{margin:0;color:var(--sub);font-size:var(--text-sm);text-wrap:pretty}
.banner,.notes p,.tile .sub{overflow-wrap:break-word}  /* 橫幅與附註可能帶長的模型名稱或原因 */
@media (hover:hover){  /* 滑鼠才有的回饋；觸控裝置上 hover 會黏住 */
  .tabs button:hover,.toggle:hover,.day:hover{color:var(--fg)}
  .seg button[aria-pressed=false]:hover{background:var(--line)}
}
@media (forced-colors:active){  /* 背景會被拿掉：選中的靠系統色加粗體與底線分辨，色塊保留原色 */
  .tabs button[aria-selected=true]{text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:.5rem}
  .seg button[aria-pressed=true]{background:Highlight;color:HighlightText;forced-color-adjust:none;font-weight:700;text-decoration:underline}
  .swatch,svg rect{forced-color-adjust:none}
}
</style>
</head>
<body>
<main>
<h1 id="title"></h1>
<p class="meta" id="meta"></p>
<div class="banners" id="banners"></div>
<div class="tabs" role="tablist" id="tabs"></div>
<div class="controls" id="controls"></div>
<div id="panel" role="tabpanel"></div>
<div class="notes" id="notes"></div>
</main>
<script type="application/json" id="report-data">{{DATA}}</script>
<script type="application/json" id="report-texts">{{TEXTS}}</script>
<script>
/* compact:start */
// 大數字換單位。spec 是語系檔的「大小:單位」清單（小的在前）；小於最小單位的整數照原樣顯示，
// 其餘取三位有效數字（1.23、12.3、123，不再帶小數的整數放千分位）。進位後剛好湊滿下一個單位時改用下一個。
// trim：座標軸的刻度本來就是整齊的數字，去掉尾端的 0（1 億，不是 1.00 億）
function makeCompact(spec, language, trim) {
  var units = spec.split(',').map(function (entry) {
    var cut = entry.indexOf(':');
    return { size: Number(entry.slice(0, cut)), label: entry.slice(cut + 1) };
  });
  function digitsOf(value) { return value < 10 ? 2 : value < 100 ? 1 : 0; }
  function scaled(n, unit) {
    var value = n / unit.size;
    var digits = digitsOf(value);
    var rounded = Number(value.toFixed(digits));
    digits = Math.min(digits, digitsOf(rounded));  // 99.96 進位成 100 之後不再帶小數
    rounded = Number(value.toFixed(digits));
    return { rounded: rounded, text: rounded.toLocaleString(language,
      { minimumFractionDigits: trim ? 0 : digits, maximumFractionDigits: digits }) + unit.label };
  }
  return function compact(n) {
    if (!units.length || n < units[0].size) return n.toLocaleString(language);
    var i = units.length - 1;
    while (n < units[i].size) i--;
    var shown = scaled(n, units[i]);
    if (i + 1 < units.length && shown.rounded * units[i].size >= units[i + 1].size) shown = scaled(n, units[i + 1]);
    return shown.text;
  };
}
/* compact:end */
(function () {
  var data = JSON.parse(document.getElementById('report-data').textContent);
  var T = JSON.parse(document.getElementById('report-texts').textContent);
  var numbers = new Intl.NumberFormat(data.language);
  var compact = makeCompact(T.units, data.language);
  var compactTick = makeCompact(T.units, data.language, true);
  var accounts = {};
  data.accounts.forEach(function (a) { accounts[a.key] = a; });
  // 金額：格子是整數美元，完整到分的數字放在滑鼠停留提示
  var dollars = new Intl.NumberFormat(data.language,
    { style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol', maximumFractionDigits: 0 });
  var cents = new Intl.NumberFormat(data.language,
    { style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol', minimumFractionDigits: 2 });
  var DASH = '—';
  var RANGES = ['7d', '30d', 'all'];
  // 各分頁共用的選擇放這裡：切換分頁時不重設
  var state = { tab: 'overview', range: '7d', view: 'all', moreColumns: false };

  function fill(template, values) {
    return template.replace(/\{(\w+)\}/g, function (whole, name) { return name in values ? values[name] : whole; });
  }
  function el(tag, text, className) {
    var node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  // SVG 元素要帶 SVG 的命名空間；從 HTML 解析器造出來的 <svg> 借用它，頁面裡就不必寫任何網址
  var SVG = (function () {
    var holder = document.createElement('div');
    holder.innerHTML = '<svg></svg>';
    return holder.firstChild.namespaceURI;
  })();
  function svg(tag, attributes) {
    var node = document.createElementNS(SVG, tag);
    Object.keys(attributes || {}).forEach(function (name) { node.setAttribute(name, attributes[name]); });
    return node;
  }
  function colorOf(account) { return account === null ? 'var(--unattributed)' : 'var(--' + accounts[account].color + ')'; }
  function swatch(account) {
    var node = el('i', null, 'swatch');
    node.style.background = colorOf(account);
    return node;
  }
  function nameOf(account) { return account === null ? T.unattributed : accounts[account].label; }
  // 大數字換單位顯示，完整數值放在滑鼠停留提示
  function counted(node, n) { node.title = numbers.format(n); return node; }
  function percent(ratio) { return ratio == null ? DASH : (ratio * 100).toFixed(1) + '%'; }
  // 金額：全部算不出是「—」，部分算不出是「已知＋—」；提示列出到分的已知金額與算不出的原因
  // headline：頭條數字的金額磚，不到 100 美元時直接顯示到分，免得剛開始用時看起來像沒花錢（$0）
  function cost(row, headline) {
    var known = row.cost == null ? null : (headline && row.cost < 100 ? cents : dollars).format(row.cost);
    var tip = [];
    if (row.cost != null) tip.push(cents.format(row.cost));
    if (row.costUnknown.length) tip.push(fill(T.costExcludes, { reason: row.costUnknown.join(T.listSep) }));
    return { text: known == null ? DASH : row.costUnknown.length ? fill(T.costPartial, { cost: known }) : known,
             title: tip.join('\n') };
  }

  document.getElementById('title').textContent = T.title;
  document.getElementById('tabs').setAttribute('aria-label', T.title);
  function when(iso) { return new Date(iso).toLocaleString(data.language); }
  document.getElementById('meta').textContent = [
    T.generatedAt + ' ' + when(data.generatedAt),
    T.ledgerUpdatedAt + ' ' + (data.ledger.updatedAt ? when(data.ledger.updatedAt) : T.ledgerNever),
    T.earliest + ' ' + (data.ledger.earliest ? when(data.ledger.earliest) : DASH),
    fill(T.pricesVersion, { date: data.prices.version || DASH })
  ].join(' · ');

  var banners = document.getElementById('banners');
  data.notices.forEach(function (notice) {
    var banner = el('p', fill(T.notices[notice.kind],
      { n: numbers.format(notice.count || 0), reason: notice.reason || '' }), 'banner');
    banner.setAttribute('role', 'status');
    banners.appendChild(banner);
  });

  // 目前選的區間與帳號：合計時是區間的總計；單看一個帳號時是該帳號在區間內的那一列，區間內沒有它的用量是 null
  function figures(summary) {
    if (state.view === 'all') return summary.accounts.length ? summary.total : null;
    return summary.accounts.filter(function (row) { return row.account === state.view; })[0] || null;
  }

  // ---- 總覽 ----
  function tile(label, value, sub) {
    var node = el('div', null, 'card tile');
    node.appendChild(el('div', label, 'label'));
    node.appendChild(value);
    var line = el('div', sub.text, 'sub');
    if (sub.title) line.title = sub.title;
    node.appendChild(line);
    return node;
  }
  function big(text, title) {
    var node = el('div', text, 'big');
    if (title) node.title = title;
    return node;
  }
  function tiles(f) {
    var node = el('section', null, 'tiles');
    node.appendChild(tile(T.tileTokens, big(compact(f.tokens), numbers.format(f.tokens)), {
      text: fill(T.tileCacheSplit, { read: compact(f.cacheRead), write: compact(f.cacheWrite) }),
      title: fill(T.tileCacheSplit, { read: numbers.format(f.cacheRead), write: numbers.format(f.cacheWrite) }) }));
    node.appendChild(tile(T.cacheHitRatio, big(percent(f.cacheHitRatio)), { text: T.tileHitFormula }));
    var money = cost(f, true);
    node.appendChild(tile(T.cost, big(money.text, money.title),
      { text: f.costUnknown.length ? T.tileCostPartial : T.tileCostBasis }));
    return node;
  }

  // 長條圖座標的刻度：最大值除以 4 之後，取 1、2、5 乘上 10 的次方
  function niceStep(max) {
    var raw = max / 4, power = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), unit = raw / power;
    return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10) * power;
  }
  function chart(summary) {
    var series = [];  // 由下往上堆：合計時依帳號出現的順序，未歸屬在最上面；單看一個帳號只有它自己
    var byDay = {};
    summary.daily.forEach(function (entry) {
      if (state.view !== 'all' && entry.account !== state.view) return;
      (byDay[entry.day] = byDay[entry.day] || {})[entry.account] = entry.tokens;
      if (series.indexOf(entry.account) < 0) series.push(entry.account);
    });
    var order = data.accounts.map(function (a) { return a.key; }).concat([null]);
    series.sort(function (a, b) { return order.indexOf(a) - order.indexOf(b); });

    var days = summary.days, W = 1000, H = 220, LEFT = 64, BOTTOM = 28, TOP = 8;
    var peak = Math.max.apply(null, [1].concat(days.map(function (day) {
      return series.reduce(function (sum, a) { return sum + ((byDay[day] || {})[a] || 0); }, 0);
    })));
    var step = niceStep(peak), top = Math.ceil(peak / step) * step;
    var plot = H - BOTTOM - TOP, slot = (W - LEFT - 8) / days.length, gap = Math.min(4, slot * 0.25);
    function scale(n) { return n / top * plot; }

    var root = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': T.chartDaily });
    for (var tick = 0; tick <= top + step / 2; tick += step) {
      var y = TOP + plot - scale(tick);
      root.appendChild(svg('line', { 'class': 'grid', x1: LEFT, x2: W, y1: y, y2: y }));
      var label = svg('text', { x: LEFT - 8, y: y + 4, 'text-anchor': 'end' });
      label.textContent = compactTick(tick);
      root.appendChild(label);
    }
    var every = Math.ceil(days.length / 8);
    days.forEach(function (day, i) {
      var x = LEFT + i * slot, base = TOP + plot;
      series.forEach(function (account) {
        var n = (byDay[day] || {})[account];
        if (!n) return;
        var h = Math.max(1, scale(n));  // 極小的段至少畫 1px，免得消失
        base -= h;
        var bar = svg('rect', { x: x + gap / 2, y: base, width: Math.max(1, slot - gap), height: h, fill: colorOf(account) });
        var tip = svg('title');
        tip.textContent = fill(T.chartTip, { day: day, account: nameOf(account), n: numbers.format(n) });
        bar.appendChild(tip);
        root.appendChild(bar);
      });
      if (i % every === 0) {
        var text = svg('text', { x: x + slot / 2, y: H - 8, 'text-anchor': 'middle' });
        text.textContent = day.slice(5).replace('-', '/');
        root.appendChild(text);
      }
    });

    var node = el('section', null, 'card');
    node.appendChild(el('h2', T.chartDaily));
    node.appendChild(root);
    var legend = el('div', null, 'legend');
    series.forEach(function (account) {
      var item = el('span', nameOf(account));
      item.insertBefore(swatch(account), item.firstChild);
      legend.appendChild(item);
    });
    node.appendChild(legend);
    return node;
  }

  // 表的一列裡各數字格：總覽的各模型表與每日表共用
  function figureCells(tr, columns, figure) {
    columns.forEach(function (column) {
      var td;
      if (column === 'cacheHitRatio') {
        td = el('td', percent(figure[column]));
      } else if (column === 'cost') {
        var money = cost(figure);
        td = el('td', money.text);
        td.title = money.title;
      } else {
        td = counted(el('td', compact(figure[column])), figure[column]);
      }
      tr.appendChild(td);
    });
  }

  // 各模型的表：其他欄位預設收起，展開的選擇在各分頁之間保留
  var MORE = ['input', 'output', 'cacheWrite5m', 'cacheWrite1h'];
  function modelTable(f) {
    var columns = ['tokens', 'cacheWrite', 'cacheRead', 'cacheHitRatio'].concat(state.moreColumns ? MORE : []).concat(['cost']);
    var table = el('table');
    var head = el('tr');
    ['model'].concat(columns).forEach(function (column) { head.appendChild(el('th', T[column])); });
    table.appendChild(head);
    function row(label, figure, className) {
      var tr = el('tr', null, className);
      tr.appendChild(el('td', label));
      figureCells(tr, columns, figure);
      return tr;
    }
    f.models.forEach(function (m) { table.appendChild(row(m.model, m)); });
    table.appendChild(row(T.total, f, 'total'));
    var node = el('section', null, 'card');
    node.appendChild(el('h2', T.models));
    node.appendChild(table);
    var toggle = el('button', state.moreColumns ? T.columnsFewer : T.columnsMore, 'toggle');
    toggle.type = 'button';
    toggle.dataset.focus = 'columns';
    toggle.setAttribute('aria-expanded', String(state.moreColumns));
    toggle.addEventListener('click', function () { state.moreColumns = !state.moreColumns; draw(); });
    node.appendChild(toggle);
    return node;
  }

  function overview(summary) {
    var f = figures(summary);
    var node = el('div', null, 'stack');
    if (!f) {
      node.appendChild(el('p', T.empty, 'card empty'));
      return node;
    }
    node.appendChild(tiles(f));
    node.appendChild(chart(summary));
    node.appendChild(modelTable(f));
    return node;
  }

  // ---- 每日 ----
  // 展開的日子：只屬於這個分頁，切換區間或帳號時保留
  var openDays = {};
  var DAILY_COLUMNS = ['tokens', 'cacheWrite', 'cacheRead', 'cacheHitRatio', 'input', 'output', 'cost'];
  // 一天的數字：合計時是那天的總計；單看一個帳號時是它那天的一列，那天沒有它的用量是 null
  function dayFigures(entry) {
    if (state.view === 'all') return entry.total;
    return entry.accounts.filter(function (row) { return row.account === state.view; })[0] || null;
  }
  function dayRow(entry, f) {
    var open = !!openDays[entry.day];
    var tr = el('tr');
    var cell = el('td');
    var toggle = el('button', null, 'day');
    toggle.type = 'button';
    toggle.dataset.focus = 'day:' + entry.day;
    toggle.setAttribute('aria-expanded', String(open));
    var chevron = el('span', open ? '▾' : '▸', 'chev');
    chevron.setAttribute('aria-hidden', 'true');
    toggle.appendChild(chevron);
    toggle.appendChild(el('span', entry.day, 'day-text'));
    toggle.addEventListener('click', function () { openDays[entry.day] = !open; draw(); });
    cell.appendChild(toggle);
    var lost = state.view === 'all'
      ? entry.accounts.filter(function (row) { return row.account === null; })[0] : null;
    if (lost) cell.appendChild(counted(el('span', T.unattributed + ' ' + compact(lost.tokens), 'day-note'), lost.tokens));
    tr.appendChild(cell);
    figureCells(tr, DAILY_COLUMNS, f);
    return tr;
  }
  function dailyTable(summary, f) {
    var table = el('table', null, 'daily');
    var head = el('tr');
    ['dayCol'].concat(DAILY_COLUMNS).forEach(function (column) {
      var th = el('th', T[column]);
      th.scope = 'col';
      head.appendChild(th);
    });
    table.appendChild(head);
    summary.byDay.slice().reverse().forEach(function (entry) {  // 新的在上
      var day = dayFigures(entry);
      if (!day) return;
      table.appendChild(dayRow(entry, day));
      if (!openDays[entry.day]) return;
      day.models.forEach(function (m) {
        var tr = el('tr', null, 'model');
        tr.appendChild(el('td', m.model));
        figureCells(tr, DAILY_COLUMNS, m);
        table.appendChild(tr);
      });
    });
    var total = el('tr', null, 'total');
    total.appendChild(el('td', T.total));
    figureCells(total, DAILY_COLUMNS, f);
    table.appendChild(total);
    var node = el('section', null, 'card');
    node.appendChild(el('h2', T.daily));
    node.appendChild(table);
    return node;
  }
  function daily(summary) {
    var f = figures(summary);
    var node = el('div', null, 'stack');
    node.appendChild(f ? dailyTable(summary, f) : el('p', T.empty, 'card empty'));
    return node;
  }

  // ---- 分頁框架：頁首的選擇各分頁共用，切換分頁時不重設 ----
  var TABS = [{ id: 'overview', label: T['tab.overview'], render: overview },
              { id: 'daily', label: T['tab.daily'], render: daily }];
  var wantFocus = null;  // 方向鍵換分頁後，重建完要把焦點給新的分頁

  function segmented(label, options, selected, choose) {
    var group = el('div', null, 'group');
    group.appendChild(el('span', label));
    var seg = el('div', null, 'seg');
    seg.setAttribute('role', 'group');
    seg.setAttribute('aria-label', label);
    options.forEach(function (option) {
      var button = el('button', option.label);
      button.type = 'button';
      button.dataset.focus = label + ':' + option.id;
      button.setAttribute('aria-pressed', String(option.id === selected));
      if (option.account !== undefined) button.insertBefore(swatch(option.account), button.firstChild);
      button.addEventListener('click', function () { choose(option.id); });
      seg.appendChild(button);
    });
    group.appendChild(seg);
    return group;
  }

  function draw() {
    var focused = wantFocus || (document.activeElement && document.activeElement.dataset
      ? document.activeElement.dataset.focus : null);
    wantFocus = null;
    var tabs = document.getElementById('tabs');
    tabs.textContent = '';
    TABS.forEach(function (tab, index) {
      var button = el('button', tab.label);
      button.type = 'button';
      button.id = 'tab-' + tab.id;
      button.setAttribute('role', 'tab');
      button.setAttribute('aria-controls', 'panel');
      button.dataset.focus = 'tab:' + tab.id;
      button.setAttribute('aria-selected', String(tab.id === state.tab));
      button.tabIndex = tab.id === state.tab ? 0 : -1;  // 分頁列只佔一個 Tab 停靠點，其餘用方向鍵
      button.addEventListener('click', function () { state.tab = tab.id; draw(); });
      button.addEventListener('keydown', function (event) {
        var last = TABS.length - 1;
        var target = { ArrowRight: index === last ? 0 : index + 1, ArrowLeft: index === 0 ? last : index - 1,
                       Home: 0, End: last }[event.key];
        if (target === undefined) return;
        event.preventDefault();
        state.tab = TABS[target].id;
        wantFocus = 'tab:' + state.tab;
        draw();
      });
      tabs.appendChild(button);
    });

    var controls = document.getElementById('controls');
    controls.textContent = '';
    controls.appendChild(segmented(T.range, RANGES.map(function (name) { return { id: name, label: T['range.' + name] }; }),
      state.range, function (id) { state.range = id; draw(); }));
    var views = [{ id: 'all', label: T['view.all'] }].concat(data.accounts.map(function (a) {
      return { id: a.key, label: a.label, account: a.key };
    }));
    controls.appendChild(segmented(T.view, views, state.view, function (id) { state.view = id; draw(); }));

    var summary = data.summary[state.range];
    var panel = document.getElementById('panel');
    panel.textContent = '';
    panel.setAttribute('aria-labelledby', 'tab-' + state.tab);
    panel.appendChild(TABS.filter(function (tab) { return tab.id === state.tab; })[0].render(summary));

    var notes = document.getElementById('notes');
    notes.textContent = '';
    notes.appendChild(el('p', T.cacheNote));
    notes.appendChild(el('p', T.costNote));
    if (state.view === 'all' && summary.accounts.some(function (row) { return row.account === null; })) {
      notes.appendChild(el('p', T.unattributedNote));
    }
    if (summary.downtimeUnrecognized) {
      notes.appendChild(el('p', data.downtimeRecordedSince
        ? fill(T.downtimeSince, { date: data.downtimeRecordedSince }) : T.downtimeNever));
    }
    // 整頁重建會丟掉鍵盤焦點：把焦點還給重建後同一個按鈕
    if (focused) {
      var again = Array.prototype.filter.call(document.querySelectorAll('[data-focus]'),
        function (node) { return node.dataset.focus === focused; })[0];
      if (again) again.focus();
    }
  }
  draw();
})();
</script>
</body>
</html>
"""
