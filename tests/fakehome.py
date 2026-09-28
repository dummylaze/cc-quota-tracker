"""假 home 與可控時鐘：所有核心測試共用的骨架。"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cc_quota_tracker.core import Core

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


def usage_cache(fetched_at=NOW, session=10, weekly=40, resets_at=None, limits=None, **fields):
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
        "accountUuid": "acct-1",
        "utilization": dict(fields, limits=limits),
    }


class HomeTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.clock = FakeClock()
        self.core = Core(self.home, self.clock)

    def write_claude_json(self, data):
        (self.home / ".claude.json").write_text(json.dumps(data), encoding="utf-8")

    def poll_card(self, **cache):
        self.write_claude_json({"cachedUsageUtilization": usage_cache(**cache)})
        return self.core.poll().cards[0]
