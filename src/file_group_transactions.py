"""Scoped, recoverable file transactions across separately selected roots."""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

from src.file_transactions import FilePreview, FileTransactions
from src.file_workspace import FileWorkspaceGroup, WorkspaceDenied


@dataclass(frozen=True)
class _PendingGroupPreview:
    destination_alias: str
    inner_token: str
    preview: FilePreview
    created_at: float
    source_alias: str | None = None
    source_path: str = ""
    payload_size: int = 0


class FileWorkspaceGroupTransactions:
    """Route reviewed writes to one explicitly granted root at a time.

    Each destination needs its own ``write`` grant and session switch. A
    cross-root copy reads from a separate ``read`` grant and creates an
    independently recoverable destination file; cross-root moves are denied.
    """

    MAX_PENDING = 32
    MAX_PENDING_COPY_BYTES = 32_000_000
    PREVIEW_TTL_SECONDS = 120

    def __init__(self, workspace: FileWorkspaceGroup, audit=None):
        if not isinstance(workspace, FileWorkspaceGroup):
            raise WorkspaceDenied("Нужна группа явно выбранных папок")
        self.workspace = workspace
        self.audit = audit
        self._transactions = {
            alias: FileTransactions(workspace._roots[alias].workspace, audit=audit)
            for alias in workspace.root_aliases
        }
        self._pending: dict[str, _PendingGroupPreview] = {}
        self._lock = threading.RLock()

    @property
    def writable(self) -> bool:
        for alias, transactions in self._transactions.items():
            try:
                self.workspace._roots[alias].require("write")
            except WorkspaceDenied:
                continue
            if transactions.writable:
                return True
        return False

    def grant_write(self, alias: str, enabled: bool) -> None:
        if not isinstance(alias, str) or not isinstance(enabled, bool):
            raise WorkspaceDenied("Разрешение должно быть явным")
        with self._lock:
            transactions = self._transactions.get(alias)
            grant = self.workspace._roots.get(alias)
            if transactions is None or grant is None:
                raise WorkspaceDenied("Неизвестное разрешение папки")
            if enabled:
                grant.require("write")
            transactions.grant_write(enabled)
            self._discard_root_previews(alias)

    def grant_trash(self, alias: str, enabled: bool) -> None:
        if not isinstance(alias, str) or not isinstance(enabled, bool):
            raise WorkspaceDenied("Разрешение должно быть явным")
        with self._lock:
            transactions = self._transactions.get(alias)
            grant = self.workspace._roots.get(alias)
            if transactions is None or grant is None:
                raise WorkspaceDenied("Неизвестное разрешение папки")
            if enabled:
                grant.require("trash")
            transactions.grant_trash(enabled)
            self._discard_root_previews(alias)

    def _discard_root_previews(self, alias: str) -> None:
        for token, pending in tuple(self._pending.items()):
            if alias in {pending.destination_alias, pending.source_alias}:
                self._pending.pop(token, None)
                self._transactions[pending.destination_alias].discard_preview(pending.inner_token)

    def discard_preview(self, token: str) -> None:
        with self._lock:
            pending = self._pending.pop(token, None)
            if pending is not None:
                self._transactions[pending.destination_alias].discard_preview(pending.inner_token)

    def _route(self, path: str, operation: str) -> tuple[str, str]:
        alias, _grant, inner = self.workspace._route_for_operation(path, operation)
        return alias, inner

    @staticmethod
    def _virtual(alias: str, inner: str) -> str:
        return alias + "/" + inner.replace("\\", "/")

    def _clear_pending(self) -> None:
        for token in tuple(self._pending):
            self.discard_preview(token)

    def preview(self, operation: str, source: str = "", destination: str = "", text: str = "") -> FilePreview:
        with self._lock:
            if not isinstance(operation, str) or any(
                not isinstance(value, str) for value in (source, destination, text)
            ):
                raise WorkspaceDenied("Тип файловой операции или её аргументы неверны")
            if len(self._pending) >= self.MAX_PENDING:
                self._clear_pending()
            if operation == "trash":
                if not source or destination or text:
                    raise WorkspaceDenied("Для Корзины укажи только один исходный файл")
                alias, inner_source = self._route(source, "trash")
                inner_preview = self._transactions[alias].preview("trash", source=inner_source)
                virtual_source = self._virtual(alias, inner_source)
                virtual_destination = virtual_source
                source_alias = None
                source_path = ""
                preview_source_hash = None
            else:
                alias, inner_destination = self._route(destination, "write")
                inner_source = ""
                virtual_source = ""
                source_alias = None
                source_path = ""
                preview_source_hash = None
                cross_root_copy = False
                if operation in {"copy", "move"}:
                    source_operation = "read" if operation == "copy" else "write"
                    source_alias, inner_source = self._route(source, source_operation)
                    if operation == "move" and source_alias != alias:
                        raise WorkspaceDenied(
                            "Перемещение между разными выбранными папками пока не поддерживается"
                        )
                    virtual_source = self._virtual(source_alias, inner_source)
                    if operation == "copy" and source_alias != alias:
                        source_grant = self.workspace._roots[source_alias]
                        source_grant.require("read")
                        source_data = self._transactions[source_alias]._bytes(inner_source)
                        source_grant.require("read")
                        pending_bytes = sum(item.payload_size for item in self._pending.values())
                        if pending_bytes + len(source_data) > self.MAX_PENDING_COPY_BYTES:
                            raise WorkspaceDenied(
                                "Слишком много ожидающих копий между папками; подтверди или отмени preview"
                            )
                        inner_preview = self._transactions[alias]._preview_bytes(
                            inner_destination, source_data
                        )
                        preview_source_hash = self._transactions[source_alias].digest(source_data)
                        source_path = inner_source
                        cross_root_copy = True
                    else:
                        inner_preview = self._transactions[alias].preview(
                            operation,
                            source=inner_source,
                            destination=inner_destination,
                            text=text,
                        )
                else:
                    inner_preview = self._transactions[alias].preview(
                        operation,
                        destination=inner_destination,
                        text=text,
                    )
                if not cross_root_copy:
                    source_alias = None
                virtual_destination = self._virtual(alias, inner_destination)

            token = secrets.token_hex(24)
            preview = FilePreview(
                token=token,
                operation=operation,
                source=virtual_source,
                destination=virtual_destination,
                size=inner_preview.size,
                source_hash=(
                    preview_source_hash
                    if preview_source_hash is not None
                    else inner_preview.source_hash
                ),
                destination_hash=inner_preview.destination_hash,
                text=inner_preview.text,
            )
            self._pending[token] = _PendingGroupPreview(
                destination_alias=alias,
                inner_token=inner_preview.token,
                preview=preview,
                created_at=time.monotonic(),
                source_alias=source_alias,
                source_path=source_path,
                payload_size=len(source_data) if operation == "copy" and cross_root_copy else 0,
            )
            return preview

    def inspect_preview(self, token: str) -> FilePreview:
        with self._lock:
            if not isinstance(token, str):
                raise WorkspaceDenied("Неверный токен предварительного просмотра")
            pending = self._pending.get(token)
            if pending is None or time.monotonic() - pending.created_at > self.PREVIEW_TTL_SECONDS:
                if pending is not None:
                    self.discard_preview(token)
                raise WorkspaceDenied("Предварительный просмотр устарел или уже использован")
            preview = pending.preview
            operation = "trash" if preview.operation == "trash" else "write"
            self.workspace._roots[pending.destination_alias].require(operation)
            self._transactions[pending.destination_alias].inspect_preview(pending.inner_token)
            if pending.source_alias is not None:
                source_grant = self.workspace._roots[pending.source_alias]
                source_grant.require("read")
                source_data = self._transactions[pending.source_alias]._bytes(pending.source_path)
                source_grant.require("read")
                if self._transactions[pending.source_alias].digest(source_data) != preview.source_hash:
                    raise WorkspaceDenied("Исходный файл изменился после предварительного просмотра")
            return preview

    def _take_preview(self, token: str, expected_operation: str | None) -> _PendingGroupPreview:
        preview = self.inspect_preview(token)
        if expected_operation is not None and preview.operation != expected_operation:
            raise WorkspaceDenied("Предварительный просмотр не совпадает с типом операции")
        return self._pending.pop(token)

    def execute(self, token: str) -> str:
        with self._lock:
            if self.inspect_preview(token).operation == "trash":
                raise WorkspaceDenied("Для Корзины используй execute_trash")
            pending = self._take_preview(token, None)
            self.workspace._roots[pending.destination_alias].require("write")
            if pending.source_alias is not None:
                self.workspace._roots[pending.source_alias].require("read")
            operation_id = self._transactions[pending.destination_alias].execute(pending.inner_token)
            return f"{pending.destination_alias}:{operation_id}"

    def execute_trash(self, token: str) -> str:
        with self._lock:
            pending = self._take_preview(token, "trash")
            return self._transactions[pending.destination_alias].execute_trash(pending.inner_token)

    def history(self, alias: str | None = None) -> list[dict]:
        with self._lock:
            if alias is not None and not isinstance(alias, str):
                raise WorkspaceDenied("Неизвестное разрешение папки")
            aliases = (alias,) if alias is not None else self.workspace.root_aliases
            if any(item not in self._transactions for item in aliases):
                raise WorkspaceDenied("Неизвестное разрешение папки")
            records = []
            for root_alias in aliases:
                grant = self.workspace._roots[root_alias]
                try:
                    grant.require("write")
                except WorkspaceDenied:
                    if alias is not None:
                        raise
                    continue
                if not self._transactions[root_alias].writable:
                    continue
                records.extend(
                    {**record, "root_alias": root_alias}
                    for record in self._transactions[root_alias].history()
                )
            return records

    def undo(self, operation: str) -> None:
        alias, operation_id = self._parse_operation_id(operation)
        with self._lock:
            self.workspace._roots[alias].require("write")
            self._transactions[alias].undo(operation_id)

    def recover(self, operation: str) -> str:
        alias, operation_id = self._parse_operation_id(operation)
        with self._lock:
            self.workspace._roots[alias].require("write")
            return self._transactions[alias].recover(operation_id)

    def _parse_operation_id(self, operation: str) -> tuple[str, str]:
        if not isinstance(operation, str) or ":" not in operation:
            raise WorkspaceDenied("Идентификатор должен включать имя выбранной папки")
        alias, operation_id = operation.split(":", 1)
        if alias not in self._transactions or len(operation_id) != 32 or any(
            char not in "0123456789abcdef" for char in operation_id
        ):
            raise WorkspaceDenied("Неверный идентификатор файловой операции")
        return alias, operation_id
