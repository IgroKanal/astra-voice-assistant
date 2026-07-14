from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.command_parser import normalize_text


ALLOWED_ROUTINE_ACTIONS = {
    "open_app",
    "open_url",
    "open_folder",
}

PROHIBITED_APP_TARGETS = {
    "cmd",
    "cmd exe",
    "powershell",
    "powershell exe",
    "pwsh",
    "pwsh exe",
    "windows terminal",
    "windowsterminal",
    "windowsterminal exe",
    "wt",
    "wt exe",
    "terminal",
    "командная строка",
    "командную строку",
}


class RoutineConfigError(ValueError):
    """Raised when the safe routines configuration is invalid."""


@dataclass(frozen=True)
class RoutineStep:
    action: str
    target: str


@dataclass(frozen=True)
class RoutineDefinition:
    name: str
    aliases: tuple[str, ...]
    response: str
    steps: tuple[RoutineStep, ...]


class RoutineController:
    """Loads exact-match routines composed only of allowlisted Astra actions."""

    def __init__(
        self,
        config_path: str | Path,
        enabled: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.enabled = enabled
        self.config_path = Path(config_path)
        self._aliases: dict[str, RoutineDefinition] = {}

        if enabled:
            self._load()

    def resolve(self, target: str) -> RoutineDefinition | None:
        if not self.enabled:
            return None
        return self._aliases.get(normalize_text(target))

    def routine_count(self) -> int:
        return len({routine.name for routine in self._aliases.values()})

    def _load(self) -> None:
        if not self.config_path.is_file():
            raise RoutineConfigError(f"Файл routines не найден: {self.config_path}")

        try:
            raw_data: Any = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RoutineConfigError(
                f"Некорректный JSON в {self.config_path}: {exc}"
            ) from exc

        raw_routines = raw_data.get("routines") if isinstance(raw_data, dict) else None
        if not isinstance(raw_routines, dict) or not raw_routines:
            raise RoutineConfigError("config/routines.json должен содержать объект routines.")

        for name, raw_routine in raw_routines.items():
            routine = self._parse_routine(name, raw_routine)
            for alias in routine.aliases:
                normalized = normalize_text(alias)
                if not normalized:
                    raise RoutineConfigError(f"Пустой alias в routine {name!r}.")
                if normalized in self._aliases:
                    raise RoutineConfigError(f"Повторяющийся routine alias: {alias!r}")
                self._aliases[normalized] = routine

        self.logger.info(
            "Safe routines loaded: routines=%s aliases=%s path=%s",
            self.routine_count(),
            len(self._aliases),
            self.config_path,
        )

    def _parse_routine(self, name: str, raw_routine: Any) -> RoutineDefinition:
        if not isinstance(name, str) or not name.strip():
            raise RoutineConfigError("Имя routine должно быть непустой строкой.")
        if not isinstance(raw_routine, dict):
            raise RoutineConfigError(f"Routine {name!r} должна быть объектом.")

        unknown_fields = set(raw_routine) - {"aliases", "response", "steps"}
        if unknown_fields:
            raise RoutineConfigError(
                f"Routine {name!r}: запрещённые поля {sorted(unknown_fields)}."
            )

        aliases = raw_routine.get("aliases")
        if not isinstance(aliases, list) or not aliases:
            raise RoutineConfigError(f"Routine {name!r}: aliases должен быть списком.")
        if not all(isinstance(item, str) and item.strip() for item in aliases):
            raise RoutineConfigError(f"Routine {name!r}: все aliases должны быть строками.")

        raw_steps = raw_routine.get("steps")
        if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 8:
            raise RoutineConfigError(f"Routine {name!r}: требуется от 1 до 8 steps.")

        steps: list[RoutineStep] = []
        for index, raw_step in enumerate(raw_steps, start=1):
            steps.append(self._parse_step(name, index, raw_step))

        response = raw_routine.get("response", "Режим готов.")
        if not isinstance(response, str) or not response.strip():
            raise RoutineConfigError(f"Routine {name!r}: response должна быть строкой.")
        response = response.strip()
        if len(response) > 120:
            raise RoutineConfigError(f"Routine {name!r}: response длиннее 120 символов.")

        all_aliases = [name, *aliases]
        return RoutineDefinition(
            name=name.strip(),
            aliases=tuple(all_aliases),
            response=response,
            steps=tuple(steps),
        )

    def _parse_step(self, routine_name: str, index: int, raw_step: Any) -> RoutineStep:
        if not isinstance(raw_step, dict):
            raise RoutineConfigError(
                f"Routine {routine_name!r}, step {index}: step должна быть объектом."
            )

        unknown_fields = set(raw_step) - {"action", "target"}
        if unknown_fields:
            raise RoutineConfigError(
                f"Routine {routine_name!r}, step {index}: запрещённые поля "
                f"{sorted(unknown_fields)}."
            )

        action = raw_step.get("action")
        target = raw_step.get("target")
        if action not in ALLOWED_ROUTINE_ACTIONS:
            raise RoutineConfigError(
                f"Routine {routine_name!r}, step {index}: действие {action!r} запрещено."
            )
        if not isinstance(target, str) or not target.strip():
            raise RoutineConfigError(
                f"Routine {routine_name!r}, step {index}: target должен быть строкой."
            )

        clean_target = target.strip()
        normalized_target = normalize_text(clean_target)
        if action == "open_app" and normalized_target in PROHIBITED_APP_TARGETS:
            raise RoutineConfigError(
                f"Routine {routine_name!r}, step {index}: shell target запрещён."
            )
        if action == "open_url" and ":" in clean_target:
            scheme = clean_target.split(":", 1)[0].lower()
            if scheme not in {"http", "https"}:
                raise RoutineConfigError(
                    f"Routine {routine_name!r}, step {index}: URL scheme запрещён."
                )

        return RoutineStep(action=action, target=clean_target)
