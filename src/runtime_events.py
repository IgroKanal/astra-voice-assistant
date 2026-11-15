"""Versioned, line-delimited runtime events for the local desktop pipe."""
from __future__ import annotations

import json
import ipaddress
import os
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

PREFIX = "@ASTRA_EVENT "
KINDS = frozenset({"assistant", "transcript", "state", "error", "conversation_reset", "file_search_request", "file_open_request", "file_read_request", "file_question_request"})
MAX_WEB_SOURCES = 3
MAX_EVENT_TEXT = 100_000


@dataclass(frozen=True)
class RuntimeEvent:
    """Validated local UI event; ``data`` is reserved for known typed payloads."""

    kind: str
    text: str
    data: dict[str, object] | None = None


def _clean_web_sources_data(data: object) -> dict[str, object]:
    if not isinstance(data, dict) or set(data) != {"kind", "sources"} or data.get("kind") != "web_sources":
        raise ValueError("Unsupported structured event payload")
    sources = data.get("sources")
    if not isinstance(sources, (list, tuple)) or not 1 <= len(sources) <= MAX_WEB_SOURCES:
        raise ValueError("Web source payload must contain one to three citations")
    clean_sources = []
    for expected_index, source in enumerate(sources, 1):
        if not isinstance(source, dict) or set(source) != {"index", "title", "url"}:
            raise ValueError("Invalid web source fields")
        index, title, url = source["index"], source["title"], source["url"]
        if type(index) is not int or index != expected_index:
            raise ValueError("Web source indices must be consecutive")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 256:
            raise ValueError("Invalid web source title")
        if any(unicodedata.category(char).startswith("C") for char in title):
            raise ValueError("Control characters are not allowed in web source titles")
        if (not isinstance(url, str) or not 1 <= len(url) <= 2048
                or any(char.isspace() or unicodedata.category(char).startswith("C") for char in url)):
            raise ValueError("Invalid web source URL")
        try:
            parsed = urlsplit(url)
            valid_port = parsed.port is None or 1 <= parsed.port <= 65535
        except ValueError:
            valid_port = False
            parsed = None
        if (parsed is None or parsed.scheme.casefold() != "https" or not parsed.hostname
                or parsed.username or parsed.password or not valid_port):
            raise ValueError("Web source URLs must use HTTPS and cannot include credentials")
        host = parsed.hostname.casefold().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local")):
            raise ValueError("Web source URLs cannot target local host names")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("Web source URLs cannot target private or reserved IP addresses")
        clean_sources.append({"index": index, "title": title.strip(), "url": url})
    return {"kind": "web_sources", "sources": clean_sources}


def emit_event(kind: str, text: str, *, data: dict[str, object] | None = None) -> bool:
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("Unsupported runtime event")
    if not isinstance(text, str) or len(text) > MAX_EVENT_TEXT:
        raise ValueError("Invalid runtime event text")
    payload = {"version": 1, "type": kind, "text": text}
    if data is not None:
        if kind != "assistant":
            raise ValueError("Structured data is supported only on assistant events")
        payload["data"] = _clean_web_sources_data(data)
    if os.environ.get("ASTRA_DESKTOP_EVENTS") != "1":
        return False
    print(PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)
    return True


def parse_event_record(line: str) -> RuntimeEvent | None:
    """Parse a validated event, retaining optional data for newer desktop clients."""
    if not isinstance(line, str):
        return None
    line = line.removeprefix("Ты: ")
    if not line.startswith(PREFIX):
        return None
    try:
        event = json.loads(line[len(PREFIX):])
    except (ValueError, TypeError):
        return None
    if (not isinstance(event, dict) or type(event.get("version")) is not int
            or event["version"] != 1 or not isinstance(event.get("type"), str)
            or event["type"] not in KINDS or not isinstance(event.get("text"), str)
            or len(event["text"]) > MAX_EVENT_TEXT
            or set(event) - {"version", "type", "text", "data"}):
        return None
    data = None
    if "data" in event:
        if event["type"] != "assistant":
            return None
        try:
            data = _clean_web_sources_data(event["data"])
        except (TypeError, ValueError):
            return None
    return RuntimeEvent(event["type"], event["text"], data)


def parse_event(line: str) -> tuple[str, str] | None:
    """Legacy tuple parser for the current desktop client."""
    event = parse_event_record(line)
    return (event.kind, event.text) if event is not None else None
