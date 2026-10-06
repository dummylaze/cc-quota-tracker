import sys

# 版本號的唯一來源：--version、右鍵選單、發佈 workflow 都讀它
__version__ = "1.0.0"


def command_for(frozen: bool) -> str:
    """提示文字裡引用的命令列寫法：打包版的使用者沒有 Python，只能呼叫與視窗 exe 同資料夾的命令列 exe。"""
    return "cc-quota-tracker-cli" if frozen else "python -m cc_quota_tracker"


# 命令列的完整寫法：未監看帳號卡片、list 與用法說明等提示文字引用這一處（README 是靜態文字，各自寫明）
COMMAND = command_for(getattr(sys, "frozen", False))
