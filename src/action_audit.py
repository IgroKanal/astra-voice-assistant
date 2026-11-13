"""Bounded local action metadata. Arguments and user content are never accepted."""
from contextlib import closing
from pathlib import Path
import logging
import os
import sqlite3
import time
import uuid

from src.task_router import ActionType

ACTIONS = frozenset(item.value for item in ActionType) | frozenset({
    "files.search", "files.read_text", "files.copy", "files.move", "files.rename", "files.create_folder",
    "files.create", "files.replace", "files.trash", "files.undo", "files.recover", "files.execute",
})
OUTCOMES = frozenset({"dispatch_allowed", "blocked", "succeeded", "failed", "cancelled"})


class ActionAudit:
    MAX_ROWS = 5000

    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("Журнал подменён ссылкой")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=3)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Журнал требует более новой версии Astra")
            if version == 0:
                db.execute("CREATE TABLE events (id TEXT PRIMARY KEY, created REAL NOT NULL, action TEXT NOT NULL, outcome TEXT NOT NULL, correlation TEXT NOT NULL)")
                db.execute("PRAGMA user_version=1")

    def record(self, action: str, outcome: str, correlation: str | None = None):
        if action not in ACTIONS or outcome not in OUTCOMES:
            raise ValueError("Неизвестный тип события журнала")
        correlation = correlation or uuid.uuid4().hex
        if len(correlation) != 32 or any(c not in "0123456789abcdef" for c in correlation):
            raise ValueError("Некорректный идентификатор операции")
        with closing(sqlite3.connect(self.path, timeout=3)) as db, db:
            db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (uuid.uuid4().hex, time.time(), action, outcome, correlation))
            db.execute("DELETE FROM events WHERE rowid NOT IN (SELECT rowid FROM events ORDER BY rowid DESC LIMIT ?)", (self.MAX_ROWS,))

    def recent(self, limit=200):
        with closing(sqlite3.connect(self.path, timeout=3)) as db:
            return db.execute("SELECT created,action,outcome,correlation FROM events ORDER BY rowid DESC LIMIT ?", (min(500, max(1, int(limit))),)).fetchall()


def default_audit():
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AstraVoiceAssistant"
    return ActionAudit(root / "actions.sqlite")


def record_action(action, outcome, correlation=None):
    try:
        default_audit().record(action, outcome, correlation)
    except (OSError, ValueError, sqlite3.Error):
        logging.getLogger(__name__).warning("Local action audit unavailable")
