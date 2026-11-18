"""Bounded retry policy for a temporarily unavailable capture device."""
from __future__ import annotations

from typing import Callable


def recover_microphone(reinitialize: Callable[[], bool], wait: Callable[[float], None], notify: Callable[[int], None]) -> bool:
    """Try the selected microphone twice, waiting at most 1.5 seconds between attempts."""
    for attempt, delay in enumerate((0.5, 1.0), 1):
        notify(attempt)
        wait(delay)
        try:
            if reinitialize() is True:
                return True
        except Exception:
            pass
    return False
