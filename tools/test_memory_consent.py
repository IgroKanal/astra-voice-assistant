from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.ai_client import AIClient
from src.config_loader import Settings
from src.desktop_settings import AIProfile
from src.personal_memory import PersonalMemory
from src.ollama_client import OllamaClient


class MemoryConsentTests(unittest.TestCase):
    def test_profile_requires_explicit_local_consent(self):
        self.assertFalse(AIProfile().memory_enabled)
        for provider in ("env", "compatible", "gemini", "disabled"):
            with self.assertRaises(ValueError):
                AIProfile(provider=provider, memory_enabled=True).validate()

    def test_local_context_refreshes_and_forget_clears_session(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.sqlite"
            memory = PersonalMemory(path)
            identity = memory.add("Любимый цвет", "Мой любимый цвет — зелёный")
            settings = Settings(llm_provider="ollama", llm_base_url="http://127.0.0.1:11434", personal_memory_enabled=True, personal_memory_path=str(path))
            observed = []
            def answer(*args, **kwargs):
                observed.append((kwargs["memory_context"], len(kwargs["history"])))
                return "итог"
            with patch.object(OllamaClient, "chat", side_effect=answer):
                client = AIClient(settings)
                self.assertTrue(client.ask("Какой мой любимый цвет?").ok)
                self.assertIn("зелёный", observed[-1][0])
                client.ask("Ещё вопрос")
                self.assertEqual(observed[-1][1], 2)
                memory.forget(identity)
                client.ask("Какой мой любимый цвет?")
                self.assertEqual(observed[-1], ("", 0))

    def test_no_consent_does_not_open_memory(self):
        settings = Settings(llm_provider="ollama", llm_base_url="http://127.0.0.1:11434")
        with patch.object(PersonalMemory, "context", side_effect=AssertionError("Not granted")), patch.object(OllamaClient, "chat", return_value="ответ") as chat:
            self.assertTrue(AIClient(settings).ask("Вопрос").ok)
            self.assertEqual(chat.call_args.kwargs["memory_context"], "")

    def test_cloud_branch_never_receives_personal_notes(self):
        completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ответ"))])
        create = unittest.mock.Mock(return_value=completion)
        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        settings = Settings(llm_api_key="dummy", personal_memory_enabled=True)
        with patch("src.ai_client.OpenAI", return_value=fake), patch.object(PersonalMemory, "context", side_effect=AssertionError("Cloud cannot read notes")):
            self.assertTrue(AIClient(settings).ask("Вопрос").ok)
            self.assertEqual(len(create.call_args.kwargs["messages"]), 2)

    def test_context_is_bounded_valid_json(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            memory = PersonalMemory(Path(temp) / "memory.sqlite")
            memory.add("Заметка", '\n"' * 7000)
            context = memory.context("Заметка")
            self.assertLessEqual(len(context), 2000)
            self.assertIsInstance(json.loads(context), list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
