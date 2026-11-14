"""Durable local reminders with encrypted payloads and leased delivery."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import threading
import time

import win32crypt
from src.portable_reminder_backup import MAX_BACKUP_BYTES as PORTABLE_MAX_BACKUP_BYTES, decrypt_reminders, encrypt_reminders


@dataclass(frozen=True)
class Reminder:
    id: str
    text: str
    due: float
    state: str
    token: str = ""


class ReminderStore:
    MAX_PORTABLE_REMINDERS = 1000
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Неподдерживаемая версия базы напоминаний")
            db.execute("CREATE TABLE IF NOT EXISTS reminders (id TEXT PRIMARY KEY, due REAL NOT NULL, state TEXT NOT NULL, lease REAL NOT NULL DEFAULT 0, token TEXT NOT NULL DEFAULT '', payload BLOB NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS reminder_due ON reminders(state,due)")
            if version == 0:
                db.execute("PRAGMA user_version=1")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=3)
        try:
            db.execute("PRAGMA secure_delete=ON")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def decode(payload):
        raw = win32crypt.CryptUnprotectData(payload, None, None, None, 1)[1]
        return raw.decode("utf-8")

    def add(self, text: str, due: float) -> str:
        text = text.strip()
        if not text or len(text) > 4000 or not isinstance(due, (int, float)) or not math.isfinite(due) or due <= 0:
            raise ValueError("Нужны текст до 4000 символов и корректное время")
        payload = win32crypt.CryptProtectData(text.encode("utf-8"), "Astra reminder", None, None, None, 1)
        identity = secrets.token_hex(16)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT count(*) FROM reminders WHERE state IN ('pending','delivering')").fetchone()[0] >= 500:
                raise ValueError("Достигнут лимит 500 активных напоминаний")
            db.execute("INSERT INTO reminders(id,due,state,payload) VALUES (?,?,'pending',?)", (identity, due, payload))
        return identity

    def list(self) -> list[Reminder]:
        with self.connect() as db:
            rows = db.execute("SELECT id,due,state,payload FROM reminders ORDER BY due DESC LIMIT 1000").fetchall()
        return [Reminder(identity, self.decode(payload), due, state) for identity, due, state, payload in rows]

    def list_upcoming(self, limit: int = 4) -> list[Reminder]:
        """Return a small, ordered snapshot of active reminders for voice replies."""
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("Лимит списка напоминаний должен быть от 1 до 10")
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,due,state,payload FROM reminders "
                "WHERE state IN ('pending','delivering') ORDER BY due ASC,id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Reminder(identity, self.decode(payload), due, state) for identity, due, state, payload in rows]

    def claim_due(self, now: float | None = None, lease_seconds: float = 30) -> list[Reminder]:
        now = time.time() if now is None else now
        if not math.isfinite(now) or not 1 <= lease_seconds <= 300:
            raise ValueError("Некорректный срок доставки")
        claimed = []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id,due,payload FROM reminders WHERE due<=? AND (state='pending' OR (state='delivering' AND lease<=?)) ORDER BY due LIMIT 3", (now, now)).fetchall()
            for identity, due, payload in rows:
                text = self.decode(payload)
                token = secrets.token_hex(24)
                db.execute("UPDATE reminders SET state='delivering',lease=?,token=? WHERE id=?", (now + lease_seconds, token, identity))
                claimed.append(Reminder(identity, text, due, "delivering", token))
        return claimed

    def valid_claim(self, identity: str, token: str) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM reminders WHERE id=? AND token=? AND state='delivering'", (identity, token)).fetchone() is not None

    def acknowledge(self, identity: str, token: str) -> bool:
        with self.connect() as db:
            return db.execute("UPDATE reminders SET state='delivered',lease=0,token='' WHERE id=? AND token=? AND state='delivering'", (identity, token)).rowcount == 1

    def cancel(self, identity: str) -> bool:
        with self.connect() as db:
            return db.execute("UPDATE reminders SET state='cancelled',lease=0,token='' WHERE id=? AND state IN ('pending','delivering')", (identity,)).rowcount == 1

    def cancel_next(self) -> bool:
        """Cancel one earliest pending or delivering reminder atomically."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id FROM reminders WHERE state IN ('pending','delivering') ORDER BY due ASC,id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return False
            return db.execute(
                "UPDATE reminders SET state='cancelled',lease=0,token='' WHERE id=? AND state IN ('pending','delivering')",
                (row[0],),
            ).rowcount == 1

    def cancel_matching(self, query: str) -> tuple[str, str]:
        """Cancel one active reminder only when its encrypted title has a unique exact fragment match."""
        normalized_query = re.sub(r"\W+", " ", query.casefold().replace("ё", "е"), flags=re.UNICODE).strip()
        if not 2 <= len(normalized_query) <= 160:
            raise ValueError("Фрагмент названия должен содержать от 2 до 160 символов")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT id,payload FROM reminders WHERE state IN ('pending','delivering') ORDER BY due ASC,id ASC"
            ).fetchall()
            matches = []
            for identity, payload in rows:
                title = self.decode(payload)
                normalized_title = re.sub(
                    r"\W+", " ", title.casefold().replace("ё", "е"), flags=re.UNICODE
                ).strip()
                if normalized_query in normalized_title:
                    matches.append((identity, title))
                    if len(matches) > 1:
                        return "ambiguous", ""
            if not matches:
                return "not_found", ""
            identity, title = matches[0]
            changed = db.execute(
                "UPDATE reminders SET state='cancelled',lease=0,token='' WHERE id=? AND state IN ('pending','delivering')",
                (identity,),
            ).rowcount
            return ("cancelled", title) if changed == 1 else ("not_found", "")

    def unread_count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM reminders WHERE state='delivered'").fetchone()[0]

    def complete(self, identity: str) -> bool:
        with self.connect() as db:
            return db.execute("UPDATE reminders SET state='completed' WHERE id=? AND state='delivered'", (identity,)).rowcount == 1

    def create_portable_backup(self, destination: Path, passphrase: str) -> int:
        """Export pending and unread reminders; live delivery leases are not portable."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Файл переносимой копии уже существует")
        with self.connect() as db:
            count = db.execute("SELECT count(*) FROM reminders WHERE state IN ('pending','delivering','delivered')").fetchone()[0]
            if count > self.MAX_PORTABLE_REMINDERS:
                raise ValueError("Активных и непрочитанных напоминаний больше лимита переноса (1000)")
            rows = db.execute("SELECT id,due,state,payload FROM reminders WHERE state IN ('pending','delivering','delivered') ORDER BY due DESC LIMIT ?", (self.MAX_PORTABLE_REMINDERS,)).fetchall()
        portable = []
        for identity, due, state, payload in rows:
            portable.append({"id": identity, "due": due, "state": "delivered" if state == "delivered" else "pending", "text": self.decode(payload)})
        encoded = encrypt_reminders(portable, passphrase)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, prefix=".astra-portable-reminders-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, destination)
            return len(portable)
        except FileExistsError:
            raise FileExistsError("Файл переносимой копии уже существует") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass

    @staticmethod
    def _read_portable_backup(source: Path, passphrase: str) -> list[dict]:
        source = Path(source)
        if source.is_symlink() or not source.is_file() or source.stat().st_size > PORTABLE_MAX_BACKUP_BYTES:
            raise ValueError("Некорректный или слишком большой файл переносимых напоминаний")
        return decrypt_reminders(source.read_bytes(), passphrase)

    def preview_portable_restore(self, source: Path, passphrase: str) -> tuple[int, int]:
        records = self._read_portable_backup(source, passphrase)
        with self.connect() as db:
            existing = {row[0] for row in db.execute("SELECT id FROM reminders")}
        conflicts = sum(record["id"] in existing for record in records)
        return len(records) - conflicts, conflicts

    def restore_portable_backup(self, source: Path, passphrase: str) -> tuple[int, int]:
        records = self._read_portable_backup(source, passphrase)
        encrypted = []
        for record in records:
            payload = win32crypt.CryptProtectData(record["text"].encode("utf-8"), "Astra reminder", None, None, None, 1)
            encrypted.append((record["id"], record["due"], record["state"], payload))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = {row[0] for row in db.execute("SELECT id FROM reminders")}
            additions = [row for row in encrypted if row[0] not in existing]
            active = db.execute("SELECT count(*) FROM reminders WHERE state IN ('pending','delivering')").fetchone()[0]
            incoming_active = sum(state == "pending" for _, _, state, _ in additions)
            if active + incoming_active > 500:
                raise ValueError("После восстановления будет превышен лимит 500 ожидающих напоминаний")
            db.executemany("INSERT INTO reminders(id,due,state,lease,token,payload) VALUES (?,?,?,0,'',?)", additions)
        return len(additions), len(records) - len(additions)


class ReminderWorker:
    def __init__(self, store: ReminderStore, emit, interval=1):
        self.store, self.emit, self.interval = store, emit, interval
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.run, name="astra-reminders", daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        last_count = None
        error_reported = False
        while not self.stopping.is_set():
            try:
                for item in self.store.claim_due():
                    self.emit("reminder", json.dumps({"id": item.id, "token": item.token, "text": item.text}, ensure_ascii=False))
                count = self.store.unread_count()
                if count != last_count:
                    self.emit("reminder_count", str(count))
                    last_count = count
                error_reported = False
            except Exception:
                if not error_reported:
                    self.emit("reminder_error", "Не удалось проверить локальные напоминания. Проверь базу и учётную запись Windows.")
                    error_reported = True
            self.stopping.wait(self.interval)

    def stop(self):
        self.stopping.set()
        self.thread.join(timeout=4)
