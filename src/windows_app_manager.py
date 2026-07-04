from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from src.command_parser import normalize_text
from src.config_loader import AppConfig


@dataclass(frozen=True)
class AppActionResult:
    ok: bool
    message: str


class WindowsAppManager:
    """Открывает и закрывает только приложения из config/apps.json."""

    def __init__(self, apps: dict[str, AppConfig], logger: logging.Logger | None = None) -> None:
        self.apps = apps
        self.logger = logger or logging.getLogger(__name__)

    def find_app(self, user_target: str) -> AppConfig | None:
        target = normalize_text(user_target)
        if not target:
            return None

        # 1. Точное совпадение с ключом приложения или alias.
        for app in self.apps.values():
            aliases = [normalize_text(alias) for alias in app.aliases]
            if target == app.name or target in aliases:
                return app

        # 2. Мягкое совпадение: "гугл браузер" может содержать alias "браузер".
        for app in self.apps.values():
            aliases = [normalize_text(alias) for alias in app.aliases]
            if any(alias and alias in target for alias in aliases):
                return app

        return None

    def open_app(self, user_target: str) -> AppActionResult:
        app = self.find_app(user_target)
        if app is None:
            return AppActionResult(False, "Не нашёл такое приложение в списке.")

        try:
            # Все команды берутся только из конфига, а не из речи пользователя.
            subprocess.Popen(app.open_command)
            self.logger.info("Запуск приложения: %s -> %s", app.name, app.open_command)
            return AppActionResult(True, f"Открываю {app.name}.")
        except FileNotFoundError:
            self.logger.exception("Файл запуска не найден для приложения: %s", app.name)
            return AppActionResult(False, f"Не удалось открыть {app.name}: файл запуска не найден.")
        except OSError as exc:
            self.logger.exception("Ошибка запуска приложения: %s", app.name)
            return AppActionResult(False, f"Не удалось открыть {app.name}: {exc}")

    def close_app(self, user_target: str) -> AppActionResult:
        app = self.find_app(user_target)
        if app is None:
            return AppActionResult(False, "Не нашёл такое приложение в списке.")

        try:
            result = subprocess.run(
                ["taskkill", "/IM", app.process_name, "/F"],
                capture_output=True,
                text=True,
                encoding="cp866",
                errors="replace",
                timeout=10,
            )
            if result.returncode == 0:
                self.logger.info("Закрытие приложения: %s -> %s", app.name, app.process_name)
                return AppActionResult(True, f"Закрываю {app.name}.")

            output = (result.stderr or result.stdout or "").strip()
            self.logger.warning("taskkill вернул код %s для %s: %s", result.returncode, app.name, output)
            return AppActionResult(False, f"Не удалось закрыть {app.name}. Возможно, оно не запущено.")
        except subprocess.TimeoutExpired:
            self.logger.exception("Таймаут закрытия приложения: %s", app.name)
            return AppActionResult(False, f"Не удалось закрыть {app.name}: превышено время ожидания.")
        except OSError as exc:
            self.logger.exception("Ошибка закрытия приложения: %s", app.name)
            return AppActionResult(False, f"Не удалось закрыть {app.name}: {exc}")
