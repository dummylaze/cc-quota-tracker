"""錯誤紀錄：每輪沒有完成時的錯誤詳情，放在設定檔所在的目錄（出錯的可能正是納管目錄）。
只在「從完成轉為沒有完成」與「錯誤內容換了」時寫一筆；寫不進去就默默放棄，下次符合時機再寫。"""
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Tuple

LOG_NAME = "errors.log"
MAX_BYTES = 1024 * 1024  # 固定值：超過就輪替成 errors.log.1，只留這一份舊檔


class ErrorLog:
    def __init__(self, directory: Path, clock: Callable[[], datetime]):
        self._path = directory / LOG_NAME
        self._clock = clock
        self._last: Optional[Tuple[type, str]] = None  # 上一輪沒完成的錯誤（類型、訊息）；None 表示上一輪完成了

    def completed(self) -> None:
        self._last = None

    def failed(self, error: BaseException) -> None:
        try:
            signature = (type(error), str(error))  # 連 str() 都可能丟例外：refresh 的 except 區塊不能再往外丟
            if signature == self._last:
                return
            self._append(error)
        except Exception:
            return  # 沒記到：不更新 _last，下次符合時機再寫
        self._last = signature

    def _append(self, error: BaseException) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self._path.stat().st_size > MAX_BYTES:
                os.replace(self._path, self._path.with_name(LOG_NAME + ".1"))
        except OSError:
            pass  # 輪替不成（例如舊檔被編輯器鎖住）也照樣追加，紀錄才不會停擺
        detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(f"[{self._clock().isoformat(timespec='seconds')}]\n{detail}\n")
