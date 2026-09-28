"""憑證儲存：唯一接觸憑證內容的地方，對外不回傳 token 本身。"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

_KEY_LEN = 16
# 刷新時會變的欄位；內容雜湊排除它們，所以刷新不算實質變更
_REFRESHED_FIELDS = ("accessToken", "expiresAt")


@dataclass(frozen=True)
class Credential:
    """憑證中可以外流的部分：只有到期時間，不含任何 token。"""
    refresh_token_expires_at: Optional[datetime]


class CredentialStore(Protocol):
    """讀不到或讀不懂一律回傳 None。M1 只有檔案版本；寫入方法到切換功能時才加。"""

    def read(self) -> Optional[Credential]: ...

    def fingerprint(self) -> Optional[str]:
        """憑證指紋：refreshToken 的 SHA-256 前 16 個十六進位字元。刷新只換 accessToken，指紋不變；它不代表帳號。"""

    def content_hash(self) -> Optional[str]:
        """實質內容：排除 accessToken 與到期時間之後的欄位；絕不對整份檔案雜湊，否則每次刷新都算變更。"""


class FileCredentialStore:
    """Claude Code 的憑證檔格式（claudeAiOauth），存放在一個 JSON 檔裡。"""

    def __init__(self, path: Path):
        self._path = Path(path)

    def read(self) -> Optional[Credential]:
        oauth = self._oauth()
        if oauth is None:
            return None
        expires = oauth.get("refreshTokenExpiresAt")
        valid = isinstance(expires, (int, float)) and not isinstance(expires, bool)
        return Credential(datetime.fromtimestamp(expires / 1000, timezone.utc) if valid else None)

    def fingerprint(self) -> Optional[str]:
        oauth = self._oauth()
        token = oauth.get("refreshToken") if oauth else None
        if not isinstance(token, str) or not token:
            return None
        return _digest(token)

    def content_hash(self) -> Optional[str]:
        oauth = self._oauth()
        if oauth is None:
            return None
        kept = {k: v for k, v in oauth.items() if k not in _REFRESHED_FIELDS}
        return _digest(json.dumps(kept, sort_keys=True))

    def _oauth(self) -> Optional[dict]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        oauth = raw.get("claudeAiOauth") if isinstance(raw, dict) else None
        return oauth if isinstance(oauth, dict) else None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_KEY_LEN]
