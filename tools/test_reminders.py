from pathlib import Path
import sys
import tempfile
import threading
import unittest
import sqlite3
from contextlib import closing
import json
import win32crypt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.reminders import ReminderStore


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "reminders.sqlite"
        self.store = ReminderStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_encrypted_persistence_and_due_time(self):
        identity = self.store.add("Тестовое напоминание", 100)
        self.assertNotIn("напоминание".encode("utf-8"), self.path.read_bytes())
        reopened = ReminderStore(self.path)
        self.assertEqual(reopened.list()[0].id, identity)
        self.assertEqual(reopened.claim_due(99), [])
        claimed = reopened.claim_due(100)
        self.assertEqual(claimed[0].text, "Тестовое напоминание")

    def test_leases_prevent_duplicates_and_recover_after_crash(self):
        identity = self.store.add("x", 100)
        first = self.store.claim_due(100, lease_seconds=30)[0]
        self.assertEqual(self.store.claim_due(129), [])
        second = self.store.claim_due(130)[0]
        self.assertNotEqual(first.token, second.token)
        self.assertFalse(self.store.acknowledge(identity, first.token))
        self.assertTrue(self.store.acknowledge(identity, second.token))
        self.assertEqual(self.store.claim_due(999), [])

    def test_cancel_invalidates_queued_delivery(self):
        identity = self.store.add("x", 100)
        claim = self.store.claim_due(100)[0]
        self.assertTrue(self.store.cancel(identity))
        self.assertFalse(self.store.valid_claim(identity, claim.token))
        self.assertFalse(self.store.acknowledge(identity, claim.token))
        self.assertEqual(self.store.claim_due(999), [])

    def test_cancel_next_atomically_cancels_only_earliest_active_reminder(self):
        later = self.store.add("later", 300)
        next_pending = self.store.add("next", 200)
        delivered = self.store.add("delivered", 50)
        delivered_claim = self.store.claim_due(50)[0]
        self.assertTrue(self.store.acknowledge(delivered, delivered_claim.token))
        next_delivering = self.store.add("delivering", 100)
        delivery_claim = self.store.claim_due(100)[0]

        self.assertTrue(self.store.cancel_next())
        self.assertFalse(self.store.valid_claim(next_delivering, delivery_claim.token))
        self.assertFalse(self.store.acknowledge(next_delivering, delivery_claim.token))
        self.assertTrue(self.store.cancel_next())
        self.assertTrue(self.store.cancel_next())
        self.assertFalse(self.store.cancel_next())

        states = {item.id: item.state for item in self.store.list()}
        self.assertEqual(states[next_delivering], "cancelled")
        self.assertEqual(states[next_pending], "cancelled")
        self.assertEqual(states[later], "cancelled")
        self.assertEqual(states[delivered], "delivered")

    def test_delivered_reminder_stays_unread_across_restart(self):
        identity = self.store.add("x", 100)
        claim = self.store.claim_due(100)[0]
        self.store.acknowledge(identity, claim.token)
        reopened = ReminderStore(self.path)
        self.assertEqual(reopened.unread_count(), 1)
        self.assertTrue(reopened.complete(identity))
        self.assertEqual(reopened.unread_count(), 0)

    def test_two_workers_do_not_claim_same_reminder(self):
        self.store.add("x", 100)
        results = []
        threads = [threading.Thread(target=lambda: results.extend(ReminderStore(self.path).claim_due(100))) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(len(results), 1)

    def test_invalid_payload_and_time(self):
        for text, due in [("", 100), ("x" * 4001, 100), ("x", float("nan")), ("x", -1)]:
            with self.assertRaises(ValueError):
                self.store.add(text, due)

    def test_portable_backup_migrates_pending_and_unread_but_not_delivery_leases(self):
        root = Path(self.temp.name)
        pending_id = self.store.add("Будущая задача", 500)
        unread_id = self.store.add("Уже доставлено", 100)
        claim = self.store.claim_due(100)[0]
        self.assertEqual(claim.id, unread_id)
        self.assertTrue(self.store.acknowledge(unread_id, claim.token))
        completed_id = self.store.add("Закрытая задача", 200)
        completed_claim = self.store.claim_due(200)[0]
        self.store.acknowledge(completed_id, completed_claim.token)
        self.store.complete(completed_id)

        backup = root / "reminders.astra-reminders-portable"
        phrase = "portable reminder secret phrase"
        self.assertEqual(self.store.create_portable_backup(backup, phrase), 2)
        payload = backup.read_bytes()
        self.assertNotIn("Будущая задача".encode(), payload)
        self.assertNotIn("Уже доставлено".encode(), payload)

        target = ReminderStore(root / "target.sqlite")
        self.assertEqual(target.preview_portable_restore(backup, phrase), (2, 0))
        self.assertEqual(target.restore_portable_backup(backup, phrase), (2, 0))
        by_id = {item.id: item for item in target.list()}
        self.assertEqual(by_id[pending_id].state, "pending")
        self.assertEqual(by_id[pending_id].text, "Будущая задача")
        self.assertEqual(by_id[unread_id].state, "delivered")
        self.assertNotIn(completed_id, by_id)
        with closing(sqlite3.connect(target.path)) as db:
            encrypted = db.execute("SELECT payload FROM reminders WHERE id=?", (pending_id,)).fetchone()[0]
        self.assertNotIn("Будущая задача".encode(), encrypted)

    def test_portable_reminder_bad_phrase_tampering_and_conflicts_fail_closed(self):
        root = Path(self.temp.name)
        identity = self.store.add("Приватный текст", 100)
        backup = root / "reminders.astra-reminders-portable"
        phrase = "secure reminder migration phrase"
        self.store.create_portable_backup(backup, phrase)
        target = ReminderStore(root / "target.sqlite")
        with self.assertRaises(ValueError):
            target.preview_portable_restore(backup, "different phrase still long enough")
        self.assertEqual(target.list(), [])

        tampered = bytearray(backup.read_bytes())
        tampered[-3] ^= 1
        bad = root / "bad.astra-reminders-portable"
        bad.write_bytes(tampered)
        with self.assertRaises(ValueError):
            target.restore_portable_backup(bad, phrase)
        self.assertEqual(target.list(), [])

        existing = win32crypt.CryptProtectData(b"local text", "Astra reminder", None, None, None, 1)
        with target.connect() as db:
            db.execute("INSERT INTO reminders(id,due,state,payload) VALUES (?,100,'pending',?)", (identity, existing))
        self.assertEqual(target.restore_portable_backup(backup, phrase), (0, 1))
        self.assertEqual(target.list()[0].text, "local text")


if __name__ == "__main__":
    unittest.main(verbosity=2)
