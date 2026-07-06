from __future__ import annotations

import difflib
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.command_parser import normalize_text
from src.config_loader import AppConfig


@dataclass(frozen=True)
class AppActionResult:
    ok: bool
    message: str


class WindowsAppManager:
    """Открывает и закрывает только приложения из config/apps.json.

    v0.9.4:
    - generic target "браузер" respects BROWSER_PREFERRED;
    - VS Code launch resolves direct Code.exe and avoids code.cmd wrappers;
    - VS Code stdout/stderr are detached from Astra console.
    """

    _FUZZY_CUTOFF = 0.62
    _FUZZY_MARGIN = 0.08
    _BROWSER_GENERIC_TARGETS = {"браузер", "browser"}
    _BROWSER_APP_NAMES = {"firefox", "chrome", "edge", "msedge"}
    _FUZZY_BLOCKLIST = {
        "окно",
        "акно",
        "последнее",
        "последние",
        "последнии",
        "последний",
        "posledniy",
        "ча",
        "чат",
    }

    def __init__(
        self,
        apps: dict[str, AppConfig],
        logger: logging.Logger | None = None,
        browser_preferred: str = "",
    ) -> None:
        self.apps = apps
        self.logger = logger or logging.getLogger(__name__)
        self.browser_preferred = normalize_text(browser_preferred).removesuffix(".exe")

    def find_app(self, user_target: str) -> AppConfig | None:
        target = normalize_text(user_target)
        if not target:
            return None

        if target in self._BROWSER_GENERIC_TARGETS:
            preferred = self._preferred_browser_app()
            if preferred is not None:
                self.logger.info(
                    "Generic browser target resolved by BROWSER_PREFERRED: %r -> %s",
                    target,
                    preferred.name,
                )
                return preferred

        if target in self._FUZZY_BLOCKLIST:
            self.logger.info("Fuzzy app lookup skipped for generic target: %r", target)
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

    def _preferred_browser_app(self) -> AppConfig | None:
        preferred = self.browser_preferred
        if preferred == "msedge":
            preferred = "edge"

        if preferred:
            app = self._find_exact_app(preferred)
            if app is not None:
                return app

        for fallback_name in ("firefox", "chrome", "edge"):
            app = self._find_exact_app(fallback_name)
            if app is not None:
                return app

        return None

    def _find_exact_app(self, target: str) -> AppConfig | None:
        clean = normalize_text(target)
        for alias, app in self._candidate_aliases():
            if clean == alias:
                return app
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

        command = self._resolve_open_command(app)
        if command is None:
            if app.name == "vscode":
                return AppActionResult(
                    False,
                    "Не нашёл Code.exe. Проверь путь к VS Code или установи команду code в PATH.",
                )
            return AppActionResult(False, f"Не удалось открыть {app.name}: команда запуска не найдена.")

        try:
            # Все команды берутся только из конфига/локального resolver-а, а не из речи пользователя.
            if app.name == "vscode":
                # VS Code иногда пишет Electron-логи в stdout/stderr. Если не
                # отделить потоки, эти строки попадают в окно Astra/PowerShell.
                # Запускаем только прямой Code.exe и гасим его консольные потоки.
                subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                subprocess.Popen(command)
            self.logger.info("Запуск приложения: %s -> %s", app.name, command)
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

    def _resolve_open_command(self, app: AppConfig) -> list[str] | None:
        if app.name == "vscode" or app.process_name.lower() == "code.exe":
            return self._resolve_vscode_command()

        return [os.path.expandvars(part) for part in app.open_command]

    def _resolve_vscode_command(self) -> list[str] | None:
        """
        v0.9.4 hotfix. Раньше первым делом брался code.cmd/code, найденный
        через PATH (shutil.which), и запускался как ["cmd", "/c", "start", "",
        <путь>.cmd] — это открывало лишнее видимое cmd-окно и у некоторых
        пользователей падало с "Недостаточно ресурсов памяти для обработки
        этой команды".

        Теперь порядок другой:
        1. ASTRA_VSCODE_PATH из .env, если указан и существует.
        2. Известные прямые пути к Code.exe (LOCALAPPDATA/ProgramFiles/...).
        3. Если что-то из этого нашли — запускаем Code.exe напрямую, без cmd.
        4. Если нашли только code.cmd/code.bat через PATH — пробуем вычислить
           соседний Code.exe из структуры каталогов VS Code (bin/code.cmd ->
           ../Code.exe), а не запускать сам .cmd.
        5. Жёстко заданные пользовательские пути не хардкодятся: нестандартная
           установка должна находиться через PATH/bin/code.cmd или ASTRA_VSCODE_PATH.
        6. Если Code.exe нигде не нашёлся — возвращаем None. Вызывающий код
           уже честно говорит "Не нашёл Code.exe...", никакого cmd-окна.
        """
        direct_candidates: list[Path] = []

        env_path = os.getenv("ASTRA_VSCODE_PATH", "").strip()
        if env_path:
            direct_candidates.append(Path(os.path.expandvars(env_path)))

        local_app_data = os.getenv("LOCALAPPDATA", "")
        program_files = os.getenv("ProgramFiles", "")
        program_files_x86 = os.getenv("ProgramFiles(x86)", "")

        if local_app_data:
            direct_candidates.append(
                Path(local_app_data) / "Programs" / "Microsoft VS Code" / "Code.exe"
            )
            direct_candidates.append(
                Path(local_app_data) / "Programs" / "Microsoft VS Code Insiders" / "Code - Insiders.exe"
            )
        if program_files:
            direct_candidates.append(Path(program_files) / "Microsoft VS Code" / "Code.exe")
        if program_files_x86:
            direct_candidates.append(Path(program_files_x86) / "Microsoft VS Code" / "Code.exe")

        for candidate in direct_candidates:
            if candidate.suffix.lower() == ".exe" and candidate.exists():
                return [str(candidate)]

        # Ничего не нашли напрямую — смотрим, что даёт PATH, но не запускаем
        # .cmd/.bat как есть, а пробуем найти рядом настоящий Code.exe.
        derived_from_path: list[Path] = []
        for executable_name in ("code.cmd", "code.exe", "code.bat"):
            found = shutil.which(executable_name)
            if not found:
                continue
            found_path = Path(found)
            if found_path.suffix.lower() == ".exe":
                return [str(found_path)]
            # Типичная структура: <install_root>\bin\code.cmd и
            # <install_root>\Code.exe. Пробуем один и два уровня вверх.
            derived_from_path.append(found_path.parent / "Code.exe")
            derived_from_path.append(found_path.parent.parent / "Code.exe")

        for candidate in derived_from_path:
            if candidate.exists():
                return [str(candidate)]

        self.logger.warning(
            "VS Code executable was not found. Tried direct: %s; derived from PATH: %s",
            [str(item) for item in direct_candidates],
            [str(item) for item in derived_from_path],
        )
        return None

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
