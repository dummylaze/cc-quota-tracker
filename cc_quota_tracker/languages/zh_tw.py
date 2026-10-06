"""正體中文語系檔。與 en.py 的鍵與佔位符必須一致。"""
STRINGS = {
    # 時間：倒數、讀數年齡
    "countdown.days_hours": "{days}天{hours}小時",
    "countdown.decimal_days": "{value}天",
    "countdown.hours_minutes": "{hours}小時{minutes}分",
    "countdown.minutes": "{minutes}分",
    "until": "{countdown}後（{when}）",
    "until.short": "{countdown}（{when}）",  # 重置倒數用：中文不帶「後」
    "age.minutes": "{n} 分鐘前",
    "age.hours": "{n} 小時前",
    "age.days": "{n} 天前",
    "age.observed": "觀測 {age}",
    "age.reading": "讀數 {age}",
    "common.unknown": "未知",
    "sep.item": "、",
    "sep.clause": "，",

    # 帳號與狀態
    "role.active": "當前憑證",
    "role.standby": "待命",
    "account.unwatched": "未監看帳號",
    "account.added": "已納管「{label}」",
    "account.removed": "已移除「{label}」",
    "account.imported": "已匯入「{label}」",

    # 限額與窗口
    "window.session": "工作階段窗口",
    "window.weekly_all": "週窗口",
    "window.weekly_scoped": "週限額",
    "window.session_short": "工作階段",
    "window.weekly_all_short": "週",
    "limit.scoped": "{name}（{scope}）",
    "limit.reset": "已重置，下次重置時間未知",
    "limit.reset_short": "已重置",
    "limit.next_reset_unknown": "下次重置時間未知",
    "limit.no_open_window": "無計時中窗口",
    "limit.resets": "重置：{when}",
    "limit.dollars_used": "已用 ${used}",
    "week.span": "本週 {start} ～ {end}",
    "week.passed": "已過 {percent}%",
    "breakdown.title": "本週用量去向",
    "extra_usage": "額外用量",
    "spend": "花費",
    "others.title": "{arrow} 其他限額（{count}）",
    "table.account": "帳號",
    "table.reading": "讀數",
    "table.credential_expiry": "憑證到期",
    "expiry.invalid": "已失效",
    "expiry.expired": "已過期（{when}）",
    "notes.count": "{count} 則提示",

    # 卡片上的提示
    "reading.none": "尚無讀數",
    "reading.none_soon": "尚無讀數，Claude Code 更新額度快取後就會出現",
    "reading.pending": "讀數待更新，Claude Code 更新額度快取後就會出現",
    "reading.pending_short": "讀數待更新",  # 旁邊有「更新」入口時用，維持單行
    "reading.lagging": "有新對話，額度尚未更新",
    "reading.lagging_before_switch": "切換前已落後",  # 待命帳號：切換之前，這份讀數就已經落後
    "reading.locked": "額度已鎖定：{reason}",
    "note.observed": "觀測值：觀測之後這個帳號沒再被用過才準確；在別台機器上用過，這台看不到",
    "note.how_to_manage": "這個帳號還沒納管：在 Claude Code 登入它之後執行 {command} add <帳號標籤>，"
                          "或在視窗按右鍵選「納管目前登入的帳號…」",
    "note.named": "{label}：{text}",
    "note.watch_only": "僅監看帳號（{reason}）：在 Claude Code 登入這個帳號後重新納管",  # reason 是 watch_only.reason.*
    "note.writeback_retrying": "寫回快照失敗，自動重試 {failures}/{attempts}",
    "note.writeback_stopped": "寫回快照失敗，已停止重試",  # 卡片上 note.watch_only 的 reason
    "snapshot.expired": "憑證快照已過期（{when}）",
    "snapshot.expires_in": "憑證快照 {left}後到期（{when}）",
    "snapshot.relogin": "{when}：在 Claude Code 重新登入這個帳號，再執行 {command} add {label}",
    "snapshot.renew": "{when}，請重新納管",

    # 橫幅
    "settings.invalid": "設定檔的 {fields} 值不合法，這幾項改用預設值；請參考 README 的欄位說明修正。",
    "settings.unreadable": "設定檔無法讀取（不是合法的 JSON），裡面的設定都當成沒填；本工具不會覆寫它，請修正後再試。",
    "font.missing": "設定檔的 font 指定的字型「{font}」在這台電腦上找不到，改用系統預設字型。",
    "banner.restart_required": "設定檔的路徑欄位改了；路徑只在啟動時讀取，重新啟動本工具後才生效。",
    "banner.permissions_untightened": "納管目錄的權限無法收緊。把它搬到 NTFS 磁碟（一般的 C:、D: 槽）即可解除。",
    "board.wrong_location": "預設位置找不到 Claude Code 的額度快取，可能讀錯位置。Claude Code 目錄若不在 home"
                            "（例如設了 CLAUDE_CONFIG_DIR），請在設定檔的 claudeConfigDir 指定。",
    "banner.schema_changed": "額度快取結構已變更，本工具讀不懂新的結構；下面是最後一次成功的讀數（{when}，{age}）",
    "banner.schema_changed_none": "額度快取結構已變更，本工具讀不懂新的結構；目前沒有成功的讀數",
    "banner.stalled": "看板已停止更新：讀取時發生錯誤；最後一次成功的讀數：（{when}，{age}）",
    "banner.stalled_none": "看板已停止更新：讀取時發生錯誤；目前沒有成功的讀數",

    # list 的文字輸出
    "notice": "注意：{text}",
    "list.header": "[{role}] {label}",
    "list.header_unwatched": "[當前憑證] 未監看帳號（納管方法：在 Claude Code 登入這個帳號後執行 {command} add <帳號標籤>）",
    "list.reading_age": "讀數年齡：{age}",
    "list.observed": "最後觀測：{age}（觀測值：觀測之後這個帳號沒再被用過才準確）",
    "list.other_limits": "其他限額：",
    "list.breakdown": "本週用量去向（{start} ～ {end}）：",
    "list.watched": "監看帳號：{labels}",
    "list.none_watched": "尚未納管任何帳號",
    "list.watch_only": "僅監看帳號：{reason}",
    "list.watch_only_remedy": "重新納管：在 Claude Code 登入這個帳號後，執行 {command} add {label}",
    "watch_only.reason.expired": "已過期",
    "watch_only.reason.invalid": "已失效",
    "watch_only.reason.no_account_info": "沒有帳號資訊",
    "watch_only.reason.writeback_retrying": "寫回失敗（重試中 {failures}/{attempts}）",
    "watch_only.reason.writeback_stopped": "寫回失敗（已停止重試）",
    "list.schema_changed": "額度快取結構已變更，本工具讀不懂新的結構；以下是最後一次成功的讀數（{time}）",
    "list.schema_changed_none": "額度快取結構已變更，本工具讀不懂新的結構；目前沒有成功的讀數",
    "list.query_hint": "讀數落後或待更新：可以執行 {command} query 查詢最新額度，或在 Claude Code 執行 /usage。",

    # 納管帳號的結果與錯誤：命令列與視窗共用
    "add_warning.label_looks_like_email": "注意：這個帳號標籤看起來像 email，它會顯示在畫面上。"
                                          "不想顯示的話，可以用別的標籤重新納管，或直接改憑證快照的檔名。",
    "add_warning.permissions_fixed": "警告：納管目錄或其中檔案的權限不符預期（其他人可存取，或沿用上層目錄的設定），"
                                     "已修正為只有目前使用者能存取。",
    "add_warning.permissions_untightened": "警告：納管目錄的權限無法收緊。把它搬到 NTFS 磁碟（一般的 C:、D: 槽）即可解除。",
    "add_warning.not_bound.cli": "警告：讀不到 Claude Code 目前登入帳號的識別碼，這份憑證快照暫時沒有綁定帳號；"
                                 "該帳號成為當前憑證帳號之前只會顯示「讀數待更新」。可以稍後再執行一次 add。",
    "add_warning.not_bound.menu": "讀不到 Claude Code 目前登入帳號的識別碼，這份憑證快照暫時沒有綁定帳號；"
                                  "該帳號成為當前憑證帳號之前只會顯示「讀數待更新」。"
                                  "可以稍後再從右鍵選單「納管目前登入的帳號…」做一次。",
    # 匯入的憑證檔本來就不帶帳號識別碼，沒有綁定是常態，不是讀取失敗
    "add_warning.not_bound.import": "這份憑證快照還沒有綁定帳號：在 Claude Code 登入這個帳號、成為當前憑證帳號之後，"
                                    "本工具會自動補上；在那之前只會顯示「讀數待更新」。",
    "error.invalid_label": "帳號標籤「{label}」不能當檔名：不可空白、不可以點開頭或結尾，"
                           "也不能含 < > : \" / \\ | ? * 或裝置名稱（如 CON、NUL）",
    "error.no_credential": "讀不到目前登入的憑證。請先在 Claude Code 登入要納管的帳號，再執行一次。",
    "error.not_a_credential_file": "這個檔案不是 Claude Code 的憑證檔（讀不出 claudeAiOauth 的 refreshToken），沒有匯入。",
    "error.unknown_label": "沒有帳號標籤為「{label}」的監看帳號。",
    "error.bindings_unreadable": "綁定檔（{path}）暫時讀不到，可能被其他程式（例如防毒軟體）鎖住。"
                                 "憑證快照沒有變更，請稍後再試一次。",

    # 右鍵選單與對話框
    "menu.layout": "版面",
    "menu.topmost": "置頂",
    "menu.mode": "模式",
    "menu.language": "語系",
    "menu.theme": "主題",
    "menu.opacity": "透明度",
    "menu.autostart": "開機自動啟動",
    "menu.query": "查詢額度",
    "menu.auto_query": "自動查詢額度",
    "menu.add": "納管目前登入的帳號…",
    "menu.import": "匯入憑證檔…",
    "menu.open_folder": "開啟資料夾",
    "menu.open_managed_dir": "納管目錄",
    "menu.open_settings_dir": "設定目錄",
    "menu.dismiss_untightened": "不再提醒權限未收緊",
    "menu.quit": "結束",
    "menu.switch": "切換帳號",
    "menu.switch_none": "（沒有可切換的帳號）",
    "layout.cards": "卡片列表",
    "layout.table": "密集表格／單行條",
    "layout.ring": "環形儀表",
    "mode.compact": "精簡",
    "mode.expanded": "展開",
    "theme.system": "跟隨系統",
    "theme.light": "淺色",
    "theme.dark": "深色",
    "language.system": "跟隨系統",
    "dialog.switch_title": "切換帳號",
    "dialog.switch_confirm": "切換到「{label}」？",
    "dialog.switch_watched": "目前帳號「{label}」是監看帳號：切走之前，會先同步憑證至快照。",
    "dialog.switch_unwatched": "目前帳號是未監看帳號：只會存成切換前憑證，且只留最新一份。",
    "dialog.switch_invalid": "目前帳號快照已失效；用「還原上一次切換」，或在 Claude Code 登入後再重新納管。",
    "dialog.switch_failed": "切換時發生錯誤，沒有切換成功：{error}",
    "dialog.label_prompt": "帳號標籤（會顯示在畫面上，也是憑證快照的檔名）：",
    "dialog.import_title": "匯入憑證檔",
    "dialog.all_files": "所有檔案",
    "dialog.confirm_replace": "已經有帳號標籤「{label}」，要用這個檔案取代它的憑證快照嗎？",
    "dialog.managed_dir_missing": "納管目錄還不存在：{directory}\n納管第一個帳號時會建立。",
    "dialog.settings_dir_missing": "設定目錄還不存在：{directory}\n第一次啟動工具時會建立。",
    "dialog.autostart_failed": "無法變更開機自動啟動：{error}",
    "dialog.auto_query_unreadable": "設定檔無法讀取，或內容不是合法的設定。\n自動查詢的開關沒有變動。",
    "dialog.auto_query_malformed": "設定檔的 providers 或 providers.claude 不是物件。\n自動查詢的開關沒有變動。",
    "dialog.auto_query_write_failed": "無法寫入設定檔：{error}\n自動查詢的開關沒有變動。",

    # 命令列
    "cli.usage": "用法：\n"
                 "  {command} add <帳號標籤>     納管 Claude Code 目前登入的帳號；標籤已存在就重新納管\n"
                 "  {command} remove <帳號標籤>  移除監看帳號\n"
                 "  {command} list               列出看板\n"
                 "  {command} check              檢查 Claude Code 的額度快取結構是否仍與本工具相容，並列出實際使用的目錄\n"
                 "  {command} query              查詢一次最新額度並等它結束；成功結束代碼 0，失敗 1\n"
                 "  {command} gui                開啟懸浮視窗；改用 pythonw 執行就不會出現主控台視窗\n"
                 "  {command} switch <帳號標籤> --yes\n"
                 "                               切換到這個納管帳號；--yes 表示不再確認、直接切換。\n"
                 "  {command} switch --previous --yes\n"
                 "                               還原上一次切換：當前憑證與帳號資訊一起回到切換前；再還原一次會回到剛才的帳號。\n"
                 "                               成功結束代碼 0，拒絕（沒寫任何檔）1，已寫入但驗證失敗或只寫了一半 3，沒帶 --yes 2",
    "switch.done": "已切換到「{label}」",
    "switch.restored": "已還原上一次切換",
    "switch.refused.no_previous": "沒有可還原的切換前憑證，沒有切換。",
    "switch.refused.previous_expired": "切換前憑證已過期，沒辦法還原，沒有切換：請在 Claude Code 重新登入那個帳號。",
    "switch.restore_write_failed": "已寫入切換前的憑證，但沒能改寫 Claude Code 的帳號資訊，兩者目前不一致：請在 Claude Code 重新登入。",
    "switch.restore_verify_failed": "已還原上一次切換，但替還原後的帳號查詢額度失敗，沒能確認還原有生效：{reason}",
    "switch.step.sync": "同步目前帳號的憑證…",
    "switch.step.query_old": "查詢舊帳號的額度…",
    "switch.step.write": "寫入「{label}」的憑證…",
    "switch.step.query_new": "查詢新帳號的額度…",
    "switch.refused.watch_only": "「{label}」是僅監看帳號（{reason}），不能切換過去：在 Claude Code 登入這個帳號後重新納管",
    "switch.refused.already_active": "「{label}」已經是當前憑證帳號。",
    "switch.refused.sync_failed": "目前帳號的憑證沒能同步回它的快照，沒有切換；請稍後再試。",
    "switch.refused.unreadable": "讀不到目前的憑證或 Claude Code 的帳號資訊，沒有切換；請稍後再試。",
    "switch.refused.unwritable": "寫不進目前的憑證或切換前憑證（可能被其他程式鎖住），沒有切換；請稍後再試。",
    "switch.write_failed": "已寫入「{label}」的憑證，但沒能改寫 Claude Code 的帳號資訊，兩者目前不一致：請在 Claude Code 重新登入。",
    "switch.verify_failed": "已切換到「{label}」，但替它查詢額度失敗，沒能確認切換有生效：{reason}\n要回到切換前的帳號：{command} switch --previous --yes",
    "query.success": "額度已更新，最新觀測時間：{time}",
    "query.failed": "查詢額度失敗：{reason}\n可改在 Claude Code 執行 /usage。",
    "query.reason.command_not_found": "找不到 claude 執行檔。請確認有在 PATH 裡，或在設定檔的 providers.claude.claudeCommand "
                                      "填入完整路徑。",
    "query.reason.timeout": "Claude Code 逾時沒有完成查詢。",
    "query.reason.reported_error": "Claude Code 回報錯誤：{message}",  # message 是 Claude Code 的原始訊息，不翻譯
    "query.reason.reported_error_no_message": "Claude Code 回報錯誤，沒有附上訊息。",
    "query.reason.not_written": "Claude Code 已結束，但額度快取沒有更新。",
    # 卡片上的查詢額度：入口與狀態
    "query.entry": "更新",
    "query.entry_busy": "查詢中…",
    "query.note.failed": "查詢失敗：{reason}。在 Claude Code 執行 /usage",
    "query.note.command_not_found": "找不到 claude 指令",
    "query.note.timeout": "Claude Code 逾時",
    "query.note.reported_error": "Claude Code 回報「{message}」",  # message 是 Claude Code 的原始訊息，不翻譯
    "query.note.reported_error_no_message": "Claude Code 回報錯誤",
    "query.note.not_written": "Claude Code 沒有更新額度快取",
    "query.note.auto_paused": "自動查詢已暫停：{reason}。手動更新成功後恢復",
    "banner.auto_query_floor": "providers.claude.autoUsageQueryMinutes 低於下限，以 {minutes} 分鐘執行",
    "cli.settings_file_location": "設定檔位置：{path}",
    "path.not_absolute": "設定檔的 {field} 必須是完整的絕對路徑；不指定請寫 null。",
    "path.not_a_directory": "設定檔的 {field} 指向的目錄不存在。本工具不會改用預設位置，以免讀到另一組帳號。",
    "path.inside_claude_dir": "納管目錄不能放在 Claude Code 的目錄裡面（本工具不寫入 Claude Code 的目錄）；"
                              "請在設定檔的 {field} 指定別的位置。",

    # check 指令
    "check.claude_dir": "Claude Code 目錄：{path}（{source}）",
    "check.usage_cache": "額度快取：{path}",
    "check.managed_dir": "納管目錄：{path}（{source}）",
    "check.managed_permissions": "納管目錄權限：{state}",
    "check.permissions.tightened": "已收緊",
    "check.permissions.untightened": "未收緊",
    "check.permissions.not_created": "尚未建立",
    "check.settings_file": "設定檔：{path}",
    "check.source.settings_file": "設定檔的 {field}",
    "check.source.env": "環境變數 {name}",
    "check.source.default": "預設值",
    "check.not_found": "找不到 {path}，無法檢查。請確認 Claude Code 目錄的位置，並至少用 Claude Code 登入過一次。",
    "check.unreadable": "讀不到 {path}：{reason}",
    "check.no_reading": "尚無讀數：額度快取還不存在，無法檢查。請先在 Claude Code 使用一次，等它寫入額度快取後再執行。",
    "check.incomplete": "檔案正在被 Claude Code 寫入，內容不完整。請稍後再執行一次。",
    "check.fields_header": "依賴的欄位：",
    "check.field_line": "  [{status}] {path}（{expected}）",
    "check.optional": "{type}，可選",
    "check.wrong_type": "{status}：實際為{actual}",
    "check.new_fields_header": "新出現的欄位（utilization 底下，實測基準之後才出現的）：",
    "check.limit_shaped": "（額度形狀，看板會當成其他限額顯示）",
    "check.no_new_fields": "無",
    "check.unparseable": "解析層無法解析這份額度快取：上方清單以外的依賴欄位也有不符，看板會把它當成結構不符。",
    "check.result_compatible": "結果：相容",
    "check.result_failures": "結果：不相容，{count} 個欄位不符",
    "check.result_unparseable": "結果：不相容，解析層無法解析",
    "type.object": "物件",
    "type.list": "清單",
    "type.string": "字串",
    "type.number": "數字",
    "type.boolean": "布林",
    "type.null": "null",
    "status.ok": "通過",
    "status.missing": "缺少",
    "status.wrong_type": "型別不符",
    "status.absent": "可選，未出現",
    "status.no_items": "清單是空的，無從檢查",
    "status.unreachable": "上層不符，無從檢查",
    "status.parent_absent": "上層未出現，免檢查",
}
