"""工具狀態的原子寫入與刪除：寫暫存檔再一次替換；短暫鎖定時重試。"""
import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

TEMP_PREFIX = ".cc-quota-tracker-"
RETRIES = 3  # 防毒或索引服務短暫鎖住檔案時的重試次數
RETRY_DELAY = 0.05


def write_atomic(path: Path, data: bytes, before_replace: Optional[Callable[[Path], None]] = None) -> None:
    """暫存檔建在目標同一目錄：跨磁區時替換會直接失敗，而開發機上測不出來。
    before_replace 在替換前拿到暫存檔，可以收緊權限或驗證內容；它丟出例外就不替換。
    任何失敗都清掉暫存檔，目標檔維持原樣。"""
    fd, name = tempfile.mkstemp(prefix=TEMP_PREFIX, suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if before_replace:
            before_replace(tmp)
        _retrying(lambda: os.replace(tmp, path))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def append(path: Path, data: bytes, before_replace: Optional[Callable[[Path], None]] = None) -> None:
    """只追加：檔案不存在時以原子寫入建立（before_replace 同 write_atomic），之後接在檔尾，不改既有內容。"""
    if not path.exists():
        write_atomic(path, data, before_replace)
        return

    def write() -> None:
        with open(path, "ab") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    _retrying(write)


def remove(path: Path) -> None:
    """刪檔也會撞上短暫鎖定，同樣重試。"""
    _retrying(lambda: os.unlink(path))


def _retrying(action: Callable[[], None]) -> None:
    for attempt in range(RETRIES + 1):
        try:
            action()
            return
        except PermissionError:
            if attempt == RETRIES:
                raise
            time.sleep(RETRY_DELAY)
