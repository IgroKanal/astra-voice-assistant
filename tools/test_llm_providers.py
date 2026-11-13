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
