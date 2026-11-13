from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MediaActionResult:
    ok: bool
    message: str


class _KeyboardLike(Protocol):
    def send_shortcut(self, name: str): ...


class _AppManagerLike(Protocol):
    def close_app(self, target: str): ...


class MediaController:
    """Safe media actions with bounded player targeting.

    The controller never builds a shell command from recognized speech.  It
    delegates only fixed media action names to ``KeyboardController`` and uses
    a fixed allowlisted application name for Yandex Music shutdown.

    Windows and many players interpret one ``Previous Track`` event as
    "restart the current track" when playback is already several seconds in.
    The explicit previous-track action therefore sends two bounded previous
    events.  ``restart_current`` remains available as the single-event action.
    """

    _SHORTCUTS = {
        "play": "media_play",
        "play_pause": "media_play_pause",
        "next": "media_next",
        "previous": "media_previous",
        "restart_current": "media_previous",
        "stop": "media_stop",
    }

    def __init__(
        self,
        keyboard: _KeyboardLike,
        app_manager: _AppManagerLike,
        logger: logging.Logger,
    ) -> None:
        self.keyboard = keyboard
        self.app_manager = app_manager
        self.logger = logger

    def execute(self, action: str) -> MediaActionResult:
        base_action, target = self._split_action(action)
        if target not in {"", "local", "yandex"}:
            return MediaActionResult(False, "Неизвестная цель управления музыкой.")

        if base_action in self._SHORTCUTS:
            repeat = 2 if base_action == "previous" else 1
            result = self._send_media_shortcut(
                self._SHORTCUTS[base_action],
                target=target,
                repeat=repeat,
            )
            return MediaActionResult(bool(result.ok), result.message)

        if base_action == "open_play_local":
            open_result = self.app_manager.open_app("медиаплеер")
            if not open_result.ok:
                return MediaActionResult(False, open_result.message)

            # Groove/Media Player is asynchronous.  Retry only the fixed local
            # target; KeyboardController refuses to fall back to another global
            # media session while an explicit target is requested.
            play_result = None
            for delay in (0.35, 0.55, 0.75, 0.95):
                time.sleep(delay)
                play_result = self._send_media_shortcut(
                    "media_play",
                    target="local",
                    repeat=1,
                )
                if play_result.ok:
                    return MediaActionResult(True, "Открываю и включаю локальную музыку.")

            message = play_result.message if play_result is not None else "Плеер не ответил."
            return MediaActionResult(
                False,
                "Локальный плеер открыт, но не удалось запустить воспроизведение. " + message,
            )

        if base_action == "shutdown_yandex_music":
            stop_result = self._send_media_shortcut(
                "media_stop",
                target="yandex",
                repeat=1,
            )
            close_result = self.app_manager.close_app("яндекс музыка")
            if close_result.ok:
                if getattr(close_result, "completed", None) is not None:
                    prefix = "Команда остановки музыки отправлена. " if stop_result.ok else "Не удалось остановить музыку. "
                    return MediaActionResult(bool(stop_result.ok), prefix + close_result.message)
                return MediaActionResult(True, "Музыка остановлена. Яндекс Музыка закрыта.")
            if stop_result.ok:
                return MediaActionResult(False, f"Музыка остановлена, но {close_result.message}")
            return MediaActionResult(False, close_result.message)

        return MediaActionResult(False, "Не знаю такую команду управления музыкой.")

    def _send_media_shortcut(self, name: str, target: str, repeat: int):
        """Use the richer media API when available, with legacy fallback.

        ``target`` is one of the fixed parser outputs: empty, ``local`` or
        ``yandex``.  It is never an executable path or arbitrary process name.
        """
        sender = getattr(self.keyboard, "send_media_shortcut", None)
        if callable(sender):
            return sender(name, target=target, repeat=repeat)

        result = None
        for _ in range(max(1, repeat)):
            result = self.keyboard.send_shortcut(name)
            if not result.ok:
                break
        return result

    @staticmethod
    def _split_action(action: str) -> tuple[str, str]:
        clean = (action or "").strip().lower()
        if ":" not in clean:
            return clean, ""
        base, target = clean.split(":", 1)
        return base, target
