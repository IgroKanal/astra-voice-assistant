"""Bounded, process-local background questions for the local Ollama provider."""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, replace
import logging
import threading
import time
import unicodedata
from typing import Callable

from src.config_loader import Settings


class BackgroundTaskError(ValueError):
    """A background question cannot be accepted under the current limits."""


@dataclass(frozen=True)
class BackgroundTaskSnapshot:
    id: int
    status: str
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class BackgroundTaskResult:
    id: int
    status: str
    result: str = ""
    error: str = ""


@dataclass
class _BackgroundTask:
    id: int
    query: str
    status: str
    created_at: float
    updated_at: float
    cancelled: threading.Event
    result: str = ""
    error: str = ""


class BackgroundTaskManager:
    """Runs short, read-only questions with one local inference worker.

    Task text and results stay in memory for this process only. No question,
    response, or provider error is written to logs or persistent storage.
    Background work is restricted to the explicitly selected local Ollama
    provider so cancellation cannot silently fall back to a cloud service.
    """

    MAX_QUERY_CHARS = 1000
    MAX_RESULT_CHARS = 4000
    MAX_STORED_TASKS = 20
    MAX_OUTSTANDING_TASKS = 3
    MAX_RUNTIME_SECONDS = 180.0
    MAX_PROVIDER_TIMEOUT_SECONDS = 30
    ACTIVE_STATUSES = frozenset({"queued", "running", "cancelling"})
    TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})

    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger | None = None,
        *,
        client_factory: Callable[[Settings, logging.Logger], object] | None = None,
        on_complete: Callable[[int, str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._logger = logger or logging.getLogger(__name__)
        self._client_factory = client_factory or self._make_ai_client
        self._on_complete = on_complete
        self._client = None
        self._condition = threading.Condition(threading.RLock())
        self._tasks: OrderedDict[int, _BackgroundTask] = OrderedDict()
        self._queue: deque[int] = deque()
        self._next_id = 1
        self._worker: threading.Thread | None = None
        self._closed = False

    @staticmethod
    def _make_ai_client(settings: Settings, logger: logging.Logger):
        from src.ai_client import AIClient

        return AIClient(settings=settings, logger=logger)

    @staticmethod
    def _validate_query(query: object) -> str:
        if not isinstance(query, str):
            raise BackgroundTaskError("Нужен текст вопроса для фоновой задачи.")
        clean = query.strip()
        if not 2 <= len(clean) <= BackgroundTaskManager.MAX_QUERY_CHARS:
            raise BackgroundTaskError(
                "Вопрос для фонового запроса должен содержать от 2 до 1000 символов."
            )
        if any(
            not char.isprintable()
            or unicodedata.category(char) in {"Cf", "Cs"}
            for char in clean
        ):
            raise BackgroundTaskError("Вопрос содержит недопустимые символы.")
        return clean

    def _provider_is_allowed(self) -> bool:
        return bool(
            self._settings.llm_enabled
            and self._settings.llm_provider == "ollama"
        )

    def start(self, query: str) -> int:
        clean_query = self._validate_query(query)
        if not self._provider_is_allowed():
            raise BackgroundTaskError(
                "Фоновые вопросы требуют явно выбранного локального Ollama. "
                "Облачный провайдер для этой команды не используется."
            )

        with self._condition:
            if self._closed:
                raise BackgroundTaskError("Фоновые задачи уже остановлены.")
            outstanding = sum(
                task.status in self.ACTIVE_STATUSES for task in self._tasks.values()
            )
            if outstanding >= self.MAX_OUTSTANDING_TASKS:
                raise BackgroundTaskError(
                    "Уже запущены три фоновых запроса. Дождись завершения или отмени один."
                )

            task_id = self._next_id
            self._next_id += 1
            now = time.time()
            task = _BackgroundTask(
                id=task_id,
                query=clean_query,
                status="queued",
                created_at=now,
                updated_at=now,
                cancelled=threading.Event(),
            )
            self._tasks[task_id] = task
            self._queue.append(task_id)
            self._trim_locked()
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._run,
                    name="AstraBackgroundQuestions",
                    daemon=True,
                )
                try:
                    self._worker.start()
                except Exception:
                    self._worker = None
                    self._queue.remove(task_id)
                    self._tasks.pop(task_id, None)
                    raise BackgroundTaskError(
                        "Не удалось запустить фоновый запрос."
                    ) from None
            self._condition.notify_all()
            return task_id

    def _trim_locked(self) -> None:
        while len(self._tasks) > self.MAX_STORED_TASKS:
            old_id = next(
                (
                    identity
                    for identity, task in self._tasks.items()
                    if task.status in self.TERMINAL_STATUSES
                ),
                None,
            )
            if old_id is None:
                return
            del self._tasks[old_id]

    def _get_client(self):
        if self._client is None:
            # Each background question has a clean context and cannot read
            # personal notes or use the command router.
            safe_settings = replace(
                self._settings,
                personal_memory_enabled=False,
                llm_router_enabled=False,
                llm_timeout_seconds=max(
                    1,
                    min(
                        int(self._settings.llm_timeout_seconds),
                        self.MAX_PROVIDER_TIMEOUT_SECONDS,
                    ),
                ),
            )
            self._client = self._client_factory(safe_settings, self._logger)
        return self._client

    def _run(self) -> None:
        while True:
            notice_status = ""
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                task_id = self._queue.popleft()
                task = self._tasks.get(task_id)
                if task is None or task.status != "queued":
                    continue
                task.status = "running"
                task.updated_at = time.time()

            result = None
            timed_out = threading.Event()
            deadline = time.monotonic() + self.MAX_RUNTIME_SECONDS

            def cancelled_or_timed_out() -> bool:
                if task.cancelled.is_set():
                    return True
                if time.monotonic() >= deadline:
                    timed_out.set()
                    return True
                return False

            try:
                client = self._get_client()
                client.clear_dialogue()
                if cancelled_or_timed_out():
                    raise _TaskCancelled()
                result = client.ask(task.query, cancelled=cancelled_or_timed_out)
                if cancelled_or_timed_out():
                    result = None
            except Exception:
                # Provider exceptions may contain endpoints or request details.
                # Keep only a generic outcome in the task history.
                result = None
            finally:
                try:
                    if self._client is not None:
                        self._client.clear_dialogue()
                except Exception:
                    pass

            with self._condition:
                current = self._tasks.get(task_id)
                if current is None:
                    continue
                current.updated_at = time.time()
                if current.cancelled.is_set() or self._closed:
                    current.status = "cancelled"
                    current.result = ""
                    current.error = ""
                elif timed_out.is_set():
                    current.status = "failed"
                    current.result = ""
                    current.error = "Превышен лимит времени фонового запроса."
                elif result is not None and getattr(result, "ok", False):
                    message = getattr(result, "message", "")
                    if isinstance(message, str) and message.strip():
                        current.status = "done"
                        current.result = " ".join(message.split())[: self.MAX_RESULT_CHARS]
                        current.error = ""
                    else:
                        current.status = "failed"
                        current.error = "Локальная модель вернула пустой ответ."
                else:
                    current.status = "failed"
                    current.result = ""
                    current.error = "Локальная модель не смогла ответить. Проверь Ollama и выбранную модель."
                if current.status in {"done", "failed"}:
                    notice_status = current.status
                self._condition.notify_all()
            if notice_status and self._on_complete is not None:
                try:
                    self._on_complete(task_id, notice_status)
                except Exception:
                    self._logger.warning(
                        "Background task notification failed: task_id=%s status=%s",
                        task_id,
                        notice_status,
                    )

    @staticmethod
    def _snapshot(task: _BackgroundTask) -> BackgroundTaskSnapshot:
        return BackgroundTaskSnapshot(
            id=task.id,
            status=task.status,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    def list_tasks(self, limit: int = 5) -> tuple[BackgroundTaskSnapshot, ...]:
        if type(limit) is not int or not 1 <= limit <= self.MAX_STORED_TASKS:
            raise ValueError("Лимит списка фоновых задач вне допустимого диапазона.")
        with self._condition:
            return tuple(
                self._snapshot(task)
                for task in reversed(tuple(self._tasks.values()))
            )[:limit]

    def get_result(self, task_id: int) -> BackgroundTaskResult | None:
        if type(task_id) is not int or task_id < 1:
            return None
        with self._condition:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return BackgroundTaskResult(
                id=task.id,
                status=task.status,
                result=task.result,
                error=task.error,
            )

    def cancel(self, task_id: int) -> str:
        if type(task_id) is not int or task_id < 1:
            return "not_found"
        with self._condition:
            task = self._tasks.get(task_id)
            if task is None:
                return "not_found"
            if task.status == "queued":
                task.cancelled.set()
                task.status = "cancelled"
                task.updated_at = time.time()
                try:
                    self._queue.remove(task_id)
                except ValueError:
                    pass
                return "cancelled"
            if task.status == "running":
                task.cancelled.set()
                task.status = "cancelling"
                task.updated_at = time.time()
                return "cancelling"
            return task.status

    def wait_for_change(self, timeout: float = 0.1) -> None:
        """Small bounded wait helper for lifecycle tests and local callers."""
        bounded = max(0.0, min(float(timeout), 1.0))
        with self._condition:
            self._condition.wait(timeout=bounded)

    def shutdown(self, timeout: float = 1.0) -> None:
        bounded = max(0.0, min(float(timeout), 3.0))
        with self._condition:
            self._closed = True
            for task in self._tasks.values():
                if task.status == "queued":
                    task.cancelled.set()
                    task.status = "cancelled"
                    task.updated_at = time.time()
                elif task.status == "running":
                    task.cancelled.set()
                    task.status = "cancelling"
                    task.updated_at = time.time()
            self._queue.clear()
            self._condition.notify_all()
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=bounded)


class _TaskCancelled(Exception):
    """Internal marker for cancellation before provider dispatch."""
