import json
import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

from cc_quota_tracker.core import AddWarning, BindingsUnreadable, InvalidLabel, NoCredential, UnknownLabel
from tests.fakehome import HomeTestCase, WindowsAclAssertions

# SHA-256 前 16 個十六進位字元，事先算好的字面值
KEY_RT1 = "a33d8c625833429d"  # refreshToken "rt-1"
KEY_RT2 = "1f23b7dadfb229cb"  # refreshToken "rt-2"
KEY_RT3 = "a9647bb04ede2838"  # refreshToken "rt-3"


class ManageTestCase(HomeTestCase):
    def snapshot(self, label):
        return self.home / ".claude-multi" / f"{label}.json"

    def bindings(self):
        path = self.home / ".claude-multi" / ".state" / "bindings.json"
        return json.loads(path.read_text(encoding="utf-8"))


class AddTest(ManageTestCase):
    def test_add_copies_current_credential_as_snapshot(self):
        self.log_in()
        self.core.add("work")
        current = (self.home / ".claude" / ".credentials.json").read_bytes()
        self.assertEqual(self.snapshot("work").read_bytes(), current)

    def test_add_binds_fingerprint_to_account_id(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.core.add("work")
        self.assertEqual(self.bindings(), {KEY_RT1: {"accountId": "acct-1"}})

    def test_board_lists_managed_accounts_by_provider_prefixed_label(self):
        self.log_in()
        self.core.add("work")
        self.snapshot("home").write_bytes(self.snapshot("work").read_bytes())  # 直接放進目錄的憑證快照
        self.assertEqual(self.core.poll().managed_accounts, ("claude:home", "claude:work"))

    def test_no_managed_accounts_before_any_add(self):
        self.assertEqual(self.core.poll().managed_accounts, ())

    def test_each_managed_account_keeps_its_own_binding(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.core.add("work")
        self.log_in(refresh="rt-2", account_uuid="acct-2")
        self.core.add("home")
        self.assertEqual(self.bindings(), {KEY_RT1: {"accountId": "acct-1"},
                                           KEY_RT2: {"accountId": "acct-2"}})

    def test_add_to_existing_label_remanages_it(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.core.add("work")
        self.log_in(refresh="rt-2", account_uuid="acct-1")  # 同一帳號重新登入，拿到新的 refreshToken
        self.core.add("work")
        current = (self.home / ".claude" / ".credentials.json").read_bytes()
        self.assertEqual(self.snapshot("work").read_bytes(), current)
        self.assertEqual(self.bindings(), {KEY_RT2: {"accountId": "acct-1"}})
        self.assertEqual(self.core.poll().managed_accounts, ("claude:work",))

    def test_add_without_current_credential_writes_nothing(self):
        self.write_claude_json({"oauthAccount": {"accountUuid": "acct-1"}})
        with self.assertRaises(NoCredential):
            self.core.add("work")
        self.assertFalse((self.home / ".claude-multi").exists())

    def test_add_with_unreadable_credential_keeps_existing_snapshot(self):
        self.log_in()
        self.core.add("work")
        before = self.snapshot("work").read_bytes()
        (self.home / ".claude" / ".credentials.json").write_text('{"claudeAiOauth": {"acc', encoding="utf-8")
        with self.assertRaises(NoCredential):
            self.core.add("work")
        self.assertEqual(self.snapshot("work").read_bytes(), before)
        self.assertEqual(self.bindings(), {KEY_RT1: {"accountId": "acct-1"}})

    def test_add_without_account_id_keeps_snapshot_unbound_and_warns(self):
        self.write_credentials()  # 有憑證，但 ~/.claude.json 不存在
        result = self.core.add("work")
        self.assertIn(AddWarning.NOT_BOUND, result.warnings)
        self.assertTrue(self.snapshot("work").exists())
        self.assertEqual(self.bindings(), {})
        self.log_in()
        self.assertNotIn(AddWarning.NOT_BOUND, self.core.add("work").warnings)

    def test_email_like_label_is_flagged(self):
        self.log_in()
        self.assertIn(AddWarning.LABEL_LOOKS_LIKE_EMAIL, self.core.add("someone@example.com").warnings)
        self.assertNotIn(AddWarning.LABEL_LOOKS_LIKE_EMAIL, self.core.add("work").warnings)
        self.assertNotIn(AddWarning.LABEL_LOOKS_LIKE_EMAIL, self.core.add("team@home").warnings)

    def test_label_that_is_not_a_plain_file_name_is_rejected(self):
        self.log_in()
        for label in ["", " ", "../work", "a/b", "a\\b", "a:b", ".hidden", "work.", "con", "NUL", "a*b"]:
            with self.subTest(label=label), self.assertRaises(InvalidLabel):
                self.core.add(label)
        self.assertFalse((self.home / "work.json").exists())
        self.assertEqual(self.core.poll().managed_accounts, ())

    def test_polls_and_add_leave_claude_code_files_untouched(self):
        self.log_in()
        settings = self.home / ".claude" / "settings.json"
        settings.write_text("{}", encoding="utf-8")
        watched = [self.home / ".claude.json", self.home / ".claude" / ".credentials.json", settings]
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in watched]
        self.core.poll()
        self.core.add("work")
        self.core.poll()
        self.core.remove("work")
        self.core.poll()
        self.assertEqual([(p.read_bytes(), p.stat().st_mtime_ns) for p in watched], before)

    def test_email_from_claude_json_is_never_stored(self):
        self.log_in()  # oauthAccount 帶著 emailAddress
        self.core.add("work")
        for path in (self.home / ".claude-multi").rglob("*"):
            if path.is_file():
                self.assertNotIn(b"example.com", path.read_bytes(), path.name)

    def test_add_returns_provider_prefixed_account_key(self):
        self.log_in()
        self.assertEqual(self.core.add("work").account_key, "claude:work")


class RemoveTest(ManageTestCase):
    def test_remove_deletes_snapshot_and_its_binding(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.core.add("work")
        self.log_in(refresh="rt-2", account_uuid="acct-2")
        self.core.add("home")
        self.core.remove("work")
        self.assertFalse(self.snapshot("work").exists())
        self.assertEqual(self.bindings(), {KEY_RT2: {"accountId": "acct-2"}})
        self.assertEqual(self.core.poll().managed_accounts, ("claude:home",))

    def test_remove_unknown_label_is_rejected(self):
        self.log_in()
        self.core.add("work")
        with self.assertRaises(UnknownLabel):
            self.core.remove("home")
        self.assertTrue(self.snapshot("work").exists())


class ImportTest(ManageTestCase):
    """匯入憑證檔：複製進納管目錄並收緊權限；綁定不在這裡決定，沿用直接放檔的補學規則。"""

    def credential_file(self, name="work.json", refresh="rt-1"):
        path = self.home / "Downloads" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(self.write_credentials(refresh=refresh).read_bytes())
        return path

    def test_copies_the_file_as_a_snapshot_under_the_label(self):
        source = self.credential_file()
        result = self.core.import_snapshot(source, "work")
        self.assertEqual(result.account_key, "claude:work")
        self.assertEqual(self.snapshot("work").read_bytes(), source.read_bytes())
        self.assertTrue(source.exists())
        self.assertEqual(self.core.poll().managed_accounts, ("claude:work",))

    def test_does_not_bind_and_says_so(self):
        # 補學由 poll 依三個條件決定；匯入時連 oauthAccount 都不看
        self.log_in(refresh="rt-9", account_uuid="acct-9")
        result = self.core.import_snapshot(self.credential_file(refresh="rt-1"), "work")
        self.assertIn(AddWarning.NOT_BOUND, result.warnings)
        self.assertNotIn(KEY_RT1, self.bindings())

    def test_learns_binding_later_by_the_drop_in_rule(self):
        source = self.credential_file(refresh="rt-1")
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.core.import_snapshot(source, "work")
        self.write_cache(oauth="acct-1", account_uuid="acct-1")
        self.core.poll()
        self.assertEqual(self.bindings(), {KEY_RT1: {"accountId": "acct-1"}})

    def test_keeps_an_existing_binding_for_the_same_credential(self):
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.core.add("old-name")
        result = self.core.import_snapshot(self.credential_file(refresh="rt-1"), "work")
        self.assertNotIn(AddWarning.NOT_BOUND, result.warnings)

    def test_file_that_is_not_a_credential_writes_nothing(self):
        source = self.home / "notes.json"
        source.write_text('{"hello": 1}', encoding="utf-8")
        with self.assertRaises(NoCredential):
            self.core.import_snapshot(source, "notes")
        self.assertFalse(self.snapshot("notes").exists())

    def test_label_rules_and_email_hint_match_add(self):
        with self.assertRaises(InvalidLabel):
            self.core.import_snapshot(self.credential_file(), "../escape")
        result = self.core.import_snapshot(self.credential_file(), "me@example.com")
        self.assertIn(AddWarning.LABEL_LOOKS_LIKE_EMAIL, result.warnings)


class LockedFileTest(ManageTestCase):
    """綁定檔或其他憑證快照暫時讀不到（被防毒或其他程式鎖住）時，納管與移除不得洗掉其他帳號的綁定與待命讀數。"""

    def setUp(self):
        super().setUp()
        self.log_in(refresh="rt-1", account_uuid="acct-1")
        self.core.add("work")
        self.write_cache(oauth="acct-1", account_uuid="acct-1")
        self.core.poll()
        self.log_in(refresh="rt-2", account_uuid="acct-2")
        self.core.add("home")
        self.write_cache(oauth="acct-2", account_uuid="acct-2")
        self.core.poll()
        self.log_in(refresh="rt-3", account_uuid="acct-3")

    def readings(self):
        path = self.home / ".claude-multi" / ".state" / "readings.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def managed_files(self):
        root = self.home / ".claude-multi"
        return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def credential_file(self, refresh):
        path = self.home / "Downloads" / "work.json"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(self.write_credentials(refresh=refresh).read_bytes())
        return path

    def test_add_with_unreadable_bindings_file_changes_nothing(self):
        before = self.managed_files()
        with self.locked("bindings.json"), self.assertRaises(BindingsUnreadable) as raised:
            self.core.add("third")
        self.assertEqual(raised.exception.path, self.home / ".claude-multi" / ".state" / "bindings.json")
        self.assertEqual(self.managed_files(), before)

    def test_import_over_an_existing_label_with_unreadable_bindings_file_changes_nothing(self):
        source = self.credential_file(refresh="rt-3")
        before = self.managed_files()
        with self.locked("bindings.json"), self.assertRaises(BindingsUnreadable):
            self.core.import_snapshot(source, "work")
        self.assertEqual(self.managed_files(), before)

    def test_remove_with_unreadable_bindings_file_deletes_the_snapshot_only(self):
        before = (self.home / ".claude-multi" / ".state" / "bindings.json").read_bytes()
        with self.locked("bindings.json"):
            self.core.remove("home")
        self.assertFalse(self.snapshot("home").exists())
        self.assertEqual((self.home / ".claude-multi" / ".state" / "bindings.json").read_bytes(), before)
        self.core.poll()  # 恢復可讀後，孤兒綁定由 poll 清掉
        self.assertEqual(self.bindings(), {KEY_RT1: {"accountId": "acct-1"}})

    def test_add_while_another_snapshot_is_unreadable_only_adds_its_own_binding(self):
        with self.locked("work.json"):
            self.core.add("third")
        self.assertEqual(set(self.bindings()), {KEY_RT1, KEY_RT2, KEY_RT3})
        self.assertEqual(set(self.readings()), {"acct-1", "acct-2"})

    def test_import_while_another_snapshot_is_unreadable_prunes_nothing(self):
        source = self.credential_file(refresh="rt-3")
        with self.locked("work.json"):
            self.core.import_snapshot(source, "third")
        self.assertEqual(set(self.bindings()), {KEY_RT1, KEY_RT2})
        self.assertEqual(set(self.readings()), {"acct-1", "acct-2"})

    def test_remove_while_another_snapshot_is_unreadable_prunes_nothing(self):
        with self.locked("work.json"):
            self.core.remove("home")
        self.assertFalse(self.snapshot("home").exists())
        self.assertIn(KEY_RT1, self.bindings())
        self.assertIn("acct-1", self.readings())
        self.core.poll()  # 都讀得到之後，孤兒綁定與它的讀數由 poll 清掉
        self.assertEqual(self.bindings(), {KEY_RT1: {"accountId": "acct-1"}})
        self.assertEqual(set(self.readings()), {"acct-1"})


class AtomicWriteTest(ManageTestCase):
    """工具狀態一律原子寫入：暫存檔建在目標同一目錄、帶工具前綴，權限錯誤重試，失敗清掉殘留。"""

    def replace_failing(self, times):
        real, calls = os.replace, []

        def fake(src, dst):
            calls.append((Path(src), Path(dst)))
            if len(calls) <= times:
                raise PermissionError("locked by another process")
            real(src, dst)
        return mock.patch("os.replace", side_effect=fake), calls

    def leftovers(self):
        return [p.name for p in (self.home / ".claude-multi").rglob("*") if "cc-quota-tracker" in p.name]

    def test_temp_file_is_created_next_to_its_target_with_tool_prefix(self):
        self.log_in()
        patch, calls = self.replace_failing(0)
        with patch:
            self.core.add("work")
        self.assertEqual({dst.name for _, dst in calls}, {"work.json", "bindings.json"})
        for src, dst in calls:
            self.assertEqual(src.parent, dst.parent)
            self.assertTrue(src.name.startswith(".cc-quota-tracker-"), src.name)

    def test_transient_permission_errors_are_retried(self):
        self.log_in()
        patch, _ = self.replace_failing(3)
        with patch:
            self.core.add("work")
        self.assertEqual(self.core.poll().managed_accounts, ("claude:work",))
        self.assertEqual(self.leftovers(), [])

    def test_persistent_permission_error_fails_and_cleans_up(self):
        self.log_in(refresh="rt-1")
        self.core.add("work")
        before = self.snapshot("work").read_bytes()
        self.log_in(refresh="rt-2")
        patch, calls = self.replace_failing(4)
        with patch, self.assertRaises(PermissionError):
            self.core.add("work")
        self.assertEqual(len(calls), 4)  # 第一次加上重試 3 次
        self.assertEqual(self.snapshot("work").read_bytes(), before)
        self.assertEqual(self.leftovers(), [])

    def test_remove_retries_transient_permission_errors(self):
        self.log_in()
        self.core.add("work")
        real, calls = os.unlink, []

        def flaky(path, *args, **kwargs):
            calls.append(path)
            if len(calls) <= 3:
                raise PermissionError("locked by another process")
            real(path, *args, **kwargs)
        with mock.patch("os.unlink", side_effect=flaky):
            self.core.remove("work")
        self.assertEqual(len(calls), 4)  # 故障確實注入：失敗 3 次後成功
        self.assertFalse(self.snapshot("work").exists())


@unittest.skipUnless(sys.platform == "win32", "Windows ACL")
class WindowsPermissionTest(WindowsAclAssertions, ManageTestCase):
    def managed_paths(self):
        state = self.home / ".claude-multi" / ".state"
        return [self.home / ".claude-multi", self.snapshot("work"), state, state / "bindings.json"]

    def test_add_tightens_new_directory_and_files(self):
        self.log_in()
        result = self.core.add("work")
        for path in self.managed_paths():
            self.assert_private(path)
        self.assertNotIn(AddWarning.PERMISSIONS_FIXED, result.warnings)

    def test_add_fixes_loose_existing_directory_and_warns(self):
        (self.home / ".claude-multi").mkdir()  # 繼承暫存目錄的權限：系統、系統管理員都讀得到
        self.log_in()
        result = self.core.add("work")
        for path in self.managed_paths():
            self.assert_private(path)
        self.assertIn(AddWarning.PERMISSIONS_FIXED, result.warnings)

    def test_import_tightens_the_snapshot(self):
        source = self.home / "work.json"
        source.write_bytes(self.write_credentials().read_bytes())
        self.core.import_snapshot(source, "work")
        for path in self.managed_paths():
            self.assert_private(path)

    def test_add_fixes_snapshot_dropped_in_directly_and_warns(self):
        self.log_in()
        self.core.add("work")
        self.snapshot("home").write_bytes(self.snapshot("work").read_bytes())  # 權限靠繼承
        result = self.core.add("work")
        self.assert_private(self.snapshot("home"))
        self.assertIn(AddWarning.PERMISSIONS_FIXED, result.warnings)


@unittest.skipIf(sys.platform == "win32", "POSIX mode bits")
class PosixPermissionTest(ManageTestCase):
    def test_add_sets_700_directories_and_600_files(self):
        (self.home / ".claude-multi").mkdir(mode=0o755)
        self.log_in()
        result = self.core.add("work")
        state = self.home / ".claude-multi" / ".state"
        for path, mode in [(self.home / ".claude-multi", 0o700), (state, 0o700),
                           (self.snapshot("work"), 0o600), (state / "bindings.json", 0o600)]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode, path.name)
        self.assertIn(AddWarning.PERMISSIONS_FIXED, result.warnings)


if __name__ == "__main__":
    unittest.main()
