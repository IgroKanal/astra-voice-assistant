"""Versioned, line-delimited runtime events for the local desktop pipe."""
from __future__ import annotations

import json
import os

PREFIX = "@ASTRA_EVENT "
KINDS = frozenset({"assistant", "transcript", "state", "error", "conversation_reset"})


def emit_event(kind: str, text: str) -> bool:
    if os.environ.get("ASTRA_DESKTOP_EVENTS") != "1":
        return False
    if kind not in KINDS:
        raise ValueError("Unsupported runtime event")
    print(PREFIX + json.dumps({"version": 1, "type": kind, "text": text}, ensure_ascii=False), flush=True)
    return True


def parse_event(line: str) -> tuple[str, str] | None:
    line = line.removeprefix("Ты: ")
    if not line.startswith(PREFIX):
        return None
    try:
        event = json.loads(line[len(PREFIX):])
    except (ValueError, TypeError):
        return None
    if not isinstance(event, dict) or event.get("version") != 1 or event.get("type") not in KINDS or not isinstance(event.get("text"), str):
        return None
    return event["type"], event["text"]
