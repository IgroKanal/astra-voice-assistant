"""Conservative first-sentence gate for local incremental speech."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Callable


_SENTENCE_END = re.compile(r"[.!?…](?=\s)")
_UNSAFE_MARKERS = ("<think", "<thought", "```", "analysis:", "reasoning:", "черновик", "вариант ")
_REASONING_PREFIXES = (
    "хорошо, пользователь", "итак, пользователь", "пользователь спрашивает",
    "хорошо, давай подумаю", "давай подумаю над", "мне нужно сначала подумать",
    "okay, the user", "the user asks", "let me think about",
)
_MAX_BUFFER_CHARS = 1600
_MAX_SENTENCE_CHARS = 400


@dataclass(frozen=True)
class EarlySpeechResult:
    """Outcome of waiting for the current early speech playback."""

    finished: bool
    succeeded: bool = False
    text: str = ""


@dataclass
class _EarlySpeechTask:
    text: str
    completed: threading.Event = field(default_factory=threading.Event)
    succeeded: bool = False


class EarlySpeechCoordinator:
    """Keep at most one early playback alive until it has actually stopped.

    The voice runtime calls ``start`` and ``wait`` on its own thread. Playback
    runs on a daemon thread, so a stalled speech engine cannot stall shutdown.
    A timed-out task stays tracked until completion; its late result can never
    be mistaken for the result of a later playback.
    """

    def __init__(
        self,
        speak: Callable[[str], bool],
        on_error: Callable[[], None] | None = None,
    ):
        self._speak = speak
        self._on_error = on_error
        self._task: _EarlySpeechTask | None = None

    def start(self, text: str) -> bool:
        if not isinstance(text, str) or not text.strip():
            return False
        if self._task is not None:
            if not self._task.completed.is_set():
                return False
            self._task = None

        task = _EarlySpeechTask(text=text)
        self._task = task

        def play() -> None:
            try:
                task.succeeded = bool(self._speak(task.text))
            except Exception:
                if self._on_error is not None:
                    try:
                        self._on_error()
                    except Exception:
                        pass
            finally:
                task.completed.set()

        try:
            threading.Thread(target=play, name="AstraEarlySpeech", daemon=True).start()
        except Exception:
            self._task = None
            return False
        return True

    def wait(self, timeout_seconds: float) -> EarlySpeechResult:
        task = self._task
        if task is None:
            return EarlySpeechResult(finished=True)
        if not task.completed.wait(timeout_seconds):
            return EarlySpeechResult(finished=False, text=task.text)
        if self._task is task:
            self._task = None
        return EarlySpeechResult(finished=True, succeeded=task.succeeded, text=task.text)


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
            or lowered.startswith(_REASONING_PREFIXES)
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
