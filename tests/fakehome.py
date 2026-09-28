"""假 home 與可控時鐘：所有核心測試共用的骨架。"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cc_quota_tracker.core import Core

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


def usage_cache(fetched_at=NOW, session=10, weekly=40, resets_at=None):
    resets = (resets_at or NOW + timedelta(days=3)).isoformat()
    return {
        "fetchedAtMs": int(fetched_at.timestamp() * 1000),
        "accountUuid": "acct-1",
        "utilization": {"limits": [
            {"kind": "session", "percent": session, "severity": "normal",
             "resets_at": resets, "is_active": True},
            {"kind": "weekly_all", "percent": weekly, "severity": "normal",
             "resets_at": resets, "is_active": True},
        ]},
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
