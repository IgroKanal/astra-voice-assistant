"""One explicit, short-lived voice confirmation for a file transaction."""
from __future__ import annotations

import threading
import time
import unicodedata
from dataclasses import dataclass

from src.file_workspace import WorkspaceDenied


@dataclass(frozen=True)
class VoiceFileResult:
    message: str
    operation_id: str = ""


class VoiceFileConfirmation:
    """Adapter for a single already-granted FileTransactions workspace.

    The caller must resolve an exact relative path before preparing an action.
    This object never grants permissions and is not a speech recognizer.
    """

    TTL_SECONDS = 30.0

    def __init__(self, transactions, clock=time.monotonic):
        self._transactions = transactions
        self._clock = clock
        self._pending = None
        self._lock = threading.RLock()

    def cancel(self):
        with self._lock:
            pending, self._pending = self._pending, None
            if pending is not None:
                self._transactions.discard_preview(pending[0].token)

    def prepare(self, operation: str, *, source: str, destination: str = "") -> str:
        with self._lock:
            self.cancel()
            if operation not in {"trash", "move", "copy"}:
                raise WorkspaceDenied("Эта голосовая файловая операция не поддерживается")
            for path in (source, destination):
                if (not isinstance(path, str) or len(path) > 400 or any(
                    unicodedata.category(char).startswith("C") or char in "«»" for char in path
                )):
                    raise WorkspaceDenied("Некорректное имя файла для голосового подтверждения")
            preview = self._transactions.preview(operation, source=source, destination=destination)
            self._pending = (preview, self._clock())
            if operation == "trash":
                return f"Переместить файл «{preview.source}» в Корзину Windows? Скажи: подтверждаю или отмени."
            verb = "Переместить" if operation == "move" else "Скопировать"
            return f"{verb} файл «{preview.source}» в «{preview.destination}»? Скажи: подтверждаю или отмени."

    def confirm(self, phrase: str) -> VoiceFileResult:
        with self._lock:
            if not isinstance(phrase, str) or phrase.strip().casefold() != "подтверждаю":
                self.cancel()
                raise WorkspaceDenied("Файловое действие не подтверждено")
            pending, self._pending = self._pending, None
            if pending is None:
                raise WorkspaceDenied("Нет ожидающего файлового действия")
            preview, created = pending
            if not 0 <= self._clock() - created <= self.TTL_SECONDS:
                self._transactions.discard_preview(preview.token)
                raise WorkspaceDenied("Время подтверждения истекло")
            if preview.operation == "trash":
                return VoiceFileResult(self._transactions.execute_trash(preview.token))
            operation_id = self._transactions.execute(preview.token)
            verb = "перемещён" if preview.operation == "move" else "скопирован"
            return VoiceFileResult(f"Файл {verb}: {preview.destination}.", operation_id)
