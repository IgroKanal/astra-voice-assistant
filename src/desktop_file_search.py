"""Bounded voice search/open/read requests for the desktop-granted folder."""
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
OPEN_REQUEST_TYPE = "file_open_request"
OPEN_RESULT_TYPE = "file_open_result"
READ_REQUEST_TYPE = "file_read_request"
READ_RESULT_TYPE = "file_read_result"
MAX_QUERY_CHARS = 120
MAX_RESULT_PATH_CHARS = 400
MAX_SPOKEN_RESULTS = 3
MAX_SPOKEN_DOCUMENT_CHARS = 1600
MAX_RESULT_COUNT = 500
MAX_CONTROL_LINE = 8192
_SEARCH_STATUSES = frozenset({"ok", "no_workspace", "cancelled", "search_failed"})
_OPEN_STATUSES = frozenset({"ok", "no_workspace", "not_found", "ambiguous", "unsafe_file", "cancelled", "open_failed"})
_READ_STATUSES = frozenset({"ok", "no_workspace", "not_found", "ambiguous", "unsafe_file", "cancelled", "read_failed"})


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


def make_file_open_request(request_id: str, filename: str) -> dict[str, object]:
    request = make_search_request(request_id, filename)
    return {**request, "type": OPEN_REQUEST_TYPE}


def parse_file_open_request(text: str) -> dict[str, object]:
    if not isinstance(text, str) or len(text) > MAX_CONTROL_LINE:
        raise ValueError("Некорректный запрос открытия файла")
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        raise ValueError("Некорректный запрос открытия файла") from None
    if not isinstance(payload, dict) or set(payload) != {"version", "type", "request_id", "query"}:
        raise ValueError("Некорректный запрос открытия файла")
    if payload["version"] != 1 or payload["type"] != OPEN_REQUEST_TYPE:
        raise ValueError("Неподдерживаемая версия запроса открытия файла")
    return make_file_open_request(payload["request_id"], payload["query"])


def make_file_read_request(request_id: str, filename: str) -> dict[str, object]:
    request = make_search_request(request_id, filename)
    return {**request, "type": READ_REQUEST_TYPE}


def parse_file_read_request(text: str) -> dict[str, object]:
    if not isinstance(text, str) or len(text) > MAX_CONTROL_LINE:
        raise ValueError("Некорректный запрос чтения файла")
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        raise ValueError("Некорректный запрос чтения файла") from None
    if not isinstance(payload, dict) or set(payload) != {"version", "type", "request_id", "query"}:
        raise ValueError("Некорректный запрос чтения файла")
    if payload["version"] != 1 or payload["type"] != READ_REQUEST_TYPE:
        raise ValueError("Неподдерживаемая версия запроса чтения файла")
    return make_file_read_request(payload["request_id"], payload["query"])


def parse_file_request(text: str) -> tuple[str, dict[str, object]]:
    if not isinstance(text, str) or len(text) > MAX_CONTROL_LINE:
        raise ValueError("Некорректный запрос файлового действия")
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        raise ValueError("Некорректный запрос файлового действия") from None
    if not isinstance(payload, dict):
        raise ValueError("Некорректный запрос файлового действия")
    if payload.get("type") == REQUEST_TYPE:
        return "search", parse_search_request(text)
    if payload.get("type") == OPEN_REQUEST_TYPE:
        return "open", parse_file_open_request(text)
    if payload.get("type") == READ_REQUEST_TYPE:
        return "read", parse_file_read_request(text)
    raise ValueError("Неизвестный тип файлового действия")


def normalize_spoken_excerpt(text: object, *, truncate: bool = False) -> str:
    """Remove non-speech controls and bound a document excerpt for local SAPI."""
    if not isinstance(text, str):
        raise ValueError("Некорректный текст документа")
    if truncate:
        # The source extractor is bounded to 1 MB of characters. Inspect only a
        # small prefix so control-heavy documents cannot make this copy costly.
        text = text[: MAX_SPOKEN_DOCUMENT_CHARS * 4]
    elif len(text) > MAX_SPOKEN_DOCUMENT_CHARS:
        raise ValueError("Текст документа превышает лимит озвучивания")
    safe = []
    for char in text:
        if char.isspace():
            safe.append(" ")
        elif unicodedata.category(char).startswith("C"):
            continue
        else:
            safe.append(char)
    normalized = " ".join("".join(safe).split())
    if truncate and len(normalized) > MAX_SPOKEN_DOCUMENT_CHARS:
        clipped = normalized[:MAX_SPOKEN_DOCUMENT_CHARS]
        normalized = clipped.rsplit(" ", 1)[0] if " " in clipped else clipped
    if not normalized or len(normalized) > MAX_SPOKEN_DOCUMENT_CHARS:
        raise ValueError("В документе нет допустимого текста для чтения")
    return normalized


def make_search_result(
    request_id: str,
    status: str,
    count: int = 0,
    files: tuple[str, ...] | list[str] = (),
) -> dict[str, object]:
    if not isinstance(request_id, str) or len(request_id) != 32 or any(char not in "0123456789abcdef" for char in request_id):
        raise ValueError("Некорректный идентификатор поиска")
    if status not in _SEARCH_STATUSES or type(count) is not int or not 0 <= count <= MAX_RESULT_COUNT:
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


def make_file_open_result(request_id: str, status: str, relative_path: str = "") -> dict[str, object]:
    if status not in _OPEN_STATUSES:
        raise ValueError("Некорректный результат открытия файла")
    files = [relative_path] if status == "ok" else []
    if status == "ok" and not relative_path:
        raise ValueError("Для успешного открытия нужен относительный путь")
    checked = make_search_result(request_id, "ok", len(files), files)
    return {**checked, "type": OPEN_RESULT_TYPE, "status": status}


def make_file_read_result(
    request_id: str,
    status: str,
    filename: str = "",
    text: str = "",
) -> dict[str, object]:
    if not isinstance(request_id, str) or len(request_id) != 32 or any(char not in "0123456789abcdef" for char in request_id):
        raise ValueError("Некорректный идентификатор чтения")
    if not isinstance(status, str) or status not in _READ_STATUSES:
        raise ValueError("Некорректный результат чтения файла")
    if not isinstance(filename, str) or not isinstance(text, str):
        raise ValueError("Некорректные данные результата чтения")
    if status != "ok":
        if filename or text:
            raise ValueError("Отказ не может содержать данные файла")
        return {
            "version": 1,
            "type": READ_RESULT_TYPE,
            "request_id": request_id,
            "status": status,
            "filename": "",
            "text": "",
        }
    clean_filename = validate_query(filename)
    clean_text = normalize_spoken_excerpt(text)
    return {
        "version": 1,
        "type": READ_RESULT_TYPE,
        "request_id": request_id,
        "status": status,
        "filename": clean_filename,
        "text": clean_text,
    }


def encode_search_result(result: dict[str, object]) -> str:
    normalized = make_search_result(
        result.get("request_id"),
        result.get("status"),
        result.get("count", 0),
        result.get("files", ()),
    )
    return CONTROL_PREFIX + json.dumps(normalized, ensure_ascii=False, separators=(",", ":")) + "\n"


def encode_file_result(result: dict[str, object]) -> str:
    if not isinstance(result, dict):
        raise ValueError("Некорректный результат файлового действия")
    if result.get("type") == READ_RESULT_TYPE:
        normalized = make_file_read_result(
            result.get("request_id"),
            result.get("status"),
            result.get("filename", ""),
            result.get("text", ""),
        )
    elif result.get("type") == OPEN_RESULT_TYPE:
        files = result.get("files")
        count = result.get("count")
        status = result.get("status")
        if not isinstance(files, list) or type(count) is not int:
            raise ValueError("Некорректный результат открытия файла")
        if status == "ok":
            if count != 1 or len(files) != 1:
                raise ValueError("Для успешного открытия нужен ровно один файл")
        elif count != 0 or files:
            raise ValueError("Результат отказа не может содержать файлы")
        normalized = make_file_open_result(
            result.get("request_id"),
            status,
            files[0] if files else "",
        )
    else:
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
        if not isinstance(payload, dict):
            return None
        if payload.get("version") != 1 or payload.get("type") not in {RESULT_TYPE, OPEN_RESULT_TYPE, READ_RESULT_TYPE}:
            return None
        if payload["type"] == READ_RESULT_TYPE:
            if set(payload) != {"version", "type", "request_id", "status", "filename", "text"}:
                return None
            return make_file_read_result(
                payload["request_id"], payload["status"], payload["filename"], payload["text"],
            )
        if set(payload) != {"version", "type", "request_id", "status", "count", "files"}:
            return None
        if payload["type"] == OPEN_RESULT_TYPE:
            if type(payload["count"]) is not int or not isinstance(payload["files"], list):
                return None
            if payload["status"] == "ok":
                if payload["count"] != 1 or len(payload["files"]) != 1:
                    return None
                return make_file_open_result(payload["request_id"], "ok", payload["files"][0])
            if payload["count"] != 0 or payload["files"]:
                return None
            return make_file_open_result(payload["request_id"], payload["status"])
        return make_search_result(
            payload["request_id"],
            payload["status"],
            payload["count"],
            payload["files"],
        )
    except (ValueError, TypeError):
        return None


class DesktopFileSearchChannel:
    """Synchronous runtime file requests paired with bounded asynchronous UI replies."""

    def __init__(self, emit=emit_event):
        self._emit = emit
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[threading.Event, dict[str, object] | None, str]] = {}
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
                    event, _result, expected_type = pending
                    if result["type"] != expected_type:
                        continue
                    self._pending[request_id] = (event, result, expected_type)
                    event.set()
        finally:
            self.close()

    def search(self, query: str, timeout_seconds: float = 10.0) -> dict[str, object] | None:
        return self._request(query, "search", timeout_seconds)

    def open_exact(self, filename: str, timeout_seconds: float = 10.0) -> dict[str, object] | None:
        return self._request(filename, "open", timeout_seconds)

    def read_exact(self, filename: str, timeout_seconds: float = 10.0) -> dict[str, object] | None:
        return self._request(filename, "read", timeout_seconds)

    def _request(self, query: str, operation: str, timeout_seconds: float) -> dict[str, object] | None:
        clean_query = validate_query(query)
        if operation == "open":
            request = make_file_open_request(uuid4().hex, clean_query)
            event_type = OPEN_REQUEST_TYPE
            result_type = OPEN_RESULT_TYPE
        elif operation == "read":
            request = make_file_read_request(uuid4().hex, clean_query)
            event_type = READ_REQUEST_TYPE
            result_type = READ_RESULT_TYPE
        elif operation == "search":
            request = make_search_request(uuid4().hex, clean_query)
            event_type = REQUEST_TYPE
            result_type = RESULT_TYPE
        else:
            raise ValueError("Неизвестное файловое действие")
        with self._lock:
            if not self._reader_started or self._closed:
                return None
            request_id = request["request_id"]
            completed = threading.Event()
            self._pending[request_id] = (completed, None, result_type)
        try:
            emitted = self._emit(event_type, json.dumps(request, ensure_ascii=False, separators=(",", ":")))
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
            return (
                make_file_open_result(request_id, "open_failed")
                if operation == "open"
                else make_file_read_result(request_id, "read_failed")
                if operation == "read"
                else make_search_result(request_id, "search_failed")
            )
        with self._lock:
            pending = self._pending.pop(request_id, None)
        if pending is not None and pending[1] is not None:
            return pending[1]
        return (
            make_file_open_result(request_id, "open_failed")
            if operation == "open"
            else make_file_read_result(request_id, "read_failed")
            if operation == "read"
            else make_search_result(request_id, "search_failed")
        )

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for event, _result, _expected_type in self._pending.values():
                event.set()
