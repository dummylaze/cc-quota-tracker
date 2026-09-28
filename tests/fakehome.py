"""假 home 與可控時鐘：所有核心測試共用的骨架。"""
import contextlib
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from cc_quota_tracker.core import Core
from cc_quota_tracker.settings import DEFAULTS, resolve_paths

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

_DEFAULT = object()
MISSING = object()  # 傳給 limit(severity=…)：該鍵整個不存在


class FakeClock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


def limit(kind, percent, resets_at=_DEFAULT, severity="normal", is_active=False, scope=None):
    """limits[] 的一個元素；resets_at 傳 None 表示供應商給 null。"""
    if resets_at is _DEFAULT:
        resets_at = NOW + timedelta(days=3)
    item = {"kind": kind, "group": kind, "percent": percent, "severity": severity,
            "resets_at": resets_at.isoformat() if resets_at else None,
            "scope": scope, "is_active": is_active}
    if severity is MISSING:
        del item["severity"]
    return item


def limit_field(utilization, resets_at=None, locked_reason=None, dollars=(None, None, None)):
    """utilization 底下「額度形狀」的欄位（five_hour、seven_day、代號欄位）。"""
    limit_d, used_d, remaining_d = dollars
    return {"utilization": utilization, "resets_at": resets_at.isoformat() if resets_at else None,
            "limit_dollars": limit_d, "used_dollars": used_d, "remaining_dollars": remaining_d,
            "locked_reason": locked_reason}


def claude_json(cache, oauth="acct-1"):
    """登入中的 ~/.claude.json：oauthAccount 是目前登入帳號，cachedUsageUtilization 是額度快取（可能還是別的帳號的）。"""
    return {"oauthAccount": {"accountUuid": oauth, "emailAddress": "someone@example.com"},
            "cachedUsageUtilization": cache}


def usage_cache(fetched_at=NOW, session=10, weekly=40, resets_at=None, limits=None, account_uuid="acct-1",
                **fields):
    resets = (resets_at or NOW + timedelta(days=3)).isoformat()
    if limits is None:
        limits = [
            {"kind": "session", "percent": session, "severity": "normal",
             "resets_at": resets, "is_active": False},
            {"kind": "weekly_all", "percent": weekly, "severity": "normal",
             "resets_at": resets, "is_active": True},
        ]
    return {
        "fetchedAtMs": int(fetched_at.timestamp() * 1000),
        "accountUuid": account_uuid,
        "utilization": dict(fields, limits=limits),
    }


class HomeTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.clock = FakeClock()
        # 環境變數一律由測試給定：不讀真實的 CLAUDE_CONFIG_DIR，設定檔也寫在暫存目錄裡
        self.env = {"APPDATA": str(self.home / "appdata-from-env")}  # 刻意與缺少 APPDATA 時的預設不同
        self.start()

    def start(self, **env):
        """啟動核心：路徑只在這時解析一次。env 會疊加在測試的環境變數上。"""
        self.env.update(env)
        self.paths = resolve_paths(self.home, self.env)
        self.core = Core(self.paths, self.clock)

    @contextlib.contextmanager
    def cli_environment(self):
        """命令列入口讀真實的 home 與環境變數：兩者都換成這個假 home。"""
        with mock.patch("pathlib.Path.home", return_value=self.home), \
                mock.patch.dict(os.environ, self.env, clear=True):
            yield

    def settings_file(self):
        return self.home / "appdata-from-env" / "cc-quota-tracker" / "settings.json"

    def write_settings(self, **fields):
        """像使用者手改那樣，把預設設定檔改掉其中幾個欄位。"""
        self.write_settings_text(json.dumps(dict(DEFAULTS, **fields)))

    def write_settings_text(self, text):
        """每次都把修改時間往後推 1 秒：連續兩次寫入可能落在同一個時間刻度，修改時間不變，核心就不會重讀。"""
        path = self.settings_file()
        mtime = path.stat().st_mtime_ns + 1_000_000_000
        path.write_text(text, encoding="utf-8")
        os.utime(path, ns=(mtime, mtime))

    def make_dir(self, name):
        path = self.home / name
        path.mkdir(parents=True)
        return path

    def write_claude_json(self, data):
        """修改時間一律往後推：同一個時間刻度內的第二次寫入，核心會當成檔案沒變。"""
        path = self.paths.claude_json
        mtime = path.stat().st_mtime_ns + 1_000_000_000 if path.exists() else None
        path.write_text(json.dumps(data), encoding="utf-8")
        if mtime:
            os.utime(path, ns=(mtime, mtime))

    def write_credentials(self, refresh="rt-1", access="at-1", expires_at=NOW + timedelta(hours=8),
                          refresh_expires_at=NOW + timedelta(days=30)):
        """Claude Code 維護的當前憑證，寫在解析出的 Claude Code 目錄；到期時間是毫秒時間戳。"""
        path = self.paths.claude_dir / ".credentials.json"
        path.parent.mkdir(exist_ok=True)
        oauth = {"accessToken": access, "refreshToken": refresh,
                 "expiresAt": int(expires_at.timestamp() * 1000),
                 "refreshTokenExpiresAt": int(refresh_expires_at.timestamp() * 1000),
                 "scopes": ["user:inference"], "subscriptionType": "max", "rateLimitTier": "tier"}
        path.write_text(json.dumps({"claudeAiOauth": oauth}), encoding="utf-8")
        return path

    def log_in(self, refresh="rt-1", account_uuid="acct-1"):
        """模擬在 Claude Code 登入某帳號：當前憑證與 oauthAccount 一起換。"""
        self.write_credentials(refresh=refresh)
        self.write_claude_json({"oauthAccount": {"accountUuid": account_uuid,
                                                 "emailAddress": "someone@example.com"}})

    def write_cache(self, oauth="acct-1", **cache):
        """Claude Code 以 oauth 帳號登入中，額度快取是 usage_cache(**cache)（識別碼預設 acct-1）。"""
        self.write_claude_json(claude_json(usage_cache(**cache), oauth))

    def poll_card(self, **cache):
        self.write_cache(**cache)
        return self.core.poll().cards[0]


def acl_entries(path):
    """icacls 列出的 ACE：只取第一個空行之前，第一行去掉開頭的路徑。"""
    out = subprocess.run(["icacls", str(path)], capture_output=True, text=True, errors="replace").stdout
    entries = []
    for i, line in enumerate(out.splitlines()):
        if not line.strip():
            break
        entries.append((line[len(str(path)):] if i == 0 else line).strip())
    return entries


class WindowsAclAssertions:
    """在 Windows 真實暫存目錄上驗證：不繼承、只授權目前使用者。以 icacls 與 whoami 當獨立的驗證來源。"""

    def assert_private(self, path):
        user = subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip().lower()
        entries = acl_entries(path)
        self.assertEqual(len(entries), 1, (path.name, entries))
        entry = entries[0].lower()
        self.assertTrue(entry.startswith(user + ":"), (path.name, entries))
        self.assertIn("(f)", entry)
        self.assertNotIn("(i)", entry)  # 不是繼承來的
