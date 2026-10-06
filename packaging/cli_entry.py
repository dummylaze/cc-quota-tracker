"""命令列 exe（cc-quota-tracker-cli.exe）的進入點：命令、參數、輸出、結束代碼都與 python -m cc_quota_tracker 相同。"""
import sys

from cc_quota_tracker.__main__ import main

sys.exit(main())
