"""Small typed read-only plan executor. No shell or arbitrary callable registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
import time
from typing import Any
import unicodedata
import uuid
import logging

from src.file_workspace import FileWorkspace


@dataclass(frozen=True)
class SkillCall:
    name: str
    arguments: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionPlan:
    steps: tuple[SkillCall, ...]


@dataclass(frozen=True)
class SkillResult:
    name: str
    ok: bool
    value: Any = None
    error: str = ""


@dataclass(frozen=True)
class PlanStepPreview:
    """A description of a validated step; creating it performs no I/O."""

    name: str
    arguments: dict[str, str]
    required_capability: str


@dataclass(frozen=True)
class PlanPreview:
    """A bounded, non-authorizing plan simulation."""

    steps: tuple[PlanStepPreview, ...]
    max_runtime_seconds: float
    execution_enabled: bool = False


class PlanDenied(ValueError):
    pass


class SkillExecutor:
    MAX_STEPS = 8
    SCHEMAS = {
        "files.search": ("query",),
        "files.read_text": ("path",),
        "files.copy": ("source", "destination"),
        "files.move": ("source", "destination"),
        "files.rename": ("source", "destination"),
        "files.create_folder": ("path",),
    }

    WRITE_SKILLS = {
        "files.copy": "copy",
        "files.move": "move",
        "files.rename": "move",
        "files.create_folder": "mkdir",
    }

    def __init__(self, workspace: FileWorkspace | None = None, transactions=None, audit=None):
        self.workspace = workspace
        self.transactions = transactions
        self.audit = audit

    def _record(self, name, outcome, correlation):
        if self.audit is not None:
            try:
                self.audit(name, outcome, correlation)
            except Exception:
                logging.getLogger(__name__).warning("Plan action audit unavailable")

    def validate(self, plan: ActionPlan) -> tuple[SkillCall, ...]:
        return self._validate(plan, require_workspace=True)

    def _validate(self, plan: ActionPlan, *, require_workspace: bool) -> tuple[SkillCall, ...]:
        if not isinstance(plan, ActionPlan) or not 1 <= len(plan.steps) <= self.MAX_STEPS:
            raise PlanDenied("План должен содержать от 1 до 8 шагов")
        # Copy arguments before validation: caller mutation cannot expand the plan.
        copied = []
        for step in plan.steps:
            if not isinstance(step, SkillCall) or step.name not in self.SCHEMAS:
                raise PlanDenied("Неизвестный навык")
            if not isinstance(step.arguments, dict):
                raise PlanDenied("Аргументы должны быть объектом")
            arguments = dict(step.arguments)
            if set(arguments) != set(self.SCHEMAS[step.name]):
                raise PlanDenied("Неожиданные или отсутствующие аргументы")
            if any(not isinstance(value, str) or len(value) > 4096 for value in arguments.values()):
                raise PlanDenied("Аргументы должны быть строками до 4096 символов")
            if any(
                ord(char) < 32 or 0x7F <= ord(char) <= 0x9F or
                unicodedata.bidirectional(char) in {"LRE", "RLE", "PDF", "LRO", "RLO", "LRI", "RLI", "FSI", "PDI"}
                for value in arguments.values() for char in value
            ):
                raise PlanDenied("Управляющие и двунаправленные символы в аргументах запрещены")
            paths = ()
            if step.name == "files.read_text" or step.name == "files.create_folder":
                paths = (arguments["path"],)
            elif step.name in self.WRITE_SKILLS and step.name != "files.create_folder":
                paths = (arguments["source"], arguments["destination"])
            for relative in paths:
                path = Path(relative)
                if (not relative.strip() or path.is_absolute() or path.drive or
                        ".." in path.parts or ":" in relative or relative.strip() in {".", ".."}):
                    raise PlanDenied("Путь доступен только относительно выбранной папки")
            if step.name == "files.rename":
                source, destination = Path(arguments["source"]), Path(arguments["destination"])
                if source.parent != destination.parent or source.name == destination.name:
                    raise PlanDenied("Переименование файла допускается только в той же папке и с новым именем")
            if require_workspace and self.workspace is None:
                raise PlanDenied("Сначала выбери разрешённую папку")
            copied.append(SkillCall(step.name, arguments))
        return tuple(copied)

    def simulate(self, plan: ActionPlan, budget_seconds: float = 15) -> PlanPreview:
        """Describe the bounded read-only plan without touching the workspace.

        A preview is informational only: it does not resolve paths, check grants,
        reserve resources, or authorize a later execution.
        """
        if not 0 < budget_seconds <= 60:
            raise PlanDenied("Недопустимый лимит времени")
        steps = self._validate(plan, require_workspace=False)
        return PlanPreview(
            steps=tuple(
                PlanStepPreview(
                    name=step.name,
                    arguments=dict(step.arguments),
                    required_capability=("выбранная папка + временное разрешение записи + отдельное подтверждение"
                                         if step.name in self.WRITE_SKILLS else "разрешённая папка пользователя"),
                )
                for step in steps
            ),
            max_runtime_seconds=float(budget_seconds),
        )

    def execute(self, plan: ActionPlan, cancel: threading.Event | None = None, budget_seconds: float = 15,
                transaction_previews: dict[int, str] | None = None) -> list[SkillResult]:
        if not 0 < budget_seconds <= 60:
            raise PlanDenied("Недопустимый лимит времени")
        steps = self.validate(plan)
        write_steps = {index for index, step in enumerate(steps) if step.name in self.WRITE_SKILLS}
        if write_steps and (self.transactions is None or not self.transactions.writable or
                            transaction_previews is None or not write_steps.issubset(transaction_previews)):
            raise PlanDenied("Изменение файлов требует активного разрешения записи и точного preview")
        deadline = time.monotonic() + budget_seconds
        results = []
        correlation = uuid.uuid4().hex
        for index, step in enumerate(steps):
            if (cancel is not None and cancel.is_set()) or time.monotonic() >= deadline:
                results.append(SkillResult(step.name, False, error="План отменён или истёк лимит времени"))
                self._record(step.name, "cancelled", correlation)
                break
            try:
                # Permissions are rechecked by FileWorkspace immediately before I/O.
                assert self.workspace is not None
                if step.name == "files.search":
                    value = self.workspace.search(step.arguments["query"])
                elif step.name == "files.read_text":
                    value = self.workspace.read_text(step.arguments["path"])
                else:
                    assert self.transactions is not None and transaction_previews is not None
                    value = self.transactions.execute(transaction_previews[index])
                results.append(SkillResult(step.name, True, value=value))
                self._record(step.name, "succeeded", correlation)
            except (OSError, ValueError) as exc:
                results.append(SkillResult(step.name, False, error=str(exc)))
                self._record(step.name, "failed", correlation)
                break
        return results
