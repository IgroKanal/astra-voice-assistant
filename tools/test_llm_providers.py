from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ai_client import AIClient
from src.config_loader import Settings
from src.llm_providers import (
    DisabledProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    create_provider,
)
from src.ollama_client import OllamaClient


class ProviderAdapterTests(unittest.TestCase):
    def test_cloud_errors_are_actionable_without_exposing_provider_payload(self):
        class FakeStatusError(Exception):
            def __init__(self, status):
                super().__init__("secret provider payload")
                self.status_code = status

        class FakeTimeoutError(Exception):
            pass

        class FakeConnectionError(Exception):
            pass

        settings = Settings(llm_provider="compatible", llm_api_key="test-key", llm_base_url="https://example.invalid/v1", llm_model="model", llm_fallback_model="")
        for status, expected in ((401, "ключ"), (402, "баланс"), (403, "доступ"), (404, "адрес"), (429, "лимиты"), (503, "недоступен"), (418, "418")):
            with self.subTest(status=status):
                remote = Mock()
                remote.chat.completions.create.side_effect = FakeStatusError(status)
                with patch("src.ai_client.OpenAI", return_value=remote), patch("src.ai_client.APIStatusError", FakeStatusError), patch("src.ai_client.APITimeoutError", FakeTimeoutError), patch("src.ai_client.APIConnectionError", FakeConnectionError), self.assertLogs("src.ai_client", level="WARNING") as logs:
                    result = AIClient(settings).ask("Вопрос")
                self.assertFalse(result.ok)
                self.assertIn(expected, result.message.lower())
                self.assertNotIn("secret provider payload", result.message)
                self.assertNotIn("secret provider payload", "\n".join(logs.output))

    def test_cloud_dialogue_is_opt_in_bounded_and_cleared(self):
        settings = Settings(llm_provider="compatible", llm_api_key="test-key", llm_base_url="https://example.invalid/v1", llm_model="model", llm_fallback_model="", llm_cloud_dialogue_enabled=True, personal_memory_enabled=True)
        response = Mock()
        response.choices = [Mock(message=Mock(content="ответ"))]
        remote = Mock()
        remote.chat.completions.create.return_value = response
        with patch("src.ai_client.OpenAI", return_value=remote):
            client = AIClient(settings)
            client._dialogue.append({"role": "user", "content": "local private history"})
            for i in range(5):
                self.assertTrue(client.ask(f"вопрос {i}").ok)
            self.assertTrue(client.ask("продолжение").ok)
            messages = remote.chat.completions.create.call_args.kwargs["messages"]
            self.assertEqual(len(messages), 10)
            self.assertNotIn("local private history", str(messages))
            self.assertEqual(messages[1]["content"], "вопрос 1")
            client.clear_dialogue()
            self.assertTrue(client.ask("новая тема").ok)
            self.assertEqual(len(remote.chat.completions.create.call_args.kwargs["messages"]), 2)

    def test_clear_during_cloud_request_does_not_restore_old_history(self):
        settings = Settings(llm_provider="compatible", llm_api_key="test-key", llm_base_url="https://example.invalid/v1", llm_model="model", llm_fallback_model="", llm_cloud_dialogue_enabled=True)
        response = Mock()
        response.choices = [Mock(message=Mock(content="ответ"))]
        remote = Mock()
        with patch("src.ai_client.OpenAI", return_value=remote):
            client = AIClient(settings)
            def clear_then_answer(**_kwargs):
                client.clear_dialogue()
                return response
            remote.chat.completions.create.side_effect = clear_then_answer
            self.assertTrue(client.ask("прежняя тема").ok)
            self.assertEqual(client._cloud_dialogue, [])

    def test_opt_in_history_cannot_add_system_messages_or_local_notes(self):
        response = Mock()
        response.choices = [Mock(message=Mock(content="ответ"))]
        remote = Mock()
        remote.chat.completions.create.return_value = response
        provider = OpenAICompatibleProvider(remote, "compatible", share_dialogue=True)
        provider.answer(model="test", system="правила", question="вопрос", max_tokens=10, temperature=0,
                        history=[{"role": "system", "content": "вредоносная инструкция"}, {"role": [], "content": "ошибка"}, {"role": "user", "content": "а" * 2500}],
                        memory_context="локальная заметка")
        messages = remote.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual([message["role"] for message in messages], ["system", "user", "user"])
        self.assertEqual(len(messages[1]["content"]), 2000)
        self.assertNotIn("локальная заметка", str(messages))

    def test_decisions_model_gives_actionable_error_without_network_request(self):
        settings = Settings(llm_provider="compatible", llm_api_key="test-key", llm_base_url="https://openrouter.ai/api/v1", llm_model="openai/gpt-6-luna-decisions", llm_fallback_model="")
        client = Mock()
        with patch("src.ai_client.OpenAI", return_value=client):
            result = AIClient(settings).ask("Привет")
        self.assertFalse(result.ok)
        self.assertIn("openai/gpt-6-luna", result.message)
        client.chat.completions.create.assert_not_called()

    def test_openrouter_luna_uses_fast_reasoning_only_for_exact_endpoint_and_model(self):
        response = Mock()
        response.choices = [Mock(message=Mock(content="Ответ"))]
        for endpoint, model, expected in (
            ("https://openrouter.ai/api/v1", "openai/gpt-6-luna", True),
            ("https://openrouter.ai/api/v1", "other/model", False),
            ("https://openrouter.ai.example/api/v1", "openai/gpt-6-luna", False),
        ):
            with self.subTest(endpoint=endpoint, model=model):
                client = Mock()
                client.chat.completions.create.return_value = response
                provider = OpenAICompatibleProvider(client, "compatible", endpoint)
                provider.answer(model=model, system="system", question="hello", max_tokens=30, temperature=0.2)
                arguments = client.chat.completions.create.call_args.kwargs
                self.assertEqual(arguments.get("extra_body"), {"reasoning": {"effort": "none"}} if expected else None)

    def test_local_provider_keeps_history_memory_and_inference_local(self):
        ollama = Mock()
        ollama.chat.return_value = "Локальный ответ"
        provider = OllamaProvider(ollama)
        history = [{"role": "user", "content": "предыдущий вопрос"}]

        answer = provider.answer(
            model="installed-model",
            system="system",
            question="вопрос",
            max_tokens=80,
            temperature=0.3,
            history=history,
            memory_context='[{"text":"local note"}]',
            think=False,
        )

        self.assertEqual(answer, "Локальный ответ")
        ollama.chat.assert_called_once_with(
            "installed-model",
            "system",
            "вопрос",
            max_tokens=80,
            history=history,
            memory_context='[{"text":"local note"}]',
            temperature=0.3,
            think=False,
        )
        self.assertTrue(provider.is_local)

    def test_local_classifier_uses_only_typed_single_turn_request(self):
        ollama = Mock()
        ollama.chat.return_value = '{"action":"unknown"}'
        provider = OllamaProvider(ollama)

        raw = provider.classify(
            model="installed-model",
            system="strict JSON rules",
            request="открой браузер",
            response_format=True,
        )

        self.assertEqual(raw, '{"action":"unknown"}')
        ollama.chat.assert_called_once_with(
            "installed-model",
            "strict JSON rules",
            "открой браузер",
            max_tokens=500,
            temperature=0,
            think=False,
        )

    def test_compatible_provider_does_not_forward_local_history_or_memory(self):
        response = Mock()
        response.choices = [Mock(message=Mock(content="Ответ"))]
        client = Mock()
        client.chat.completions.create.return_value = response
        provider = OpenAICompatibleProvider(client, "compatible")

        answer = provider.answer(
            model="remote-model",
            system="system",
            question="вопрос",
            max_tokens=90,
            temperature=0.5,
            history=[{"role": "user", "content": "private history"}],
            memory_context="private notes",
        )

        self.assertEqual(answer, "Ответ")
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["messages"],
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "вопрос"},
            ],
        )
        self.assertTrue(provider.available)
        self.assertFalse(provider.is_local)

    def test_compatible_provider_streams_answer_chunks_and_reports_first_token(self):
        events = [
            Mock(choices=[Mock(delta=Mock(content="Первая фраза."))]),
            Mock(choices=[Mock(delta=Mock(content=" Вторая часть."))]),
            Mock(choices=[]),
        ]
        client = Mock()
        client.chat.completions.create.return_value = iter(events)
        provider = OpenAICompatibleProvider(client, "compatible")
        chunks = []
        timings = []

        answer = provider.answer(
            model="remote-model",
            system="system",
            question="вопрос",
            max_tokens=90,
            temperature=0.5,
            history=[{"role": "user", "content": "private history"}],
            memory_context="private notes",
            on_chunk=chunks.append,
            timing_callback=timings.append,
        )

        self.assertEqual(answer, "Первая фраза. Вторая часть.")
        self.assertEqual(chunks, ["Первая фраза.", " Вторая часть."])
        self.assertEqual(len(timings), 1)
        self.assertGreaterEqual(timings[0]["first_token_seconds"], 0)
        self.assertGreaterEqual(timings[0]["elapsed_seconds"], timings[0]["first_token_seconds"])
        call = client.chat.completions.create.call_args.kwargs
        self.assertTrue(call["stream"])
        self.assertNotIn("private history", str(call["messages"]))
        self.assertNotIn("private notes", str(call["messages"]))

    def test_compatible_stream_callback_failure_does_not_break_completion(self):
        client = Mock()
        client.chat.completions.create.return_value = iter([
            Mock(choices=[Mock(delta=Mock(content="Ответ завершён."))]),
        ])
        provider = OpenAICompatibleProvider(client, "compatible")

        def broken_callback(_part):
            raise RuntimeError("playback callback failed")

        answer = provider.answer(
            model="remote-model",
            system="system",
            question="вопрос",
            max_tokens=30,
            temperature=0.2,
            on_chunk=broken_callback,
        )

        self.assertEqual(answer, "Ответ завершён.")

    def test_compatible_stream_rejects_truncation_at_token_limit(self):
        client = Mock()
        client.chat.completions.create.return_value = iter([
            Mock(choices=[Mock(delta=Mock(content="Неполный ответ"), finish_reason="length")]),
        ])
        provider = OpenAICompatibleProvider(client, "compatible")

        with self.assertRaisesRegex(ValueError, "исчерпала лимит"):
            provider.answer(
                model="remote-model",
                system="system",
                question="вопрос",
                max_tokens=10,
                temperature=0.2,
                on_chunk=lambda _part: None,
            )

    def test_compatible_stream_checks_cancellation_and_closes_stream(self):
        cancelled = [False]

        class CloseableStream:
            def __init__(self):
                self.events = [
                    Mock(choices=[Mock(delta=Mock(content="Первый токен"))]),
                    Mock(choices=[Mock(delta=Mock(content=" лишний токен"))]),
                ]
                self.read_count = 0
                self.closed = False

            def __iter__(self):
                return self

            def __next__(self):
                self.read_count += 1
                if not self.events:
                    raise StopIteration
                return self.events.pop(0)

            def close(self):
                self.closed = True

        stream = CloseableStream()
        client = Mock()
        client.chat.completions.create.return_value = stream
        provider = OpenAICompatibleProvider(client, "compatible")

        def on_chunk(_part):
            cancelled[0] = True

        with self.assertRaisesRegex(RuntimeError, "отменён"):
            provider.answer(
                model="remote-model",
                system="system",
                question="вопрос",
                max_tokens=30,
                temperature=0.2,
                on_chunk=on_chunk,
                cancelled=lambda: cancelled[0],
            )

        self.assertTrue(stream.closed)
        self.assertEqual(stream.read_count, 1)

    def test_compatible_classifier_supports_optional_json_mode(self):
        response = Mock()
        response.choices = [Mock(message=Mock(content='{"action":"get_time"}'))]
        client = Mock()
        client.chat.completions.create.return_value = response
        provider = OpenAICompatibleProvider(client, "compatible")

        raw = provider.classify(
            model="remote-model",
            system="rules",
            request="который час",
            response_format=True,
        )

        self.assertEqual(raw, '{"action":"get_time"}')
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["response_format"],
            {"type": "json_object"},
        )

    def test_factory_prefers_explicit_ollama_and_never_builds_remote_client(self):
        settings = Settings(
            llm_provider="ollama",
            llm_enabled=True,
            llm_api_key="ignored-cloud-key",
            llm_base_url="http://127.0.0.1:11434",
        )
        local = Mock(spec=OllamaClient)
        local_factory = Mock(return_value=local)
        remote_factory = Mock(side_effect=AssertionError("No remote client allowed"))

        provider = create_provider(
            settings,
            openai_factory=remote_factory,
            ollama_factory=local_factory,
            can_create_compatible=True,
        )

        self.assertIsInstance(provider, OllamaProvider)
        self.assertIs(provider.client, local)
        local_factory.assert_called_once_with(settings.llm_base_url, settings.llm_timeout_seconds)
        remote_factory.assert_not_called()

    def test_factory_disables_provider_when_llm_is_off(self):
        settings = Settings(llm_enabled=False, llm_provider="ollama")
        with patch.object(OllamaClient, "__init__", side_effect=AssertionError("Disabled provider must not connect")):
            provider = create_provider(
                settings,
                openai_factory=Mock(side_effect=AssertionError("Disabled provider must not connect")),
                can_create_compatible=False,
            )

        self.assertIsInstance(provider, DisabledProvider)
        self.assertFalse(provider.available)

    def test_ai_client_routes_through_the_compatible_adapter(self):
        response = Mock()
        response.choices = [Mock(message=Mock(content="Проверочный ответ"))]
        fake_client = Mock()
        fake_client.chat.completions.create.return_value = response
        settings = Settings(
            llm_provider="compatible",
            llm_api_key="test-key",
            llm_base_url="https://example.invalid/v1",
            llm_model="test-model",
            llm_fallback_model="",
        )

        with patch("src.ai_client.OpenAI", return_value=fake_client):
            client = AIClient(settings)
            result = client.ask("проверка")

        self.assertIsInstance(client.provider, OpenAICompatibleProvider)
        self.assertEqual(result.message, "Проверочный ответ")

    def test_ai_client_streams_cloud_chunks_and_logs_first_token_without_content(self):
        fake_client = Mock()
        fake_client.chat.completions.create.return_value = iter([
            Mock(choices=[Mock(delta=Mock(content="Потоковый ответ."))]),
        ])
        settings = Settings(
            llm_provider="compatible",
            llm_api_key="test-key",
            llm_base_url="https://example.invalid/v1",
            llm_model="test-model",
            llm_fallback_model="",
        )
        chunks = []

        with patch("src.ai_client.OpenAI", return_value=fake_client), self.assertLogs(
            "src.ai_client", level="INFO"
        ) as captured:
            client = AIClient(settings)
            result = client.ask("личный вопрос", on_text_chunk=chunks.append)

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "Потоковый ответ.")
        self.assertEqual(chunks, ["Потоковый ответ."])
        self.assertTrue(fake_client.chat.completions.create.call_args.kwargs["stream"])
        log_text = "\n".join(captured.output)
        self.assertIn("LLM first-token timing: provider=compatible", log_text)
        self.assertNotIn("личный вопрос", log_text)
        self.assertNotIn("Потоковый ответ", log_text)

    def test_cloud_stream_failure_after_output_does_not_mix_in_fallback_model(self):
        secret = "private-stream-error-content"

        def broken_stream():
            yield Mock(choices=[Mock(delta=Mock(content="Начало ответа. "))])
            raise RuntimeError(secret)

        fake_client = Mock()
        fake_client.chat.completions.create.side_effect = [
            broken_stream(),
            iter([Mock(choices=[Mock(delta=Mock(content="Другой ответ."))])]),
        ]
        settings = Settings(
            llm_provider="compatible", llm_api_key="test-key",
            llm_base_url="https://example.invalid/v1",
            llm_model="primary", llm_fallback_model="fallback",
        )
        chunks = []

        with patch("src.ai_client.OpenAI", return_value=fake_client), self.assertLogs(
            "src.ai_client", level="INFO"
        ) as captured:
            result = AIClient(settings).ask("вопрос", on_text_chunk=chunks.append)

        self.assertFalse(result.ok)
        self.assertEqual(chunks, ["Начало ответа. "])
        self.assertEqual(fake_client.chat.completions.create.call_count, 1)
        logs = "\n".join(captured.output)
        self.assertIn("fallback skipped", logs)
        self.assertNotIn(secret, logs)

    def test_cloud_stream_failure_before_output_still_uses_fallback_model(self):
        def broken_stream():
            raise RuntimeError("stream disconnected")
            yield  # pragma: no cover

        fake_client = Mock()
        fake_client.chat.completions.create.side_effect = [
            broken_stream(),
            iter([Mock(choices=[Mock(delta=Mock(content="Резервный ответ."))])]),
        ]
        settings = Settings(
            llm_provider="compatible", llm_api_key="test-key",
            llm_base_url="https://example.invalid/v1",
            llm_model="primary", llm_fallback_model="fallback",
        )
        chunks = []

        with patch("src.ai_client.OpenAI", return_value=fake_client), self.assertLogs(
            "src.ai_client", level="INFO"
        ):
            result = AIClient(settings).ask("вопрос", on_text_chunk=chunks.append)

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "Резервный ответ.")
        self.assertEqual(chunks, ["Резервный ответ."])
        self.assertEqual(fake_client.chat.completions.create.call_count, 2)

    def test_cloud_answer_does_not_log_exception_payload(self):
        secret = "private-question-and-provider-token"
        fake_client = Mock()
        fake_client.chat.completions.create.side_effect = RuntimeError(secret)
        settings = Settings(
            llm_provider="compatible", llm_api_key="test-key",
            llm_base_url="https://example.invalid/v1",
            llm_model="primary", llm_fallback_model="",
        )

        with patch("src.ai_client.OpenAI", return_value=fake_client), self.assertLogs(
            "src.ai_client", level="INFO"
        ) as captured:
            result = AIClient(settings).ask("вопрос")

        self.assertFalse(result.ok)
        logs = "\n".join(captured.output)
        self.assertIn("type=RuntimeError", logs)
        self.assertNotIn(secret, logs)

    def test_cloud_router_does_not_log_exception_payload(self):
        secret = "private-command-and-provider-token"
        settings = Settings(
            llm_provider="compatible", llm_api_key="test-key",
            llm_base_url="https://example.invalid/v1",
            llm_model="primary", llm_fallback_model="",
        )
        for exceptions in (
            [RuntimeError(secret)],
            [TypeError(secret), RuntimeError(secret)],
        ):
            with self.subTest(attempts=len(exceptions)):
                fake_client = Mock()
                fake_client.chat.completions.create.side_effect = exceptions
                with patch("src.ai_client.OpenAI", return_value=fake_client), self.assertLogs(
                    "src.ai_client", level="INFO"
                ) as captured:
                    result = AIClient(settings).route_command("команда", {})
                self.assertFalse(result.ok)
                logs = "\n".join(captured.output)
                self.assertIn("type=RuntimeError", logs)
                self.assertNotIn(secret, logs)

    def test_compatible_router_retries_without_json_mode_when_endpoint_rejects_it(self):
        response = Mock()
        response.choices = [
            Mock(message=Mock(content='{"action":"get_time","target":"","query":"","url":"","confidence":0.93,"reason":"Вопрос о времени"}'))
        ]
        fake_client = Mock()
        fake_client.chat.completions.create.side_effect = [TypeError("response_format unsupported"), response]
        settings = Settings(
            llm_provider="compatible",
            llm_api_key="test-key",
            llm_base_url="https://example.invalid/v1",
            llm_model="test-model",
            llm_fallback_model="",
        )

        with patch("src.ai_client.OpenAI", return_value=fake_client):
            result = AIClient(settings).route_command("который час", {})

        self.assertTrue(result.ok)
        self.assertEqual(result.action.type.value, "get_time")
        calls = fake_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs["response_format"], {"type": "json_object"})
        self.assertNotIn("response_format", calls[1].kwargs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
