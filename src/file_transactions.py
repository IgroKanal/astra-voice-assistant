"""Session write grants, exact previews and recoverable bounded file edits."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time
import functools
import logging
import uuid
from send2trash import send2trash

from src.file_workspace import FileWorkspace, WorkspaceDenied


def audited_file_call(method):
    @functools.wraps(method)
    def call(self, identity, *args, **kwargs):
        action = {"execute_trash": "trash", "undo": "undo", "recover": "recover"}.get(method.__name__, "execute")
        if method.__name__ == "execute":
            with self._lock:
                pending = self._pending.get(identity)
                if pending:
                    action = pending[0].operation
                    if action == "mkdir":
                        action = "create_folder"
        correlation = uuid.uuid4().hex
        try:
            result = method(self, identity, *args, **kwargs)
        except Exception:
            self._record_audit("files." + action, "failed", correlation)
            raise
        self._record_audit("files." + action, "succeeded", correlation)
        return result
    return call


@dataclass(frozen=True)
class FilePreview:
    token: str
    operation: str
    source: str
    destination: str
    size: int
    source_hash: str
    destination_hash: str
    text: str


class FileTransactions:
    MAX_BYTES = 16_000_000
    HISTORY = ".astra-history"

    def __init__(self, workspace: FileWorkspace, audit=None):
        self.workspace = workspace
        self.audit = audit
        self.writable = False
        self.trash_enabled = False
        self._pending: dict[str, tuple[FilePreview, float]] = {}
        self._lock = threading.RLock()

    def _record_audit(self, action, outcome, correlation):
        if self.audit is not None:
            try:
                self.audit(action, outcome, correlation)
            except Exception:
                logging.getLogger(__name__).warning("File action audit unavailable")

    def grant_write(self, enabled: bool) -> None:
        with self._lock:
            if not isinstance(enabled, bool):
                raise WorkspaceDenied("Разрешение должно быть явным")
            self.writable = bool(enabled)
            self._pending.clear()

    def grant_trash(self, enabled: bool) -> None:
        with self._lock:
            if not isinstance(enabled, bool):
                raise WorkspaceDenied("Разрешение должно быть явным")
            self.trash_enabled = enabled
            self._pending.clear()

    def discard_preview(self, token: str) -> None:
        """Discard an unused preview token without changing the active grant."""
        with self._lock:
            self._pending.pop(token, None)

    def _destination(self, relative: str) -> Path:
        rel = Path(relative)
        if not relative or rel.is_absolute() or rel.drive or ".." in rel.parts or any(c in relative for c in ':<>"|?*'):
            raise WorkspaceDenied("Недопустимый относительный путь")
        for part in rel.parts:
            if part.endswith((".", " ")) or part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
                raise WorkspaceDenied("Зарезервированное имя Windows")
        parent = self.workspace.checked(str(rel.parent))
        target = parent / rel.name
        if target.exists() or target.is_symlink():
            return self.workspace.checked(relative)
        # Validate the filename blocklist using the same policy as existing files.
        name = target.name.lower()
        if name in FileWorkspace.BLOCKED or name.startswith(".astra-") or name == ".env" or name.startswith(".env.") or target.suffix.lower() in FileWorkspace.SECRET_SUFFIXES or name in {"credentials", "id_rsa", "id_ed25519"}:
            raise WorkspaceDenied("Файл с секретами исключён")
        return target

    def _bytes(self, relative: str) -> bytes:
        path = self.workspace.checked(relative)
        if not path.is_file() or path.stat().st_size > self.MAX_BYTES:
            raise WorkspaceDenied("Нужен обычный файл до 16 МБ")
        with path.open("rb") as stream:
            identity = os.fstat(stream.fileno())
            data = stream.read(self.MAX_BYTES + 1)
            current = self.workspace.checked(relative).stat()
        if len(data) > self.MAX_BYTES or (identity.st_dev, identity.st_ino) != (current.st_dev, current.st_ino):
            raise WorkspaceDenied("Файл изменился при чтении")
        return data

    @staticmethod
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def preview(self, operation: str, source: str = "", destination: str = "", text: str = "") -> FilePreview:
        with self._lock:
            if operation == "trash":
                if not self.trash_enabled:
                    raise WorkspaceDenied("Сначала отдельно разреши перемещение файлов в Корзину Windows")
                if not source or destination or text:
                    raise WorkspaceDenied("Для Корзины укажи только один исходный файл")
                target = self.workspace.checked(source)
                if not target.is_file():
                    raise WorkspaceDenied("В Корзину можно отправить только обычный файл")
                info = target.stat()
                identity = f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}".encode("ascii")
                if len(self._pending) >= 32:
                    self._pending.clear()
                preview = FilePreview(secrets.token_hex(24), operation, source, source, info.st_size,
                                      self.digest(identity), "", "")
                self._pending[preview.token] = (preview, time.monotonic())
                return preview
            if not self.writable:
                raise WorkspaceDenied("Сначала явно разреши запись в эту папку")
            if operation not in {"create", "replace", "copy", "move", "mkdir"}:
                raise WorkspaceDenied("Неизвестная файловая операция")
            if (operation in {"create", "replace", "mkdir"} and source) or (operation in {"copy", "move", "mkdir"} and text):
                raise WorkspaceDenied("Лишние аргументы операции")
            target = self._destination(destination)
            if operation == "mkdir":
                if target.exists():
                    raise WorkspaceDenied("Папка назначения уже существует")
                if len(self._pending) >= 32:
                    self._pending.clear()
                result = FilePreview(secrets.token_hex(24), operation, "", destination, 0, "", "", "")
                self._pending[result.token] = (result, time.monotonic())
                return result
            source_data = self._bytes(source) if operation in {"copy", "move"} else b""
            data = source_data if operation in {"copy", "move"} else text.encode("utf-8")
            if len(data) > self.MAX_BYTES:
                raise WorkspaceDenied("Операция ограничена 16 МБ")
            if operation == "replace":
                destination_data = self._bytes(destination)
                destination_hash = self.digest(destination_data)
            else:
                if target.exists():
                    raise WorkspaceDenied("Файл назначения уже существует")
                destination_hash = ""
            if len(self._pending) >= 32:
                self._pending.clear()
            result = FilePreview(secrets.token_hex(24), operation, source, destination, len(data), self.digest(source_data) if source else "", destination_hash, text)
            self._pending[result.token] = (result, time.monotonic())
            return result

    @audited_file_call
    def execute_trash(self, token: str) -> str:
        """Move one reviewed file to the native Windows Recycle Bin."""
        with self._lock:
            if not self.trash_enabled:
                raise WorkspaceDenied("Разрешение Корзины Windows отозвано")
            pending = self._pending.pop(token, None)
            if pending is None or time.monotonic() - pending[1] > 120:
                raise WorkspaceDenied("Предварительный просмотр устарел или уже использован")
            preview = pending[0]
            if preview.operation != "trash":
                raise WorkspaceDenied("Неверный тип предварительного просмотра")
            target = self.workspace.checked(preview.source)
            if not target.is_file():
                raise WorkspaceDenied("Файл изменился после предварительного просмотра")
            info = target.stat()
            identity = f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}".encode("ascii")
            if self.digest(identity) != preview.source_hash:
                raise WorkspaceDenied("Файл изменился после предварительного просмотра")
            send2trash(str(target))
            if target.exists() or target.is_symlink():
                raise WorkspaceDenied("Windows не подтвердил перемещение файла в Корзину")
            return f"Файл перемещён в Корзину Windows: {preview.source}"

    def _history(self, create: bool = True) -> Path:
        root = self.workspace.checked(".")
        history = root / self.HISTORY
        if not history.exists() and not create:
            return history
        history.mkdir(exist_ok=True)
        info = history.lstat()
        if history.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise WorkspaceDenied("Каталог восстановления подменён ссылкой")
        return history

    @audited_file_call
    def execute(self, token: str) -> str:
        with self._lock:
            if not self.writable:
                raise WorkspaceDenied("Разрешение записи отозвано")
            pending = self._pending.pop(token, None)
            if pending is None or time.monotonic() - pending[1] > 120:
                raise WorkspaceDenied("Просмотр устарел или уже использован")
            preview = pending[0]
            target = self._destination(preview.destination)
            source_data = self._bytes(preview.source) if preview.source else b""
            if preview.source and self.digest(source_data) != preview.source_hash:
                raise WorkspaceDenied("Исходный файл изменился после просмотра")
            old = self._bytes(preview.destination) if preview.operation == "replace" else b""
            if preview.operation == "replace" and self.digest(old) != preview.destination_hash:
                raise WorkspaceDenied("Файл назначения изменился после просмотра")
            if preview.operation != "replace" and target.exists():
                raise WorkspaceDenied("Назначение появилось после просмотра")
            data = source_data if preview.source else preview.text.encode("utf-8")
            history = self._history()
            operation_id = secrets.token_hex(16)
            record = {"id": operation_id, "operation": preview.operation, "source": preview.source, "destination": preview.destination, "before_hash": self.digest(old), "after_hash": self.digest(data), "status": "prepared"}
            if preview.operation == "replace":
                with (history / (operation_id + ".backup")).open("xb") as stream:
                    stream.write(old)
                    stream.flush()
                    os.fsync(stream.fileno())
            journal = history / (operation_id + ".json")
            self._save_record(journal, record)
            if preview.operation == "mkdir":
                target.mkdir()
                record["created_identity"] = self._directory_identity(target)
                self._save_record(journal, record)
            elif preview.operation == "move":
                # Windows rename refuses an existing destination, preserving it.
                self._assert_hash(preview.source, preview.source_hash)
                self.workspace.checked(preview.source).rename(target)
            elif preview.operation == "replace":
                temporary = target.with_name(".astra-" + operation_id + ".tmp")
                with temporary.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._destination(preview.destination)
                self._assert_hash(preview.destination, preview.destination_hash)
                os.replace(temporary, target)
            else:
                temporary = target.with_name(".astra-" + operation_id + ".tmp")
                with temporary.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._destination(preview.destination)
                # Unlike replace, link refuses to overwrite a concurrently created file.
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    record["status"] = "cancelled"
                    self._save_record(journal, record)
                    raise WorkspaceDenied("Файл назначения появился во время операции; существующие данные сохранены") from None
                finally:
                    if temporary.exists():
                        temporary.unlink()
            record["status"] = "done"
            self._save_record(journal, record)
            return operation_id

    def _assert_hash(self, relative: str, expected: str) -> None:
        if self.digest(self._bytes(relative)) != expected:
            raise WorkspaceDenied("Файл изменён во время операции; перезапись остановлена")

    @staticmethod
    def _directory_identity(path: Path) -> str:
        info = path.lstat()
        if not path.is_dir() or path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise WorkspaceDenied("Папка подменена ссылкой или имеет неверный тип")
        return f"{info.st_dev}:{info.st_ino}"

    @staticmethod
    def _save_record(path: Path, record: dict) -> None:
        temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def history(self) -> list[dict]:
        with self._lock:
            history = self._history(create=False)
            paths = list(history.glob("*.json"))
            for path in paths:
                self._check_record(path)
            return [self._read_record(path) for path in sorted(paths, key=lambda item: item.stat().st_mtime_ns)[-200:]]

    @staticmethod
    def _check_record(path: Path) -> None:
        info = path.lstat()
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400 or info.st_size > 65536:
            raise WorkspaceDenied("Недопустимая запись журнала восстановления")

    @classmethod
    def _read_record(cls, path: Path) -> dict:
        cls._check_record(path)
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            data = stream.read(65537)
            cls._check_record(path)
            current = path.lstat()
        if len(data) > 65536 or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise WorkspaceDenied("Журнал изменился при чтении")
        result = json.loads(data.decode("utf-8"))
        if not isinstance(result, dict):
            raise WorkspaceDenied("Повреждённая запись журнала")
        return result

    @audited_file_call
    def undo(self, operation_id: str) -> None:
        with self._lock:
            if not self.writable:
                raise WorkspaceDenied("Разрешение записи отозвано")
            if len(operation_id) != 32 or any(c not in "0123456789abcdef" for c in operation_id):
                raise WorkspaceDenied("Неверный идентификатор операции")
            history = self._history()
            journal = history / (operation_id + ".json")
            record = self._read_record(journal)
            if record.get("status") != "done" or record.get("operation") not in {"create", "replace", "copy", "move", "mkdir"}:
                raise WorkspaceDenied("Операция недоступна для восстановления")
            if record["operation"] == "mkdir":
                target = self.workspace.checked(record["destination"])
                if self._directory_identity(target) != record.get("created_identity") or any(target.iterdir()):
                    raise WorkspaceDenied("Папка изменена или уже содержит данные; автоматическое восстановление остановлено")
                record["status"] = "undo_prepared"
                self._save_record(journal, record)
                if self._directory_identity(target) != record.get("created_identity") or any(target.iterdir()):
                    raise WorkspaceDenied("Папка изменилась перед восстановлением; данные сохранены")
                preserved = history / (operation_id + ".undone-dir")
                if preserved.exists():
                    raise WorkspaceDenied("Папка восстановления уже существует")
                target.rename(preserved)
                record["status"] = "undone"
                self._save_record(journal, record)
                return
            target = self.workspace.checked(record["destination"])
            current = self._bytes(record["destination"])
            if self.digest(current) != record["after_hash"]:
                raise WorkspaceDenied("Файл изменён после операции; автоматический откат остановлен")
            if record["operation"] == "move":
                source = self._destination(record["source"])
                if source.exists():
                    raise WorkspaceDenied("Старое имя уже занято")
                record["status"] = "undo_prepared"
                self._save_record(journal, record)
                self._assert_hash(record["destination"], record["after_hash"])
                target.rename(source)
            elif record["operation"] == "replace":
                backup = history / (operation_id + ".backup")
                if backup.is_symlink() or getattr(backup.lstat(), "st_file_attributes", 0) & 0x400:
                    raise WorkspaceDenied("Резервная копия подменена")
                if backup.stat().st_size > self.MAX_BYTES:
                    raise WorkspaceDenied("Резервная копия повреждена")
                data = backup.read_bytes()
                if self.digest(data) != record["before_hash"]:
                    raise WorkspaceDenied("Контрольная сумма резервной копии не совпала")
                temporary = target.with_name(".astra-undo-" + operation_id + ".tmp")
                with temporary.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                self.workspace.checked(record["destination"])
                record["status"] = "undo_prepared"
                self._save_record(journal, record)
                self._assert_hash(record["destination"], record["after_hash"])
                os.replace(temporary, target)
            else:
                # Keep the created/copied file recoverable instead of deleting it.
                record["status"] = "undo_prepared"
                self._save_record(journal, record)
                self._assert_hash(record["destination"], record["after_hash"])
                target.rename(history / (operation_id + ".undone-file"))
            record["status"] = "undone"
            self._save_record(journal, record)

    @audited_file_call
    def recover(self, operation_id: str) -> str:
        """Reconcile a durable pending journal with current files; never edit data."""
        with self._lock:
            if not self.writable:
                raise WorkspaceDenied("Разреши запись для обновления журнала")
            if len(operation_id) != 32 or any(c not in "0123456789abcdef" for c in operation_id):
                raise WorkspaceDenied("Неверный идентификатор")
            history = self._history()
            journal = history / (operation_id + ".json")
            record = self._read_record(journal)
            operation = record.get("operation")
            phase = record.get("status")
            if operation not in {"create", "copy", "replace", "move", "mkdir"} or phase not in {"prepared", "undo_prepared"}:
                raise WorkspaceDenied("Нет незавершённого действия для проверки")
            if operation == "mkdir":
                target_path = self._destination(record["destination"])
                preserved = history / (operation_id + ".undone-dir")
                outcome = None
                if phase == "prepared":
                    if not target_path.exists():
                        outcome = "cancelled"
                    elif record.get("created_identity") and self._directory_identity(target_path) == record["created_identity"] and not any(target_path.iterdir()):
                        outcome = "done"
                else:
                    if target_path.exists() and self._directory_identity(target_path) == record.get("created_identity") and not any(target_path.iterdir()):
                        outcome = "done"
                    elif preserved.exists() and self._directory_identity(preserved) == record.get("created_identity") and not any(preserved.iterdir()):
                        outcome = "undone"
                if outcome is None:
                    raise WorkspaceDenied("Папка не совпала с журналом; автоматическое восстановление остановлено")
                record["status"] = outcome
                self._save_record(journal, record)
                return outcome
            target = self._destination(record["destination"])
            destination_hash = self.digest(self._bytes(record["destination"])) if target.exists() else None
            source_hash = None
            if operation == "move":
                source = self._destination(record["source"])
                source_hash = self.digest(self._bytes(record["source"])) if source.exists() else None
            outcome = None
            if phase == "prepared":
                if operation == "move":
                    if destination_hash == record["after_hash"] and source_hash is None:
                        outcome = "done"
                    elif destination_hash is None and source_hash == record["after_hash"]:
                        outcome = "cancelled"
                elif operation == "replace":
                    if destination_hash == record["after_hash"]:
                        outcome = "done"
                    elif destination_hash == record["before_hash"]:
                        outcome = "cancelled"
                elif destination_hash == record["after_hash"]:
                    outcome = "done"
                elif destination_hash is None:
                    outcome = "cancelled"
            elif operation == "move":
                if destination_hash is None and source_hash == record["after_hash"]:
                    outcome = "undone"
                elif destination_hash == record["after_hash"] and source_hash is None:
                    outcome = "done"
            elif operation == "replace":
                if destination_hash == record["before_hash"]:
                    outcome = "undone"
                elif destination_hash == record["after_hash"]:
                    outcome = "done"
            elif destination_hash is None:
                preserved = history / (operation_id + ".undone-file")
                if preserved.is_file() and not preserved.is_symlink() and not (getattr(preserved.lstat(), "st_file_attributes", 0) & 0x400) and preserved.stat().st_size <= self.MAX_BYTES:
                    if self.digest(preserved.read_bytes()) == record["after_hash"]:
                        outcome = "undone"
            elif destination_hash == record["after_hash"]:
                outcome = "done"
            if outcome is None:
                raise WorkspaceDenied("Файлы не совпали с журналом. Автоматическое восстановление остановлено; данные не изменены.")
            record["status"] = outcome
            self._save_record(journal, record)
            return outcome
