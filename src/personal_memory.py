"""Explicit local notes encrypted for the current Windows account using DPAPI."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import json
import base64
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

import win32crypt
from src.portable_memory_backup import MAX_BACKUP_BYTES as PORTABLE_MAX_BACKUP_BYTES, decrypt_memory, encrypt_memory


@dataclass(frozen=True)
class MemoryNote:
    id: str
    title: str
    text: str


class PersonalMemory:
    MAX_NOTES = 1000
    BACKUP_SCHEMA = 1
    MAX_BACKUP_BYTES = 32 * 1024 * 1024

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Эта версия базы памяти требует более новой Astra")
            db.execute("CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, payload BLOB NOT NULL)")
            if version == 0:
                db.execute("PRAGMA user_version=1")

    def context(self, question: str, limit: int = 2000) -> str:
        import re
        words = set(re.findall(r"[\w]{3,}", question.casefold()))
        notes = self.search()
        ranked = sorted(notes, key=lambda note: sum(word in (note.title + " " + note.text).casefold() for word in words), reverse=True)
        selected = []
        remaining = min(2000, max(0, limit))
        for note in ranked[:3]:
            if remaining < 100:
                break
            title = note.title[:200]
            text = note.text[:max(0, remaining - len(title) - 50)]
            selected.append({"title": title, "text": text})
            remaining -= len(title) + len(text) + 50
        while selected:
            encoded = json.dumps(selected, ensure_ascii=False)
            if len(encoded) <= min(2000, max(0, limit)):
                return encoded
            overflow = len(encoded) - min(2000, max(0, limit))
            if len(selected[-1]["text"]) > overflow:
                selected[-1]["text"] = selected[-1]["text"][:-overflow]
            else:
                selected.pop()
        return ""

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA secure_delete=ON")
            with db:
                yield db
        finally:
            db.close()

    def add(self, title: str, text: str) -> str:
        title, text = title.strip(), text.strip()
        if not title or not text or len(title) > 200 or len(text) > 16000:
            raise ValueError("Нужны название (до 200 символов) и текст (до 16000)")
        identity = uuid4().hex
        data = json.dumps({"title": title, "text": text}, ensure_ascii=False).encode("utf-8")
        encrypted = win32crypt.CryptProtectData(data, "Astra personal note", None, None, None, 1)
        with self._connect() as db:
            if db.execute("SELECT count(*) FROM notes").fetchone()[0] >= self.MAX_NOTES:
                raise ValueError("Достигнут лимит 1000 записей")
            db.execute("INSERT INTO notes VALUES (?,?)", (identity, encrypted))
        return identity

    def search(self, query: str = "") -> list[MemoryNote]:
        with self._connect() as db:
            rows = db.execute("SELECT id,payload FROM notes ORDER BY rowid DESC LIMIT ?", (self.MAX_NOTES,)).fetchall()
        notes = []
        for identity, encrypted in rows:
            raw = win32crypt.CryptUnprotectData(encrypted, None, None, None, 1)[1]
            data = json.loads(raw.decode("utf-8"))
            if query.casefold() in (data["title"] + "\n" + data["text"]).casefold():
                notes.append(MemoryNote(identity, data["title"], data["text"]))
        return notes

    def forget(self, identity: str) -> bool:
        with self._connect() as db:
            return db.execute("DELETE FROM notes WHERE id=?", (identity,)).rowcount > 0

    @staticmethod
    def _backup_digest(payload: dict) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def create_backup(self, destination: Path) -> int:
        """Write a ciphertext-only backup, refusing to overwrite an existing path."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Файл резервной копии уже существует")
        with self._connect() as db:
            rows = db.execute("SELECT id,payload FROM notes ORDER BY id").fetchall()
        backup = {
            "schema": self.BACKUP_SCHEMA,
            "notes": [
                {"id": identity, "payload": base64.b64encode(bytes(payload)).decode("ascii")}
                for identity, payload in rows
            ],
        }
        document = dict(backup, sha256=self._backup_digest(backup))
        encoded = (json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > self.MAX_BACKUP_BYTES:
            raise ValueError("Резервная копия превышает допустимый размер")
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, prefix=".astra-memory-", delete=False) as temp:
                temp_path = Path(temp.name)
                temp.write(encoded)
                temp.flush()
                os.fsync(temp.fileno())
            # Hard-link creation is atomic and fails if another process created destination.
            os.link(temp_path, destination)
            return len(rows)
        except FileExistsError:
            raise FileExistsError("Файл резервной копии уже существует") from None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _read_backup(self, source: Path) -> list[tuple[str, bytes]]:
        source = Path(source)
        if source.is_symlink() or not source.is_file() or source.stat().st_size > self.MAX_BACKUP_BYTES:
            raise ValueError("Некорректный или слишком большой файл резервной копии")
        try:
            document = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or set(document) != {"schema", "notes", "sha256"}:
                raise ValueError
            payload = {"schema": document["schema"], "notes": document["notes"]}
            if document["schema"] != self.BACKUP_SCHEMA or not isinstance(document["notes"], list):
                raise ValueError
            if len(document["notes"]) > self.MAX_NOTES or document["sha256"] != self._backup_digest(payload):
                raise ValueError
            result = []
            seen = set()
            for item in document["notes"]:
                if not isinstance(item, dict) or set(item) != {"id", "payload"}:
                    raise ValueError
                identity = item["id"]
                encoded = item["payload"]
                if not isinstance(identity, str) or len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
                    raise ValueError
                if identity in seen or not isinstance(encoded, str) or len(encoded) > 90000:
                    raise ValueError
                seen.add(identity)
                encrypted = base64.b64decode(encoded, validate=True)
                raw = win32crypt.CryptUnprotectData(encrypted, None, None, None, 1)[1]
                note = json.loads(raw.decode("utf-8"))
                if (not isinstance(note, dict) or set(note) != {"title", "text"} or
                        not isinstance(note["title"], str) or not isinstance(note["text"], str) or
                        not note["title"].strip() or not note["text"].strip() or
                        len(note["title"]) > 200 or len(note["text"]) > 16000):
                    raise ValueError
                result.append((identity, encrypted))
            return result
        except Exception as exc:
            raise ValueError("Резервная копия повреждена или создана другой учётной записью Windows") from exc

    def preview_restore(self, source: Path) -> tuple[int, int]:
        """Return (new notes, conflicts); never writes to the database."""
        rows = self._read_backup(source)
        with self._connect() as db:
            existing = {row[0] for row in db.execute("SELECT id FROM notes")}
        conflicts = sum(identity in existing for identity, _ in rows)
        return len(rows) - conflicts, conflicts

    def restore_backup(self, source: Path) -> tuple[int, int]:
        """Merge verified notes transactionally; existing IDs are never replaced."""
        rows = self._read_backup(source)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = {row[0] for row in db.execute("SELECT id FROM notes")}
            additions = [(identity, payload) for identity, payload in rows if identity not in existing]
            if len(existing) + len(additions) > self.MAX_NOTES:
                raise ValueError("После восстановления будет превышен лимит 1000 записей")
            db.executemany("INSERT INTO notes(id,payload) VALUES (?,?)", additions)
        return len(additions), len(rows) - len(additions)

    def create_portable_backup(self, destination: Path, passphrase: str) -> int:
        """Create a cross-Windows-account encrypted backup without plaintext on disk."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Файл переносимой копии уже существует")
        notes = self.search()
        payload = encrypt_memory([{"id": note.id, "title": note.title, "text": note.text} for note in notes], passphrase)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, prefix=".astra-portable-memory-", delete=False) as temp:
                temp_path = Path(temp.name)
                temp.write(payload)
                temp.flush()
                os.fsync(temp.fileno())
            os.link(temp_path, destination)
            return len(notes)
        except FileExistsError:
            raise FileExistsError("Файл переносимой копии уже существует") from None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _read_portable_backup(source: Path, passphrase: str) -> list[dict[str, str]]:
        source = Path(source)
        if source.is_symlink() or not source.is_file() or source.stat().st_size > PORTABLE_MAX_BACKUP_BYTES:
            raise ValueError("Некорректный или слишком большой файл переносимой копии")
        return decrypt_memory(source.read_bytes(), passphrase)

    def preview_portable_restore(self, source: Path, passphrase: str) -> tuple[int, int]:
        """Decrypt and count additions/conflicts without changing the local database."""
        notes = self._read_portable_backup(source, passphrase)
        with self._connect() as db:
            existing = {row[0] for row in db.execute("SELECT id FROM notes")}
        conflicts = sum(note["id"] in existing for note in notes)
        return len(notes) - conflicts, conflicts

    def restore_portable_backup(self, source: Path, passphrase: str) -> tuple[int, int]:
        """Re-encrypt imported notes for this Windows account and merge by stable ID."""
        notes = self._read_portable_backup(source, passphrase)
        encrypted = []
        for note in notes:
            plaintext = json.dumps({"title": note["title"], "text": note["text"]}, ensure_ascii=False).encode("utf-8")
            payload = win32crypt.CryptProtectData(plaintext, "Astra personal note", None, None, None, 1)
            encrypted.append((note["id"], payload))
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = {row[0] for row in db.execute("SELECT id FROM notes")}
            additions = [(identity, payload) for identity, payload in encrypted if identity not in existing]
            if len(existing) + len(additions) > self.MAX_NOTES:
                raise ValueError("После восстановления будет превышен лимит 1000 записей")
            db.executemany("INSERT INTO notes(id,payload) VALUES (?,?)", additions)
        return len(additions), len(notes) - len(additions)
