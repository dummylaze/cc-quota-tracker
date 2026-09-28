"""命令列：納管帳號的操作都交給核心，這裡只負責參數與文案。"""
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import COMMAND
from .core import AddWarning, Core, InvalidLabel, NoCredential, UnknownLabel
from .render_text import render

USAGE = f"""用法：
  {COMMAND} add <帳號標籤>     納管 Claude Code 目前登入的帳號；標籤已存在就重新納管
  {COMMAND} remove <帳號標籤>  移除納管帳號
  {COMMAND} list               列出看板"""

_WARNINGS = {
    AddWarning.LABEL_LOOKS_LIKE_EMAIL: "注意：這個帳號標籤看起來像 email，它會顯示在畫面上。"
                                       "不想顯示的話，可以用別的標籤重新納管，或直接改憑證快照的檔名。",
    AddWarning.PERMISSIONS_FIXED: "警告：納管目錄或其中檔案的權限不符預期（其他人可存取，或沿用上層目錄的設定），"
                                  "已修正為只有目前使用者能存取。",
    AddWarning.NOT_BOUND: "警告：讀不到 Claude Code 目前登入帳號的識別碼，這份憑證快照暫時沒有綁定帳號；"
                          "該帳號成為使用中帳號之前只會顯示「讀數待更新」。可以稍後再執行一次 add。",
}


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    command, params = (args[0], args[1:]) if args else (None, [])
    if (command, len(params)) not in {("add", 1), ("remove", 1), ("list", 0)}:
        print(USAGE, file=sys.stderr)
        return 2
    core = Core(Path.home(), lambda: datetime.now(timezone.utc))
    if command == "list":
        print(render(core.poll()))
        return 0
    label = params[0]
    try:
        if command == "add":
            result = core.add(label)
            print(f"已納管「{label}」")
            for warning in sorted(result.warnings, key=lambda w: w.value):
                print(_WARNINGS[warning], file=sys.stderr)
        else:
            core.remove(label)
            print(f"已移除「{label}」")
    except InvalidLabel:
        print(f"帳號標籤「{label}」不能當檔名：不可空白、不可以點開頭或結尾，"
              "也不能含 < > : \" / \\ | ? * 或裝置名稱（如 CON、NUL）", file=sys.stderr)
        return 2
    except NoCredential:
        print("讀不到目前登入的憑證。請先在 Claude Code 登入要納管的帳號，再執行一次。", file=sys.stderr)
        return 1
    except UnknownLabel:
        print(f"沒有帳號標籤為「{label}」的納管帳號。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
