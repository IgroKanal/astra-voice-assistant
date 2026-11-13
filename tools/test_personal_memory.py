from pathlib import Path
import sqlite3
import json
from contextlib import closing
import sys
import tempfile
import unittest
import win32crypt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.personal_memory import PersonalMemory


class PersonalMemoryTests(unittest.TestCase):
    def test_encrypted_persistence_search_and_forget(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.sqlite"
            memory = PersonalMemory(path)
            identity = memory.add("Язык", "Отвечать по-русски")
            reopened = PersonalMemory(path)
            self.assertEqual(reopened.search("РУССКИ")[0].text, "Отвечать по-русски")
            self.assertNotIn("Отвечать".encode(), path.read_bytes())
            self.assertTrue(reopened.forget(identity))
            self.assertEqual(reopened.search(), [])
            self.assertFalse(reopened.forget(identity))

    def test_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            memory = PersonalMemory(Path(temp) / "memory.sqlite")
            for title, text in [("", "x"), ("x", ""), ("x" * 201, "x"), ("x", "x" * 16001)]:
                with self.assertRaises(ValueError):
                    memory.add(title, text)

    def test_tampered_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.sqlite"
            memory = PersonalMemory(path)
            identity = memory.add("title", "note")
            with closing(sqlite3.connect(path)) as db:
                with db:
                    db.execute("UPDATE notes SET payload=? WHERE id=?", (b"broken", identity))
            with self.assertRaises(Exception):
                memory.search()

    def test_newer_database_is_not_downgraded(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.sqlite"
            with closing(sqlite3.connect(path)) as db:
                db.execute("PRAGMA user_version=99")
            with self.assertRaises(ValueError):
                PersonalMemory(path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 99)

    def test_ciphertext_backup_restores_and_never_overwrites_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = PersonalMemory(root / "source.sqlite")
            identity = source.add("Домашний город", "Сосновый город")
            backup = root / "memory.astra-memory.json"
            self.assertEqual(source.create_backup(backup), 1)
            raw_backup = backup.read_bytes()
            self.assertNotIn("Сосновый город".encode(), raw_backup)
            self.assertNotIn("Домашний город".encode(), raw_backup)

            restored = PersonalMemory(root / "restored.sqlite")
            restored.add("Своя заметка", "Оставить как есть")
            self.assertEqual(restored.preview_restore(backup), (1, 0))
            # Preview is read-only until the user confirms in the UI.
            self.assertEqual(len(restored.search()), 1)
            self.assertEqual(restored.restore_backup(backup), (1, 0))
            self.assertEqual(restored.search()[0].text, "Сосновый город")

            # Same identity in a destination wins; restoring cannot replace its payload.
            conflict = PersonalMemory(root / "conflict.sqlite")
            with conflict._connect() as db:
                db.execute("INSERT INTO notes(id,payload) VALUES (?,?)", (identity, win32crypt.CryptProtectData(
                    json.dumps({"title": "Локальная версия", "text": "Не заменять"}).encode(), "Astra personal note", None, None, None, 1)))
            before = conflict.search()[0]
            self.assertEqual(conflict.preview_restore(backup), (0, 1))
            self.assertEqual(conflict.restore_backup(backup), (0, 1))
            after = conflict.search()[0]
            self.assertEqual((after.title, after.text), (before.title, before.text))

    def test_backup_refuses_overwrite_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            memory = PersonalMemory(root / "memory.sqlite")
            memory.add("Личное", "Секретный текст теста")
            backup = root / "backup.json"
            memory.create_backup(backup)
            original = backup.read_bytes()
            with self.assertRaises(FileExistsError):
                memory.create_backup(backup)
            self.assertEqual(backup.read_bytes(), original)

            tampered = json.loads(original)
            tampered["notes"][0]["payload"] = "broken"
            bad_path = root / "tampered.json"
            bad_path.write_text(json.dumps(tampered), encoding="utf-8")
            target = PersonalMemory(root / "target.sqlite")
            with self.assertRaises(ValueError):
                target.preview_restore(bad_path)
            self.assertEqual(target.search(), [])

    def test_portable_backup_migrates_across_windows_account_protection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = PersonalMemory(root / "source.sqlite")
            identity = source.add("Любимый формат", "Аниме с хорошим сюжетом")
            backup = root / "memory.astra-memory-portable"
            phrase = "correct horse battery staple"
            self.assertEqual(source.create_portable_backup(backup, phrase), 1)
            payload = backup.read_bytes()
            self.assertNotIn("Любимый формат".encode(), payload)
            self.assertNotIn("Аниме с хорошим сюжетом".encode(), payload)

            target = PersonalMemory(root / "target.sqlite")
            target.add("Локальная", "Оставить как есть")
            self.assertEqual(target.preview_portable_restore(backup, phrase), (1, 0))
            self.assertEqual(len(target.search()), 1)
            self.assertEqual(target.restore_portable_backup(backup, phrase), (1, 0))
            migrated = {note.id: note for note in target.search()}
            self.assertIn(identity, migrated)
            self.assertEqual(migrated[identity].text, "Аниме с хорошим сюжетом")
            # Imported data is protected by this account's DPAPI, not portable ciphertext.
            with closing(sqlite3.connect(target.path)) as db:
                stored = db.execute("SELECT payload FROM notes WHERE id=?", (identity,)).fetchone()[0]
            self.assertNotEqual(stored, payload)
            self.assertNotIn("Аниме с хорошим сюжетом".encode(), stored)

    def test_portable_backup_wrong_phrase_and_tampering_do_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = PersonalMemory(root / "source.sqlite")
            source.add("Тема", "Переносимая заметка")
            backup = root / "memory.astra-memory-portable"
            source.create_portable_backup(backup, "passphrase with enough length")
            target = PersonalMemory(root / "target.sqlite")
            with self.assertRaises(ValueError):
                target.preview_portable_restore(backup, "wrong phrase of enough length")
            self.assertEqual(target.search(), [])

            raw = bytearray(backup.read_bytes())
            raw[-5] ^= 1
            tampered = root / "tampered.astra-memory-portable"
            tampered.write_bytes(raw)
            with self.assertRaises(ValueError):
                target.restore_portable_backup(tampered, "passphrase with enough length")
            self.assertEqual(target.search(), [])

    def test_portable_backup_requires_long_phrase_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = PersonalMemory(root / "source.sqlite")
            source.add("Тема", "Текст")
            backup = root / "memory.astra-memory-portable"
            with self.assertRaises(ValueError):
                source.create_portable_backup(backup, "short")
            self.assertFalse(backup.exists())
            phrase = "another sufficiently long phrase"
            source.create_portable_backup(backup, phrase)
            original = backup.read_bytes()
            with self.assertRaises(FileExistsError):
                source.create_portable_backup(backup, phrase)
            self.assertEqual(backup.read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
