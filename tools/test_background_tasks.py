from __future__ import annotations

import logging
from pathlib import Path
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import TurnState, handle_action, parsed_to_action, resolve_action
from src.background_tasks import BackgroundTaskError, BackgroundTaskManager
from src.ai_client import AIClient
from src.command_parser import (
    BACKGROUND_TASK_HELP_TARGET,
    CommandType,
    ParsedCommand,
    extract_command_after_wake,
    is_command_like_text,
    parse_command_text,
)
from src.config_loader import Settings
from src.ollama_client import OllamaRequestCancelled
from src.task_router import ActionType, AssistantAction


class BackgroundTaskTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            llm_provider="ollama",
            llm_base_url="http://127.0.0.1:11434",
            llm_model="installed-test-model",
            personal_memory_enabled=True,
            llm_router_enabled=True,
        )

    def wait_for_status(self, manager, task_id, expected, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = manager.get_result(task_id)
            if task is not None and task.status == expected:
                return task
            time.sleep(0.01)
        self.fail(f"task {task_id} did not reach {expected}")

    def test_question_runs_with_clean_local_context_and_notifies_without_content(self):
        questions = []
        settings_seen = []
        notifications = []

        class Client:
            def clear_dialogue(self):
                pass

            def ask(self, query, cancelled=None):
                questions.append(query)
                self_cancelled = cancelled is not None and cancelled()
                if self_cancelled:
                    raise OllamaRequestCancelled("cancelled")
                return SimpleNamespace(ok=True, message="Ответ из локальной модели.")

        def factory(settings, logger):
            settings_seen.append(settings)
            return Client()

        manager = BackgroundTaskManager(
            self.settings,
            logging.getLogger("test.background"),
            client_factory=factory,
            on_complete=lambda identity, status: notifications.append((identity, status)),
        )
        try:
            task_id = manager.start("  Объясни кратко, зачем нужен DNS.  ")
            task = self.wait_for_status(manager, task_id, "done")

            self.assertEqual(task.result, "Ответ из локальной модели.")
            self.assertEqual(questions, ["Объясни кратко, зачем нужен DNS."])
            self.assertEqual(len(settings_seen), 1)
            self.assertFalse(settings_seen[0].personal_memory_enabled)
            self.assertFalse(settings_seen[0].llm_router_enabled)
            self.assertLessEqual(settings_seen[0].llm_timeout_seconds, 30)
            self.assertEqual(notifications, [(task_id, "done")])
            snapshot = manager.list_tasks()[0]
            self.assertEqual(snapshot.status, "done")
            self.assertFalse(hasattr(snapshot, "query"))
        finally:
            manager.shutdown()

    def test_running_task_cancels_through_local_provider_signal(self):
        started = threading.Event()

        class BlockingClient:
            def clear_dialogue(self):
                pass

            def ask(self, _query, cancelled=None):
                started.set()
                while not cancelled():
                    time.sleep(0.005)
                raise OllamaRequestCancelled("cancelled")

        manager = BackgroundTaskManager(
            self.settings,
            client_factory=lambda _settings, _logger: BlockingClient(),
        )
        try:
            task_id = manager.start("Проверь выполнение и остановись по запросу.")
            self.assertTrue(started.wait(1.0))
            self.assertEqual(manager.cancel(task_id), "cancelling")
            task = self.wait_for_status(manager, task_id, "cancelled")
            self.assertEqual(task.result, "")
            self.assertEqual(task.error, "")
        finally:
            manager.shutdown()

    def test_task_has_a_finite_runtime_budget(self):
        started = threading.Event()

        class BudgetAwareClient:
            def clear_dialogue(self):
                pass

            def ask(self, _query, cancelled=None):
                started.set()
                while not cancelled():
                    time.sleep(0.005)
                raise OllamaRequestCancelled("timeout")

        manager = BackgroundTaskManager(
            self.settings,
            client_factory=lambda _settings, _logger: BudgetAwareClient(),
        )
        manager.MAX_RUNTIME_SECONDS = 0.03
        try:
            task_id = manager.start("Неограниченно долго отвечающий вопрос.")
            self.assertTrue(started.wait(1.0))
            task = self.wait_for_status(manager, task_id, "failed")
            self.assertEqual(task.error, "Превышен лимит времени фонового запроса.")
        finally:
            manager.shutdown()

    def test_ai_client_forwards_cancellation_only_to_local_ollama(self):
        with patch("src.ai_client.OpenAI", side_effect=AssertionError("cloud fallback forbidden")), patch(
            "src.ai_client.OllamaClient.chat",
            side_effect=OllamaRequestCancelled("cancelled"),
        ) as local_chat:
            result = AIClient(self.settings).ask(
                "Вопрос для фонового запроса.",
                cancelled=lambda: False,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.message, "Запрос отменён.")
        self.assertTrue(callable(local_chat.call_args.kwargs["cancelled"]))

    def test_queue_is_bounded_and_queued_task_can_be_cancelled(self):
        first_started = threading.Event()
        release_first = threading.Event()

        class OneBlockingClient:
            def clear_dialogue(self):
                pass

            def ask(self, query, cancelled=None):
                if query == "Первый вопрос с длинным ожиданием.":
                    first_started.set()
                    while not release_first.wait(0.005):
                        if cancelled():
                            raise OllamaRequestCancelled("cancelled")
                return SimpleNamespace(ok=True, message=f"Готово: {query}")

        manager = BackgroundTaskManager(
            self.settings,
            client_factory=lambda _settings, _logger: OneBlockingClient(),
        )
        try:
            first = manager.start("Первый вопрос с длинным ожиданием.")
            self.assertTrue(first_started.wait(1.0))
            second = manager.start("Второй вопрос в очереди.")
            third = manager.start("Третий вопрос в очереди.")
            with self.assertRaises(BackgroundTaskError):
                manager.start("Четвёртый вопрос сверх лимита.")

            self.assertEqual(manager.cancel(second), "cancelled")
            self.assertEqual(manager.get_result(second).status, "cancelled")
            release_first.set()
            self.wait_for_status(manager, first, "done")
            self.wait_for_status(manager, third, "done")
        finally:
            release_first.set()
            manager.shutdown()

    def test_cloud_provider_is_never_used_for_background_questions(self):
        cloud = Settings(llm_provider="compatible", llm_api_key="test-key")
        factory_calls = []
        manager = BackgroundTaskManager(
            cloud,
            client_factory=lambda *_args: factory_calls.append(True),
        )
        try:
            with self.assertRaises(BackgroundTaskError):
                manager.start("Ответь на этот вопрос в фоне.")
            self.assertEqual(factory_calls, [])
        finally:
            manager.shutdown()

    def test_query_and_list_limits_are_enforced(self):
        manager = BackgroundTaskManager(self.settings)
        try:
            for invalid in ("", "x", "строка\nс переносом", "q" * 1001, None):
                with self.subTest(invalid=repr(invalid)), self.assertRaises(BackgroundTaskError):
                    manager.start(invalid)
            for invalid_limit in (0, 21, True, 2.0):
                with self.subTest(limit=invalid_limit), self.assertRaises(ValueError):
                    manager.list_tasks(invalid_limit)
        finally:
            manager.shutdown()

    def test_voice_commands_are_typed_and_keep_wake_phrase_guard(self):
        raw = "Астра, спроси в фоне, как устроен DNS"
        parsed = extract_command_after_wake(raw, ["астра"])
        action = parsed_to_action(parsed)
        self.assertEqual(parsed.type, CommandType.BACKGROUND_ASK)
        self.assertEqual(action.type, ActionType.BACKGROUND_ASK)
        self.assertEqual(action.query, "как устроен DNS")

        cases = (
            ("покажи фоновые задачи", CommandType.BACKGROUND_LIST, ""),
            ("статус фонового запроса 12", CommandType.BACKGROUND_LIST, "12"),
            ("отмени фоновую задачу 12", CommandType.BACKGROUND_CANCEL, "12"),
            ("результат фонового запроса 12", CommandType.BACKGROUND_RESULT, "12"),
        )
        for command, expected_type, expected_target in cases:
            with self.subTest(command=command):
                parsed_command = parse_command_text(command)
                self.assertEqual(parsed_command.type, expected_type)
                self.assertEqual(parsed_command.target, expected_target)

        self.assertEqual(
            parse_command_text("спроси в фоне").target,
            BACKGROUND_TASK_HELP_TARGET,
        )
        self.assertTrue(is_command_like_text("спроси в фоне какой сегодня день"))

        class RouterMustNotRun:
            is_available = True

            def route_command(self, *_args):
                raise AssertionError("background actions must never come from the model router")

        guarded = resolve_action(
            raw_text="спроси в фоне какой сегодня день",
            parsed=ParsedCommand(CommandType.NO_WAKE),
            had_wake=False,
            ctx=SimpleNamespace(
                settings=Settings(
                    allow_commands_without_wake=False,
                    llm_router_enabled=True,
                    llm_enabled=True,
                ),
                logger=logging.getLogger("test.background.guard"),
                state=TurnState(),
                ai_client=RouterMustNotRun(),
                apps={},
                allow_conversation_without_wake=True,
            ),
        )
        self.assertEqual(guarded.type, ActionType.UNKNOWN)
        self.assertEqual(guarded.source, "wake_required_guard")

    def test_typed_actions_start_list_and_return_background_result(self):
        class ImmediateClient:
            def clear_dialogue(self):
                pass

            def ask(self, query, cancelled=None):
                return SimpleNamespace(ok=True, message=f"Локальный ответ: {query}")

        manager = BackgroundTaskManager(
            self.settings,
            client_factory=lambda _settings, _logger: ImmediateClient(),
        )
        responses = []
        context = SimpleNamespace(
            settings=self.settings,
            logger=logging.getLogger("test.background.dispatch"),
            respond=responses.append,
            background_tasks=manager,
            audit=None,
        )
        try:
            self.assertTrue(
                handle_action(
                    AssistantAction(
                        type=ActionType.BACKGROUND_ASK,
                        query="Проверь typed dispatch фонового вопроса.",
                        source="local",
                    ),
                    context,
                )
            )
            self.assertIn("Фоновый запрос 1 поставлен в очередь", responses[-1])
            self.wait_for_status(manager, 1, "done")

            self.assertTrue(
                handle_action(
                    AssistantAction(type=ActionType.BACKGROUND_LIST, source="local"),
                    context,
                )
            )
            self.assertIn("Фоновый запрос 1: готов", responses[-1])

            self.assertTrue(
                handle_action(
                    AssistantAction(
                        type=ActionType.BACKGROUND_RESULT,
                        target="1",
                        source="local",
                    ),
                    context,
                )
            )
            self.assertEqual(
                responses[-1],
                "Локальный ответ: Проверь typed dispatch фонового вопроса.",
            )
        finally:
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
