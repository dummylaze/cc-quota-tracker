"""命令列：納管帳號的操作都交給核心，這裡只負責參數與文案。"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import COMMAND, claude_provider
from .claude_provider import FieldStatus, NoReading, SchemaCheck
from .core import Core, InvalidLabel, NoCredential, UnknownLabel
from .render_text import ADD_WARNINGS, INVALID_LABEL, NO_CREDENTIAL, SETTINGS_UNREADABLE, render
from .settings import (CLAUDE_CONFIG_DIR, CLAUDE_DIR_FIELD, MANAGED_DIR_FIELD, InvalidPathSetting, PathProblem,
                       PathSource, ResolvedPaths, resolve_paths)

USAGE = f"""用法：
  {COMMAND} add <帳號標籤>     納管 Claude Code 目前登入的帳號；標籤已存在就重新納管
  {COMMAND} remove <帳號標籤>  移除納管帳號
  {COMMAND} list               列出看板
  {COMMAND} check              檢查 Claude Code 的額度快取結構是否仍與本工具相容，並列出實際使用的目錄
  {COMMAND} gui                開啟懸浮視窗；改用 pythonw 執行就不會出現主控台視窗"""

_PATH_PROBLEMS = {
    PathProblem.NOT_ABSOLUTE: "設定檔的 {field} 必須是完整的絕對路徑；不指定請寫 null。",
    PathProblem.NOT_A_DIRECTORY: "設定檔的 {field} 指向的目錄不存在。本工具不會改用預設位置，以免讀到另一組帳號。",
    PathProblem.INSIDE_CLAUDE_DIR: "納管目錄不能放在 Claude Code 的目錄裡面（本工具不寫入 Claude Code 的目錄）；"
                                   "請在設定檔的 {field} 指定別的位置。",
}


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    command, params = (args[0], args[1:]) if args else (None, [])
    if (command, len(params)) not in {("add", 1), ("remove", 1), ("list", 0), ("check", 0), ("gui", 0)}:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        paths = resolve_paths(Path.home(), os.environ)
    except InvalidPathSetting as e:
        message = _PATH_PROBLEMS[e.problem].format(field=e.field) + f"\n設定檔位置：{e.settings_file}"
        if command == "gui":  # pythonw 沒有主控台，印出來使用者看不到
            _show_error(message)
        print(message, file=sys.stderr)
        return 1
    if command == "check":
        return check(paths)
    if command == "gui":
        return gui(paths)
    core = Core(paths, lambda: datetime.now(timezone.utc))
    if command == "list":
        print(render(core.poll()))
        return 0
    label = params[0]
    if paths.settings_unreadable:  # list 由看板帶出這個提示
        print(SETTINGS_UNREADABLE, file=sys.stderr)
    try:
        if command == "add":
            result = core.add(label)
            print(f"已納管「{label}」")
            for warning in sorted(result.warnings, key=lambda w: w.value):
                print(ADD_WARNINGS[warning], file=sys.stderr)
        else:
            core.remove(label)
            print(f"已移除「{label}」")
    except InvalidLabel:
        print(INVALID_LABEL.format(label=label), file=sys.stderr)
        return 2
    except NoCredential:
        print(NO_CREDENTIAL, file=sys.stderr)
        return 1
    except UnknownLabel:
        print(f"沒有帳號標籤為「{label}」的納管帳號。", file=sys.stderr)
        return 1
    return 0


def gui(paths: ResolvedPaths) -> int:
    import tkinter as tk
    from .widget import Widget, enable_dpi_awareness
    enable_dpi_awareness()
    root = tk.Tk()
    core = Core(paths, lambda: datetime.now(timezone.utc))
    Widget(root, core, paths)
    root.mainloop()
    return 0


def _show_error(message: str):
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("cc-quota-tracker", message, parent=root)
    root.destroy()


_TYPE_NAMES = {"object": "物件", "list": "清單", "string": "字串", "number": "數字", "boolean": "布林", "null": "null"}
_STATUS = {
    FieldStatus.OK: "通過",
    FieldStatus.MISSING: "缺少",
    FieldStatus.WRONG_TYPE: "型別不符",
    FieldStatus.ABSENT: "可選，未出現",
    FieldStatus.NO_ITEMS: "清單是空的，無從檢查",
    FieldStatus.UNREACHABLE: "上層不符，無從檢查",
    FieldStatus.PARENT_ABSENT: "上層未出現，免檢查",
}


def check(paths: ResolvedPaths) -> int:
    """架設者檢查指令：只讀額度快取所在的檔案，只印型別與欄位名稱，不印任何值。"""
    print(f"Claude Code 目錄：{paths.claude_dir}（{_source(paths.claude_source, CLAUDE_DIR_FIELD)}）")
    print(f"額度快取：{paths.claude_json}")
    print(f"納管目錄：{paths.managed_dir}（{_source(paths.managed_source, MANAGED_DIR_FIELD)}）")
    print(f"設定檔：{paths.settings_file}")
    if paths.settings_unreadable:
        print(SETTINGS_UNREADABLE)
    print()
    try:
        text = paths.claude_json.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"找不到 {paths.claude_json}，無法檢查。請確認 Claude Code 目錄的位置，並至少用 Claude Code 登入過一次。",
              file=sys.stderr)
        return 1
    except OSError as e:
        print(f"讀不到 {paths.claude_json}：{e.strerror}", file=sys.stderr)
        return 1
    result = claude_provider.check_schema(text)
    if isinstance(result, NoReading):
        print("尚無讀數：額度快取還不存在，無法檢查。請先在 Claude Code 使用一次，等它寫入額度快取後再執行。",
              file=sys.stderr)
        return 1
    if not isinstance(result, SchemaCheck):
        print("檔案正在被 Claude Code 寫入，內容不完整。請稍後再執行一次。", file=sys.stderr)
        return 1
    print("依賴的欄位：")
    for f in result.fields:
        expected = _TYPE_NAMES[f.expected] + ("" if f.required else "，可選")
        status = _STATUS[f.status]
        if f.status is FieldStatus.WRONG_TYPE:
            status += f"：實際為{_TYPE_NAMES[f.actual]}"
        print(f"  [{status}] {f.path}（{expected}）")
    print()
    print("新出現的欄位（utilization 底下，實測基準之後才出現的）：")
    for name, limit_shaped in result.new_fields:
        print(f"  {name}" + ("（額度形狀，看板會當成其他限額顯示）" if limit_shaped else ""))
    if not result.new_fields:
        print("  無")
    if not result.parses:
        print()
        print("解析層無法解析這份額度快取：上方清單以外的依賴欄位也有不符，看板會把它當成結構不符。")
    print()
    if result.compatible:
        print("結果：相容")
    else:
        print(f"結果：不相容，{len(result.failures)} 個欄位不符" if result.failures else "結果：不相容，解析層無法解析")
    return 0 if result.compatible else 1


def _source(source: PathSource, field: str) -> str:
    return {PathSource.SETTINGS_FILE: f"設定檔的 {field}", PathSource.ENV: f"環境變數 {CLAUDE_CONFIG_DIR}",
            PathSource.DEFAULT: "預設值"}[source]


if __name__ == "__main__":
    sys.exit(main())
