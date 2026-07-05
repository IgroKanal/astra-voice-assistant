from __future__ import annotations

import difflib
import logging
import subprocess
from dataclasses import dataclass
from typing import Iterable

from src.command_parser import normalize_text
from src.config_loader import AppConfig


@dataclass(frozen=True)
class AppActionResult:
    ok: bool
    message: str


class WindowsAppManager:
    """Открывает и закрывает только приложения из config/apps.json."""

    _FUZZY_CUTOFF = 0.62
    _FUZZY_MARGIN = 0.08

    def __init__(
        self,
        apps: dict[str, AppConfig],
        logger: logging.Logger | None = None,
    ) -> None:
        self.apps = apps
        self.logger = logger or logging.getLogger(__name__)

    def find_app(self, user_target: str) -> AppConfig | None:
        target = normalize_text(user_target)
        if not target:
            return None

        candidates = self._candidate_aliases()

        # 1. Точное совпадение с ключом приложения или alias.
        for alias, app in candidates:
            if target == alias:
                return app

        # 2. Безопасное частичное совпадение.
        # Работает для "бло" -> "блокнот", но не для слишком коротких фрагментов.
        partial_matches: list[tuple[str, AppConfig]] = []
        for alias, app in candidates:
            if len(target) >= 3 and (target in alias or alias in target):
                partial_matches.append((alias, app))

        unique_partial_apps = {app.name: (alias, app) for alias, app in partial_matches}
        if len(unique_partial_apps) == 1:
            alias, app = next(iter(unique_partial_apps.values()))
            self.logger.info(
                "Fuzzy app partial match: target=%r alias=%r app=%s",
                target,
                alias,
                app.name,
            )
            return app

        if len(unique_partial_apps) > 1:
            self.logger.info(
                "Fuzzy app partial ambiguous: target=%r matches=%s",
                target,
                sorted(unique_partial_apps),
            )

        # 3. Fuzzy по похожести строк с проверкой отрыва от второго кандидата.
        scored = self._rank_aliases(target, candidates)
        if not scored:
            return None

        best_score, best_alias, best_app = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0

        if best_score >= self._FUZZY_CUTOFF and best_score - second_score >= self._FUZZY_MARGIN:
            self.logger.info(
                "Fuzzy app ratio match: target=%r alias=%r app=%s score=%.2f second=%.2f",
                target,
                best_alias,
                best_app.name,
                best_score,
                second_score,
            )
            return best_app

        if best_score >= self._FUZZY_CUTOFF:
            self.logger.info(
                "Fuzzy app ratio ambiguous: target=%r best=%r %.2f second=%.2f",
                target,
                best_alias,
                best_score,
                second_score,
            )

        return None

    def _candidate_aliases(self) -> list[tuple[str, AppConfig]]:
        candidates: list[tuple[str, AppConfig]] = []
        seen: set[tuple[str, str]] = set()

        for app in self.apps.values():
            for raw_alias in self._aliases_for_app(app):
                alias = normalize_text(raw_alias)
                if not alias:
                    continue
                key = (alias, app.name)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append((alias, app))

        return candidates

    def _aliases_for_app(self, app: AppConfig) -> Iterable[str]:
        yield app.name
        yield from app.aliases

    def _rank_aliases(
        self,
        target: str,
        candidates: list[tuple[str, AppConfig]],
    ) -> list[tuple[float, str, AppConfig]]:
        scored: list[tuple[float, str, AppConfig]] = []
        for alias, app in candidates:
            if not alias:
                continue
            score = difflib.SequenceMatcher(None, target, alias).ratio()
            scored.append((score, alias, app))

        return sorted(scored, key=lambda item: item[0], reverse=True)

    def app_names_for_prompt(self) -> list[str]:
        """Возвращает список приложений и alias для LLM-router."""
        names: list[str] = []
        for app in self.apps.values():
            names.append(app.name)
            names.extend(app.aliases)
        return sorted(set(names))

    def open_app(self, user_target: str) -> AppActionResult:
        app = self.find_app(user_target)
        if app is None:
            return AppActionResult(False, "Не нашёл такое приложение в списке.")

        try:
            # Все команды берутся только из конфига, а не из речи пользователя.
            subprocess.Popen(app.open_command)
            self.logger.info("Запуск приложения: %s -> %s", app.name, app.open_command)
            return AppActionResult(True, "Открываю.")
        except FileNotFoundError:
            self.logger.exception("Файл запуска не найден: %s", app.name)
            return AppActionResult(
                False,
                f"Не удалось открыть {app.name}: файл запуска не найден.",
            )
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
                self.logger.info("Закрытие приложения: %s", app.name)
                return AppActionResult(True, "Закрываю.")

            output = (result.stderr or result.stdout or "").strip()
            self.logger.warning(
                "taskkill вернул код %s для %s: %s",
                result.returncode,
                app.name,
                output,
            )
            return AppActionResult(
                False,
                f"Не удалось закрыть {app.name}. Возможно, оно не запущено.",
            )
        except subprocess.TimeoutExpired:
            self.logger.exception("Таймаут закрытия приложения: %s", app.name)
            return AppActionResult(
                False,
                f"Не удалось закрыть {app.name}: превышено время ожидания.",
            )
        except OSError as exc:
            self.logger.exception("Ошибка закрытия приложения: %s", app.name)
            return AppActionResult(False, f"Не удалось закрыть {app.name}: {exc}")
