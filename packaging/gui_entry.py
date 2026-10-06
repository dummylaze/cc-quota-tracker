"""視窗 exe（cc-quota-tracker.exe）的進入點：不帶參數就開視窗，等同 `gui`；帶了參數就照命令列處理。
視窗 exe 沒有主控台，帶參數時的輸出看不到；要看輸出與結束代碼請用 cc-quota-tracker-cli.exe。"""
import sys

from cc_quota_tracker.__main__ import main

sys.exit(main(sys.argv[1:] or ["gui"]))
