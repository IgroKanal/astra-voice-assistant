"""Bounded request/reply channel for voice search inside the desktop-granted folder."""
from __future__ import annotations

import json
import os
from pathlib import PureWindowsPath
import sys
import threading
import unicodedata
from uuid import uuid4

from src.runtime_events import emit_event

CONTROL_PREFIX = "@ASTRA_CONTROL "
REQUEST_TYPE = "file_search_request"
RESULT_TYPE = "file_search_result"
MAX_QUERY_CHARS = 120
MAX_RESULT_PATH_CHARS = 400
MAX_SPOKEN_RESULTS = 3
MAX_RESULT_COUNT = 500
MAX_CONTROL_LINE = 8192
_RESULT_STATUSES = frozenset({"ok", "no_workspace", "cancelled", "search_failed"})


def validate_query(query: object) -> str:
    if not isinstance(query, str):
        raise ValueError("Некорректный запрос поиска")
    query = " ".join(query.split()).strip()
    if not 2 <= len(query) <= MAX_QUERY_CHARS:
        raise ValueError("Уточни имя файла (от 2 до 120 символов)")
    if any(not char.isprintable() or unicodedata.category(char) in {"Cf", "Cs"} for char in query) or any(char in query for char in "/\\:"):
        raise ValueError("Можно искать только по имени файла, без пути")
    return query


def make_search_request(request_id: str, query: str) -> dict[str, object]:
    if not isinstance(request_id, str) or len(request_id) != 32 or any(char not in "0123456789abcdef" for char in request_id):
        raise ValueError("Некорректный идентификатор поиска")
    return {
        "version": 1,
        "type": REQUEST_TYPE,
        "request_id": request_id,
        "query": validate_query(query),
    }


def parse_search_request(text: str) -> dict[str, object]:
    if not isinstance(text, str) or len(text) > MAX_CONTROL_LINE:
        raise ValueError("Некорректный запрос поиска")
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        raise ValueError("Некорректный запрос поиска") from None
    if not isinstance(payload, dict) or set(payload) != {"version", "type", "request_id", "query"}:
        raise ValueError("Некорректный запрос поиска")
    if payload["version"] != 1 or payload["type"] != REQUEST_TYPE:
        raise ValueError("Неподдерживаемая версия запроса поиска")
    request = make_search_request(payload["request_id"], payload["query"])
    return request


def make_search_result(
    request_id: str,
    status: str,
    count: int = 0,
    files: tuple[str, ...] | list[str] = (),
) -> dict[str, object]:
    if not isinstance(request_id, str) or len(request_id) != 32 or any(char not in "0123456789abcdef" for char in request_id):
        raise ValueError("Некорректный идентификатор поиска")
    if status not in _RESULT_STATUSES or type(count) is not int or not 0 <= count <= MAX_RESULT_COUNT:
        raise ValueError("Некорректный результат поиска")
    if not isinstance(files, (tuple, list)) or len(files) > MAX_SPOKEN_RESULTS:
        raise ValueError("Некорректный результат поиска")
    clean_files: list[str] = []
    for value in files:
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_RESULT_PATH_CHARS:
            raise ValueError("Некорректный путь результата")
        if any(not char.isprintable() or unicodedata.category(char) in {"Cf", "Cs"} for char in value):
            raise ValueError("Некорректный путь результата")
        relative = value.replace("/", "\\")
        path = PureWindowsPath(relative)
        if (
            path.is_absolute()
            or path.drive
            or ":" in relative
            or not path.parts
            or any(part in {"", ".", ".."} for part in relative.split("\\"))
        ):
            raise ValueError("Путь результата должен оставаться относительным")
        clean_files.append(value)
    return {
        "version": 1,
        "type": RESULT_TYPE,
        "request_id": request_id,
        "status": status,
        "count": count,
        "files": clean_files,
    }


def encode_search_result(result: dict[str, object]) -> str:
    normalized = make_search_result(
        result.get("request_id"),
        result.get("status"),
        result.get("count", 0),
        result.get("files", ()),
    )
    return CONTROL_PREFIX + json.dumps(normalized, ensure_ascii=False, separators=(",", ":")) + "\n"


def parse_control_line(line: str) -> dict[str, object] | None:
    if not isinstance(line, str) or len(line) > MAX_CONTROL_LINE or not line.startswith(CONTROL_PREFIX):
        return None
    try:
        payload = json.loads(line[len(CONTROL_PREFIX):])
        if not isinstance(payload, dict) or set(payload) != {"version", "type", "request_id", "status", "count", "files"}:
            return None
        if payload["version"] != 1 or payload["type"] != RESULT_TYPE:
            return None
        return make_search_result(
            payload["request_id"],
            payload["status"],
            payload["count"],
            payload["files"],
        )
    except (ValueError, TypeError):
        return None


class DesktopFileSearchChannel:
    """Synchronous runtime requests paired with bounded asynchronous UI replies."""

    def __init__(self, emit=emit_event):
        self._emit = emit
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[threading.Event, dict[str, object] | None]] = {}
        self._reader_started = False
        self._closed = False

    def start_control_reader(self, stream=None) -> bool:
        if os.environ.get("ASTRA_DESKTOP_EVENTS") != "1":
            return False
        with self._lock:
            if self._reader_started or self._closed:
                return False
            self._reader_started = True
        source = stream if stream is not None else sys.stdin
        threading.Thread(target=self._read_controls, args=(source,), name="astra-desktop-control", daemon=True).start()
        return True

    def _read_controls(self, stream) -> None:
        try:
            while True:
                line = stream.readline(MAX_CONTROL_LINE + 1)
                if not line:
                    break
                result = parse_control_line(line.rstrip("\r\n"))
                if result is None:
                    continue
                request_id = result["request_id"]
                with self._lock:
                    pending = self._pending.get(request_id)
                    if pending is None:
                        continue
                    event, _ = pending
                    self._pending[request_id] = (event, result)
                    event.set()
        finally:
            self.close()

    def search(self, query: str, timeout_seconds: float = 10.0) -> dict[str, object] | None:
        clean_query = validate_query(query)
        with self._lock:
            if not self._reader_started or self._closed:
                return None
            request_id = uuid4().hex
            completed = threading.Event()
            self._pending[request_id] = (completed, None)
        request = make_search_request(request_id, clean_query)
        try:
            emitted = self._emit(REQUEST_TYPE, json.dumps(request, ensure_ascii=False, separators=(",", ":")))
        except Exception:
            emitted = False
        if not emitted:
            with self._lock:
                self._pending.pop(request_id, None)
            return None
        timeout = min(12.0, max(0.1, float(timeout_seconds)))
        if not completed.wait(timeout):
            with self._lock:
                self._pending.pop(request_id, None)
            return {"status": "search_failed", "count": 0, "files": []}
        with self._lock:
            pending = self._pending.pop(request_id, None)
        return pending[1] if pending is not None else {"status": "search_failed", "count": 0, "files": []}

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for event, _result in self._pending.values():
                event.set()
