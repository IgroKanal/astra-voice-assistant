"""Small typed plan executor. No shell or arbitrary callable registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import threading
import time
from typing import Any
import unicodedata
import uuid
import logging

from src.file_workspace import FileWorkspace, FileWorkspaceGroup


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
        "files.trash": ("path",),
        "web.search": ("query",),
        "web.read": ("url",),
        "web.answer": ("query",),
    }

    WRITE_SKILLS = {
        "files.copy": "copy",
        "files.move": "move",
        "files.rename": "move",
        "files.create_folder": "mkdir",
    }
    TRASH_SKILLS = frozenset({"files.trash"})

    def __init__(self, workspace: FileWorkspace | FileWorkspaceGroup | None = None, transactions=None,
                 audit=None, web_research=None, web_answer=None):
        transaction_workspace = getattr(transactions, "workspace", None) if transactions is not None else workspace
        if transactions is not None and workspace is not None and transaction_workspace is not workspace:
            raise PlanDenied("Разрешённая папка и файловые транзакции должны использовать один workspace")
        self.workspace = workspace
        self.transactions = transactions
        self.audit = audit
        self.web_research = web_research
        self.web_answer = web_answer

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
            if step.name in {"files.read_text", "files.create_folder", "files.trash"}:
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
            if require_workspace and step.name.startswith("files.") and self.workspace is None:
                raise PlanDenied("Сначала выбери разрешённую папку")
            if (require_workspace and step.name in {"web.search", "web.read"}
                    and self.web_research is None):
                raise PlanDenied("Сначала выдай отдельное разрешение на веб-поиск или чтение страниц")
            if require_workspace and step.name == "web.answer" and self.web_answer is None:
                raise PlanDenied("Сначала выдай веб-разрешение и выбери локальную модель для ответа")
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
                    required_capability=(
                        "выбранная папка + временное разрешение записи + отдельное подтверждение"
                        if step.name in self.WRITE_SKILLS else
                        "разрешённая папка + отдельный trash scope + preview и подтверждение"
                        if step.name in self.TRASH_SKILLS else
                        "истекающее разрешение на интернет-поиск"
                        if step.name == "web.search" else
                        "истекающее разрешение на чтение публичной HTTPS-страницы"
                        if step.name == "web.read" else
                        "истекающее веб-разрешение + явно выбранная локальная модель"
                        if step.name == "web.answer" else
                        "разрешённая папка пользователя"
                    ),
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
        trash_steps = {index for index, step in enumerate(steps) if step.name in self.TRASH_SKILLS}
        mutation_steps = write_steps | trash_steps
        if write_steps and (self.transactions is None or not self.transactions.writable or
                            transaction_previews is None):
            raise PlanDenied("Изменение файлов требует активного разрешения записи и точного preview")
        if trash_steps and self.transactions is None:
            raise PlanDenied("Перемещение в Корзину требует отдельного trash scope и точного preview")
        if mutation_steps and (
            transaction_previews is None or not mutation_steps.issubset(transaction_previews)
        ):
            raise PlanDenied("Каждое изменение требует собственного точного preview")
        if mutation_steps:
            used_tokens = set()
            earlier_writes: list[tuple[str, ...]] = []

            def path_parts(value: str) -> tuple[str, ...]:
                return tuple(part.casefold() for part in PurePosixPath(value.replace("\\", "/")).parts)

            def overlaps(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
                common = min(len(left), len(right))
                return left[:common] == right[:common]

            for index in sorted(mutation_steps):
                token = transaction_previews[index]
                if not isinstance(token, str) or token in used_tokens:
                    raise PlanDenied("Каждому изменению нужен отдельный токен предварительного просмотра")
                used_tokens.add(token)
                step = steps[index]
                expected_operation = self.WRITE_SKILLS.get(step.name, "trash")
                expected_source = (
                    step.arguments["path"] if step.name in self.TRASH_SKILLS
                    else step.arguments.get("source", "")
                )
                expected_destination = step.arguments.get("path", step.arguments.get("destination", ""))
                try:
                    preview = self.transactions.inspect_preview(token)
                except (OSError, ValueError) as exc:
                    raise PlanDenied(str(exc)) from exc
                if (
                    preview.operation != expected_operation
                    or preview.source != expected_source
                    or preview.destination != expected_destination
                ):
                    raise PlanDenied(
                        "Предварительный просмотр не совпадает с точной файловой операцией плана"
                    )
                current_reads = (
                    [path_parts(expected_source)]
                    if expected_operation in {"copy", "move", "trash"} else []
                )
                current_writes = [path_parts(expected_destination)]
                if expected_operation in {"move", "trash"}:
                    current_writes.append(path_parts(expected_source))
                if any(
                    overlaps(previous, current)
                    for previous in earlier_writes
                    for current in current_reads + current_writes
                ):
                    raise PlanDenied(
                        "Шаги плана пересекаются по файлам; выполни их отдельными подтверждёнными планами"
                    )
                earlier_writes.extend(current_writes)
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
                if step.name == "web.answer":
                    assert self.web_answer is not None
                    remaining = deadline - time.monotonic()
                    if remaining < 1:
                        raise PlanDenied("Истёк лимит времени плана")
                    value = self.web_answer.answer(
                        step.arguments["query"],
                        cancelled=cancel,
                        timeout_seconds=min(120, remaining),
                        deadline=deadline,
                    )
                elif step.name == "web.search":
                    assert self.web_research is not None
                    value = self.web_research.search(
                        step.arguments["query"],
                        is_cancelled=cancel.is_set if cancel is not None else None,
                        deadline=deadline,
                    )
                elif step.name == "web.read":
                    assert self.web_research is not None
                    value = self.web_research.fetch_page(
                        step.arguments["url"],
                        is_cancelled=cancel.is_set if cancel is not None else None,
                        deadline=deadline,
                    )
                elif step.name == "files.search":
                    assert self.workspace is not None
                    value = self.workspace.search(
                        step.arguments["query"],
                        is_cancelled=cancel.is_set if cancel is not None else None,
                        deadline=deadline,
                    )
                elif step.name == "files.read_text":
                    assert self.workspace is not None
                    value = self.workspace.read_text(
                        step.arguments["path"],
                        is_cancelled=cancel.is_set if cancel is not None else None,
                        deadline=deadline,
                    )
                elif step.name in self.TRASH_SKILLS:
                    assert self.transactions is not None and transaction_previews is not None
                    value = self.transactions.execute_trash(transaction_previews[index])
                else:
                    assert self.transactions is not None and transaction_previews is not None
                    value = self.transactions.execute(transaction_previews[index])
                results.append(SkillResult(step.name, True, value=value))
                self._record(step.name, "succeeded", correlation)
            except (OSError, ValueError) as exc:
                cancelled_or_expired = (
                    (cancel is not None and cancel.is_set())
                    or time.monotonic() >= deadline
                )
                error = (
                    "План отменён или истёк лимит времени"
                    if cancelled_or_expired
                    else str(exc)
                )
                results.append(SkillResult(step.name, False, error=error))
                self._record(
                    step.name,
                    "cancelled" if cancelled_or_expired else "failed",
                    correlation,
                )
                break
        return results
