"""納管目錄：本工具保管的資料都放在這裡，核心只透過它存取，不直接碰檔案。

對外是領域操作，不是檔案。以下規則在這個 module 裡強制執行，呼叫端不必、也無法繞過：
- 三態讀取：不存在與讀不懂視為「沒有」，讀不到（作業系統層的讀取錯誤，例如被防毒鎖住）視為「未知」。
- 一律原子寫入；暫存檔在替換前就收緊權限；目錄先收緊再往裡面寫。
- 切換紀錄只追加。
- 權限只有一套政策：收緊後事後驗證，仍不符就丟 PermissionError。

已知限制：GUI 與命令列是兩個程序，同時寫同一個檔案時沒有跨程序的鎖；兩者在同一輪內交錯時，後寫的會蓋掉先寫的。

過渡：綁定、待命讀數、憑證快照與視窗位置還在核心與視窗程式裡，它們用 STATE_DIR、tighten、mkdir_private、
ManagedDirectory.write_state；隨後續的票搬進來之後，這幾個就收回 module 內部。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional

from . import atomic
from .permissions import is_private, make_private

STATE_DIR = ".state"  # 納管目錄底下放工具狀態的子目錄，與憑證快照分開


class Observed(NamedTuple):
    """上一輪的觀測：當時的憑證指紋，以及已失效（被輪替）而留著標記的憑證快照的憑證指紋。沒有上一輪時兩者都是 None。"""
    fingerprint: Optional[str] = None
    invalid_snapshot: Optional[str] = None


def tighten(path: Path, new: bool = False) -> bool:
    """收緊到只有目前使用者能存取。回傳是否修正了原本外露的權限；剛建立的不算。修正後仍不符就丟例外。"""
    if is_private(path):
        return False
    make_private(path)
    if not is_private(path):
        raise PermissionError(f"could not restrict access to the current user: {path.name}")  # 給開發者的診斷，不是畫面文案
    return not new


def mkdir_private(path: Path) -> bool:
    """先收緊目錄再往裡面寫，檔案一建立就不會外露。回傳是否修正了既有目錄的權限。"""
    new = not path.exists()
    path.mkdir(exist_ok=True)
    return tighten(path, new)


class ManagedDirectory:
    """一個納管目錄的所有讀寫；路徑由設定決定，核心啟動時給一次。"""

    def __init__(self, path: Path):
        self._path = Path(path)
        state = self._path / STATE_DIR
        self._observed = state / "observed.json"  # 最後運作時間與上一輪的觀測
        self._switch_log = state / "switches.jsonl"

    def read_observed(self) -> Optional[Observed]:
        """讀不到回傳 None（呼叫端這一輪不判定）；不存在或讀不懂就當成沒有上一輪。"""
        state = self._read_state(self._observed)
        if state is None:
            return None
        return Observed(_text(state.get("fingerprint")), _text(state.get("invalidSnapshot")))

    def write_observed(self, last_run_at: datetime, observed: Observed) -> None:
        """記下這一輪的觀測與運作時間，下一輪（含重新啟動後）接著比對。寫不成就丟 OSError。"""
        self.write_state(self._observed, {"lastRunAt": last_run_at.isoformat(), "fingerprint": observed.fingerprint,
                                          "invalidSnapshot": observed.invalid_snapshot})

    def append_switch(self, at: datetime, account_id: Optional[str]) -> None:
        """切換紀錄只追加：時間、切到的帳號識別碼（拿不到為 null）、來源。不記帳號鍵（ADR-0009）。寫不成就丟 OSError。"""
        self._mkdir_state_dir()
        line = json.dumps({"at": at.isoformat(), "accountId": account_id, "source": "observed"})
        atomic.append(self._switch_log, (line + "\n").encode("utf-8"),
                      before_replace=lambda tmp: tighten(tmp, new=True))

    def write_state(self, path: Path, data: dict) -> None:
        """工具狀態一律原子寫入，暫存檔在替換前就收緊權限。"""
        self._mkdir_state_dir()
        atomic.write_atomic(path, json.dumps(data, indent=2).encode("utf-8"),
                            before_replace=lambda tmp: tighten(tmp, new=True))

    @staticmethod
    def _read_state(path: Path) -> Optional[dict]:
        """三態讀取的唯一一份：讀不到回傳 None；不存在、讀不懂、不是物件都回傳空的。"""
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except OSError:
            return None
        except ValueError:
            return {}
        return state if isinstance(state, dict) else {}

    def _mkdir_state_dir(self) -> None:
        """poll 在還沒納管任何帳號時也會寫工具狀態，納管目錄可能還不存在。"""
        mkdir_private(self._path)
        mkdir_private(self._path / STATE_DIR)


def _text(value) -> Optional[str]:
    return value if isinstance(value, str) and value else None
