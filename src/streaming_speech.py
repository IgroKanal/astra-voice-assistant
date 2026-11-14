"""Conservative first-sentence gate for local incremental speech."""
from __future__ import annotations

import re
from typing import Callable


_SENTENCE_END = re.compile(r"[.!?…](?=\s)")
_UNSAFE_MARKERS = ("<think", "<thought", "```", "analysis:", "reasoning:", "черновик", "вариант ")
_MAX_BUFFER_CHARS = 1600
_MAX_SENTENCE_CHARS = 400


class FirstSentenceBuffer:
    """Release at most one cleaned, complete prose sentence from a token stream."""

    def __init__(self, cleaner: Callable[[str], str] | None = None):
        self._cleaner = cleaner or (lambda text: text.strip())
        self._buffer = ""
        self._finished = False

    def feed(self, chunk: object) -> str:
        if self._finished or not isinstance(chunk, str) or not chunk:
            return ""
        self._buffer += chunk
        if len(self._buffer) > _MAX_BUFFER_CHARS:
            self._finished = True
            return ""

        match = _SENTENCE_END.search(self._buffer)
        if match is None:
            return ""
        self._finished = True
        candidate = self._buffer[: match.end()].strip()
        lowered = candidate.casefold()
        if (
            not candidate
            or len(candidate) > _MAX_SENTENCE_CHARS
            or not candidate[0].isalnum()
            or any(marker in lowered for marker in _UNSAFE_MARKERS)
            or any(char in candidate for char in "{}[]<>`")
        ):
            return ""
        try:
            clean = self._cleaner(candidate)
        except Exception:
            return ""
        if not isinstance(clean, str):
            return ""
        clean = " ".join(clean.split())
        if not clean or len(clean) > _MAX_SENTENCE_CHARS:
            return ""
        return clean
