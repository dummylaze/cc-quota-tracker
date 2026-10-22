"""token 報表的 HTML：單一檔案，樣式與腳本都內嵌，不載入任何外部資源，不自動刷新。

畫面全部由內嵌的報表資料（JSON）算出；頁面的文字依語系放在另一份內嵌的 JSON，腳本只取字串、不寫死任何語言。
顏色沿用視窗的 token（tokens.THEMES），跟著系統的淺色／深色。"""
import json
import re

from . import i18n
from .tokens import FONTS, THEMES

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
    "account": "report.col.account",
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
_HOLES = {"n": "{n}", "date": "{date}", "reason": "{reason}", "cost": "{cost}"}  # 讓 text() 把佔位符原樣留下，由腳本填


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
        return (f"--panel:{t['panel']};--card:{t['card']};--fg:{t['fg']};--sub:{t['sub']};"
                f"--banner:{t['banner']};--banner-fg:{t['banner_fg']};")
    family = FONTS["body"][0]
    return (f':root{{--font:"{family}","Segoe UI",system-ui,sans-serif;}}'
            f":root{{{block('light')}}}"
            f"@media (prefers-color-scheme:dark){{:root{{{block('dark')}}}}}")


_PAGE = """<!doctype html>
<html lang="{{LANG}}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}}</title>
<style>
{{THEMES}}
:root{color-scheme:light dark;--line:color-mix(in srgb,var(--fg) 14%,transparent)}  /* 線不另立顏色，由文字色淡化而來 */
*{box-sizing:border-box}
body{margin:0;background:var(--panel);color:var(--fg);
  font:15px/1.6 var(--font)}
main{max-width:960px;margin:0 auto;padding:32px 24px 48px}
h1{margin:0 0 4px;font-size:22px;line-height:1.2;font-weight:700}
.meta{margin:0 0 24px;color:var(--sub);font-size:13px}
.banners{display:grid;gap:8px;margin:0 0 24px}
.banner{margin:0;padding:12px 16px;border-radius:8px;background:var(--banner);color:var(--banner-fg);font-size:14px}
.controls{display:flex;align-items:center;gap:8px;margin:0 0 16px}
.controls label{color:var(--sub);font-size:13px}
select{font:inherit;font-size:14px;color:var(--fg);background:var(--card);border:1px solid var(--line);
  border-radius:8px;padding:6px 12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:8px 16px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:12px 8px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
th{color:var(--sub);font-size:13px;font-weight:600}
th:first-child,td:first-child{text-align:left}
td{font-variant-numeric:tabular-nums}
tr.total td{font-weight:700;border-bottom:0}
.empty{margin:0;padding:24px 8px;color:var(--sub)}
.notes{margin:24px 0 0;display:grid;gap:8px}
.notes p{margin:0;color:var(--sub);font-size:13px}
</style>
</head>
<body>
<main>
<h1 id="title"></h1>
<p class="meta" id="meta"></p>
<div class="banners" id="banners"></div>
<div class="controls"><label for="range" id="range-label"></label><select id="range"></select></div>
<div class="card" id="card"></div>
<div class="notes" id="notes"></div>
</main>
<script type="application/json" id="report-data">{{DATA}}</script>
<script type="application/json" id="report-texts">{{TEXTS}}</script>
<script>
(function () {
  var data = JSON.parse(document.getElementById('report-data').textContent);
  var T = JSON.parse(document.getElementById('report-texts').textContent);
  var numbers = new Intl.NumberFormat(data.language);
  var labels = {};
  data.accounts.forEach(function (a) { labels[a.key] = a.label; });
  // 金額：格子是整數美元，完整到分的數字放在滑鼠停留提示
  var dollars = new Intl.NumberFormat(data.language,
    { style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol', maximumFractionDigits: 0 });
  var cents = new Intl.NumberFormat(data.language,
    { style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol', minimumFractionDigits: 2 });
  var COLUMNS = ['input', 'output', 'cacheWrite5m', 'cacheWrite1h', 'cacheRead', 'cacheHitRatio', 'cost'];

  function fill(template, values) {
    return template.replace(/\\{(\\w+)\\}/g, function (whole, name) { return name in values ? values[name] : whole; });
  }
  function el(tag, text, className) {
    var node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function figure(row, column) {
    if (column === 'cacheHitRatio') return row[column] == null ? '\\u2014' : (row[column] * 100).toFixed(1) + '%';
    return numbers.format(row[column]);
  }
  // 金額格：全部算不出是「—」，部分算不出是「已知＋—」；提示列出到分的已知金額與算不出的原因
  function cell(row, column) {
    if (column !== 'cost') return el('td', figure(row, column));
    var known = row.cost == null ? null : dollars.format(row.cost);
    var td = el('td', known == null ? '\\u2014' : row.costUnknown.length ? fill(T.costPartial, { cost: known }) : known);
    var tip = [];
    if (row.cost != null) tip.push(cents.format(row.cost));
    if (row.costUnknown.length) tip.push(fill(T.costExcludes, { reason: row.costUnknown.join(T.listSep) }));
    td.title = tip.join('\\n');
    return td;
  }

  document.getElementById('title').textContent = T.title;
  function when(iso) { return new Date(iso).toLocaleString(data.language); }
  document.getElementById('meta').textContent = [
    T.generatedAt + ' ' + when(data.generatedAt),
    T.ledgerUpdatedAt + ' ' + (data.ledger.updatedAt ? when(data.ledger.updatedAt) : T.ledgerNever),
    T.earliest + ' ' + (data.ledger.earliest ? when(data.ledger.earliest) : '\\u2014'),
    fill(T.pricesVersion, { date: data.prices.version || '\\u2014' })
  ].join(' \\u00b7 ');
  document.getElementById('range-label').textContent = T.range;
  var select = document.getElementById('range');
  ['7d', '30d', 'all'].forEach(function (name) {
    var option = el('option', T['range.' + name]);
    option.value = name;
    select.appendChild(option);
  });

  var banners = document.getElementById('banners');
  data.notices.forEach(function (notice) {
    var banner = el('p', fill(T.notices[notice.kind],
      { n: numbers.format(notice.count || 0), reason: notice.reason || '' }), 'banner');
    banner.setAttribute('role', 'alert');
    banners.appendChild(banner);
  });

  function draw() {
    var summary = data.summary[select.value];
    var card = document.getElementById('card');
    card.textContent = '';
    if (!summary.accounts.length) {
      card.appendChild(el('p', T.empty, 'empty'));
    } else {
      var table = el('table');
      var head = el('tr');
      ['account'].concat(COLUMNS).forEach(function (column) { head.appendChild(el('th', T[column])); });
      table.appendChild(head);
      summary.accounts.forEach(function (row) {
        var tr = el('tr');
        tr.appendChild(el('td', row.account === null ? T.unattributed : labels[row.account]));
        COLUMNS.forEach(function (column) { tr.appendChild(cell(row, column)); });
        table.appendChild(tr);
      });
      var total = el('tr', null, 'total');
      total.appendChild(el('td', T.total));
      COLUMNS.forEach(function (column) { total.appendChild(cell(summary.total, column)); });
      table.appendChild(total);
      card.appendChild(table);
    }
    var notes = document.getElementById('notes');
    notes.textContent = '';
    notes.appendChild(el('p', T.cacheNote));
    notes.appendChild(el('p', T.costNote));
    if (summary.accounts.some(function (row) { return row.account === null; })) {
      notes.appendChild(el('p', T.unattributedNote));
    }
    if (summary.downtimeUnrecognized) {
      notes.appendChild(el('p', data.downtimeRecordedSince
        ? fill(T.downtimeSince, { date: data.downtimeRecordedSince }) : T.downtimeNever));
    }
  }
  select.addEventListener('change', draw);
  select.value = '7d';
  draw();
})();
</script>
</body>
</html>
"""
