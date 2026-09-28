import unittest
from datetime import timedelta

from cc_quota_tracker.credstore import FileCredentialStore
from tests.fakehome import NOW, HomeTestCase


class FileCredentialStoreTest(HomeTestCase):
    """內容雜湊在縫 ① 觀察不到，直接測憑證儲存介面。"""

    def store(self, **credentials):
        return FileCredentialStore(self.write_credentials(**credentials))

    def test_refresh_keeps_identity_key_and_content_hash(self):
        before = self.store(access="at-1", expires_at=NOW)
        key, digest = before.identity_key(), before.content_hash()
        after = self.store(access="at-2", expires_at=NOW + timedelta(hours=8))
        self.assertEqual((after.identity_key(), after.content_hash()), (key, digest))

    def test_new_refresh_token_changes_identity_key_and_content_hash(self):
        before = self.store(refresh="rt-1")
        key, digest = before.identity_key(), before.content_hash()
        after = self.store(refresh="rt-2")
        self.assertNotEqual(after.identity_key(), key)
        self.assertNotEqual(after.content_hash(), digest)

    def test_read_gives_refresh_token_expiry_without_tokens(self):
        store = self.store(refresh="rt-secret", access="at-secret", refresh_expires_at=NOW + timedelta(days=5))
        credential = store.read()
        self.assertEqual(credential.refresh_token_expires_at, NOW + timedelta(days=5))
        for value in (repr(credential), store.identity_key(), store.content_hash()):
            self.assertNotIn("secret", value)

    def test_missing_or_unreadable_credential_reads_as_none(self):
        store = FileCredentialStore(self.home / "nope.json")
        self.assertEqual((store.read(), store.identity_key(), store.content_hash()), (None, None, None))
        path = self.write_credentials()
        path.write_text('{"claudeAiOauth": {"ref', encoding="utf-8")
        store = FileCredentialStore(path)
        self.assertEqual((store.read(), store.identity_key(), store.content_hash()), (None, None, None))


if __name__ == "__main__":
    unittest.main()
