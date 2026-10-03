"""命令列：納管帳號的操作都交給核心，這裡只負責參數與文案；文案的語系與視窗一樣取自設定檔的 language。"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import COMMAND, claude_provider, i18n
from .board import QueryFailure
from .claude_provider import FieldStatus, NoReading, SchemaCheck
from .core import BindingsUnreadable, Core, InvalidLabel, NoCredential, UnknownLabel
from .fmt import date_time
from .i18n import text
from .managed_directory import ManagedDirectory, PermissionState
from .render_text import add_warning, render
from .settings import (CLAUDE_CONFIG_DIR, CLAUDE_DIR_FIELD, MANAGED_DIR_FIELD, InvalidPathSetting, PathProblem,
                       PathSource, ResolvedPaths, read_preferences, read_settings, resolve_paths)

_PATH_PROBLEMS = {
    PathProblem.NOT_ABSOLUTE: "path.not_absolute",
    PathProblem.NOT_A_DIRECTORY: "path.not_a_directory",
    PathProblem.INSIDE_CLAUDE_DIR: "path.inside_claude_dir",
}
_PERMISSION_STATES = {
    PermissionState.TIGHTENED: "check.permissions.tightened",
    PermissionState.UNTIGHTENED: "check.permissions.untightened",
    PermissionState.NOT_CREATED: "check.permissions.not_created",
}


def configured_language(settings_file: Optional[Path]) -> str:
    """命令列用的語系：設定檔的 language，跟隨系統時取作業系統的語系。設定檔讀不到或讀不懂就當成跟隨系統。
    視窗的語系取自每輪 poll 的看板（含 GUI 尚未寫進設定檔的改動），解析規則同樣是 i18n.resolve。"""
    fields = read_settings(settings_file) if settings_file else None
    preferences, _ = read_preferences(fields or {})
    return i18n.resolve(preferences.language, i18n.system_tag())


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    command, params = (args[0], args[1:]) if args else (None, [])
    if (command, len(params)) not in {("add", 1), ("remove", 1), ("list", 0), ("query", 0), ("check", 0), ("gui", 0)}:
        print(text(configured_language(None), "cli.usage", command=COMMAND), file=sys.stderr)  # 還沒解析路徑，讀不到設定檔
        return 2
    try:
        paths = resolve_paths(Path.home(), os.environ)
    except InvalidPathSetting as e:
        lang = configured_language(e.settings_file)
        message = (text(lang, _PATH_PROBLEMS[e.problem], field=e.field) + "\n"
                   + text(lang, "cli.settings_file_location", path=e.settings_file))
        if command == "gui":  # pythonw 沒有主控台，印出來使用者看不到
            _show_error(message)
        print(message, file=sys.stderr)
        return 1
    lang = configured_language(paths.settings_file)
    if command == "check":
        return check(paths, lang)
    if command == "gui":
        return gui(paths)
    core = Core(paths, lambda: datetime.now(timezone.utc), auto_query=False)  # 命令列不做自動查詢
    if command == "list":
        print(render(core.poll(), lang))
        return 0
    if paths.settings_unreadable:  # list 由看板帶出這個提示
        print(text(lang, "notice", text=text(lang, "settings.unreadable")), file=sys.stderr)
    if command == "query":
        return query(core, lang)
    label = params[0]
    try:
        if command == "add":
            result = core.add(label)
            print(text(lang, "account.added", label=label))
            for warning in sorted(result.warnings, key=lambda w: w.value):
                print(add_warning(lang, warning, "cli"), file=sys.stderr)
        else:
            core.remove(label)
            print(text(lang, "account.removed", label=label))
    except InvalidLabel:
        print(text(lang, "error.invalid_label", label=label), file=sys.stderr)
        return 2
    except NoCredential:
        print(text(lang, "error.no_credential"), file=sys.stderr)
        return 1
    except BindingsUnreadable as e:
        print(text(lang, "error.bindings_unreadable", path=e.path), file=sys.stderr)
        return 1
    except UnknownLabel:
        print(text(lang, "error.unknown_label", label=label), file=sys.stderr)
        return 1
    return 0


_QUERY_REASONS = {
    QueryFailure.COMMAND_NOT_FOUND: "query.reason.command_not_found",
    QueryFailure.TIMEOUT: "query.reason.timeout",
    QueryFailure.NOT_WRITTEN: "query.reason.not_written",
}


def query(core: Core, lang: str) -> int:
    """同步查詢一次額度：成功印出新的觀測時間、結束代碼 0；失敗印出原因與 /usage 退路、結束代碼 1。
    命令列與視窗是不同的程序，不共享冷卻。"""
    result = core.query_usage()
    if result.failure is None:
        print(text(lang, "query.success", time=date_time(result.observed_at, lang)))
        return 0
    if result.failure is QueryFailure.REPORTED_ERROR:  # Claude Code 的原始訊息，不翻譯
        reason = (text(lang, "query.reason.reported_error", message=result.message) if result.message
                  else text(lang, "query.reason.reported_error_no_message"))
    else:
        reason = text(lang, _QUERY_REASONS[result.failure])
    print(text(lang, "query.failed", reason=reason), file=sys.stderr)
    return 1


def gui(paths: ResolvedPaths) -> int:
    import tkinter as tk
    from .widget import Widget, enable_dpi_awareness
    enable_dpi_awareness()
    root = tk.Tk()
    core = Core(paths, lambda: datetime.now(timezone.utc))
    autostart = None
    if sys.platform == "win32":  # 開機自動啟動寫的是 Windows 登錄
        from .autostart import RegistryAutostart
        autostart = RegistryAutostart()
    Widget(root, core, paths, autostart=autostart)
    root.mainloop()
    return 0


def _show_error(message: str):
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("cc-quota-tracker", message, parent=root)
    root.destroy()


_TYPE_NAMES = {"object": "type.object", "list": "type.list", "string": "type.string", "number": "type.number",
               "boolean": "type.boolean", "null": "type.null"}
_STATUS = {
    FieldStatus.OK: "status.ok",
    FieldStatus.MISSING: "status.missing",
    FieldStatus.WRONG_TYPE: "status.wrong_type",
    FieldStatus.ABSENT: "status.absent",
    FieldStatus.NO_ITEMS: "status.no_items",
    FieldStatus.UNREACHABLE: "status.unreachable",
    FieldStatus.PARENT_ABSENT: "status.parent_absent",
}


def check(paths: ResolvedPaths, lang: str) -> int:
    """架設者檢查指令：只讀額度快取所在的檔案，只印型別與欄位名稱，不印任何值。"""
    print(text(lang, "check.claude_dir", path=paths.claude_dir, source=_source(paths.claude_source, CLAUDE_DIR_FIELD, lang)))
    print(text(lang, "check.usage_cache", path=paths.claude_json))
    print(text(lang, "check.managed_dir", path=paths.managed_dir, source=_source(paths.managed_source, MANAGED_DIR_FIELD, lang)))
    state = ManagedDirectory(paths.managed_dir).permission_state()
    print(text(lang, "check.managed_permissions", state=text(lang, _PERMISSION_STATES[state])))
    print(text(lang, "check.settings_file", path=paths.settings_file))
    if paths.settings_unreadable:
        print(text(lang, "notice", text=text(lang, "settings.unreadable")))
    print()
    try:
        cache = paths.claude_json.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(text(lang, "check.not_found", path=paths.claude_json), file=sys.stderr)
        return 1
    except OSError as e:
        print(text(lang, "check.unreadable", path=paths.claude_json, reason=e.strerror), file=sys.stderr)
        return 1
    result = claude_provider.check_schema(cache)
    if isinstance(result, NoReading):
        print(text(lang, "check.no_reading"), file=sys.stderr)
        return 1
    if not isinstance(result, SchemaCheck):
        print(text(lang, "check.incomplete"), file=sys.stderr)
        return 1
    print(text(lang, "check.fields_header"))
    for f in result.fields:
        expected = text(lang, _TYPE_NAMES[f.expected])
        if not f.required:
            expected = text(lang, "check.optional", type=expected)
        status = text(lang, _STATUS[f.status])
        if f.status is FieldStatus.WRONG_TYPE:
            status = text(lang, "check.wrong_type", status=status, actual=text(lang, _TYPE_NAMES[f.actual]))
        print(text(lang, "check.field_line", status=status, path=f.path, expected=expected))
    print()
    print(text(lang, "check.new_fields_header"))
    for name, limit_shaped in result.new_fields:
        print(f"  {name}" + (text(lang, "check.limit_shaped") if limit_shaped else ""))
    if not result.new_fields:
        print("  " + text(lang, "check.no_new_fields"))
    if not result.parses:
        print()
        print(text(lang, "check.unparseable"))
    print()
    if result.compatible:
        print(text(lang, "check.result_compatible"))
    elif result.failures:
        print(text(lang, "check.result_failures", count=len(result.failures)))
    else:
        print(text(lang, "check.result_unparseable"))
    return 0 if result.compatible else 1


def _source(source: PathSource, field: str, lang: str) -> str:
    return {PathSource.SETTINGS_FILE: text(lang, "check.source.settings_file", field=field),
            PathSource.ENV: text(lang, "check.source.env", name=CLAUDE_CONFIG_DIR),
            PathSource.DEFAULT: text(lang, "check.source.default")}[source]


if __name__ == "__main__":
    sys.exit(main())
