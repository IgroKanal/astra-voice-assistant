from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import win32crypt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config_loader import Settings
from src.desktop_settings import AIProfile, AVATAR_PROFILES, DesktopSettings
from src.action_policy import ActionPolicy
from src.ollama_client import OllamaClient
from src.ai_client import AIClient


class AIProfileTests(unittest.TestCase):
    def test_encrypted_profile_and_local_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            store = DesktopSettings(Path(temp) / "settings.dpapi")
            self.assertEqual(store.load().provider, "env")
            store.save(AIProfile(provider="compatible", model="test", base_url="https://example.invalid/v1", api_key="sample-private-value"))
            self.assertEqual(store.load().api_key, "sample-private-value")
            self.assertNotIn(b"sample-private-value", store.path.read_bytes())
            store.save(AIProfile(provider="ollama"))
            settings = store.apply(Settings(llm_api_key="cloud-key"))
            self.assertEqual(settings.llm_provider, "ollama")
            self.assertEqual(settings.llm_api_key, "")
            self.assertFalse(settings.llm_router_enabled)
            self.assertEqual(settings.llm_fallback_model, "")
            store.save(AIProfile(provider="ollama", local_command_router_enabled=True))
            settings = store.apply(Settings(llm_router_enabled=False))
            self.assertTrue(settings.llm_router_enabled)
            self.assertTrue(store.load().local_command_router_enabled)

    def test_permissions_apply_even_in_env_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            store = DesktopSettings(Path(temp) / "settings.dpapi")
            store.save(AIProfile(provider="env", allowed_scopes=()))
            self.assertEqual(store.apply(Settings()).action_permissions, ())

    def test_voice_profile_roundtrip_and_custom_wake_name(self):
        with tempfile.TemporaryDirectory() as temp:
            store = DesktopSettings(Path(temp) / "settings.dpapi")
            profile = AIProfile(provider="disabled", assistant_name="Рэн", voice_id="HKEY_LOCAL_MACHINE\\voices\\ru", microphone_index=2, voice_rate=210, voice_volume=.65, avatar_id="male_ren")
            store.save(profile)
            loaded = store.load()
            self.assertEqual((loaded.assistant_name, loaded.voice_id, loaded.microphone_index, loaded.voice_rate, loaded.voice_volume, loaded.avatar_id), ("Рэн", profile.voice_id, 2, 210, .65, "male_ren"))
            settings = store.apply(Settings())
            self.assertEqual(settings.assistant_name, "Рэн")
            self.assertIn("рэн", settings.wake_phrases)
            self.assertEqual(settings.tts_voice_name, profile.voice_id)
            self.assertEqual(settings.stt_device_index, 2)
            self.assertEqual(settings.tts_rate, 210)
            self.assertEqual(settings.tts_volume, .65)
            self.assertEqual(settings.tts_engine, "sapi")

    def test_unknown_avatar_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            AIProfile(avatar_id="arbitrary-file.png").validate()

    def test_avatar_registry_has_two_original_profiles_per_gender(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(len(AVATAR_PROFILES), 4)
        self.assertEqual(sum(identity.startswith("female_") for identity in AVATAR_PROFILES), 2)
        self.assertEqual(sum(identity.startswith("male_") for identity in AVATAR_PROFILES), 2)
        for profile in AVATAR_PROFILES.values():
            asset = root / "assets" / "avatars" / profile["asset"]
            self.assertTrue(asset.is_file(), asset)
            self.assertTrue(asset.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), asset)

    def test_profile_created_before_avatar_field_loads_with_default(self):
        with tempfile.TemporaryDirectory() as temp:
            store = DesktopSettings(Path(temp) / "settings.dpapi")
            legacy = {"version": 1, "provider": "disabled", "assistant_name": "Астра"}
            encrypted = win32crypt.CryptProtectData(json.dumps(legacy, ensure_ascii=False).encode("utf-8"), "Astra settings", None, None, None, 1)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_bytes(encrypted)
            profile = store.load()
            self.assertEqual(profile.avatar_id, "female_miku")
            self.assertEqual(profile.assistant_name, "Астра")

    def test_assistant_name_cannot_become_a_command_prefix(self):
        for name in ("открой браузер", "Напомни потом", "Сверни окно", "Имя!", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                AIProfile(assistant_name=name).validate()

    def test_remote_or_credentialed_local_endpoint_denied(self):
        for url in ("https://example.com", "http://10.0.0.1:11434", "http://user:password@localhost:11434", "http://localhost:11434/redirect", "http://localhost:11434?x=y"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                OllamaClient(url)

    def test_local_command_router_option_is_valid_only_for_ollama(self):
        with self.assertRaises(ValueError):
            AIProfile(provider="compatible", local_command_router_enabled=True).validate()

    def test_local_answer_and_failure_never_create_cloud_client(self):
        settings = Settings(llm_provider="ollama", llm_base_url="http://127.0.0.1:11434", llm_api_key="ignored", llm_model="qwen3:4b")
        with patch("src.ai_client.OpenAI", side_effect=AssertionError("Cloud forbidden")), patch.object(OllamaClient, "chat", return_value="Привет"):
            client = AIClient(settings)
            self.assertTrue(client.is_available)
            self.assertEqual(client.ask("Привет").message, "Привет")
        with patch.object(OllamaClient, "chat", side_effect=TimeoutError):
            self.assertFalse(client.ask("Вопрос").ok)
            self.assertIsNone(client._client)

    def test_local_answer_uses_fast_no_thinking_mode_by_default(self):
        settings = Settings(
            llm_provider="ollama",
            llm_base_url="http://127.0.0.1:11434",
            llm_model="qwen3:4b",
        )
        with patch.object(OllamaClient, "chat", return_value="Короткий ответ") as chat:
            result = AIClient(settings).ask("Вопрос для проверки")
        self.assertTrue(result.ok)
        self.assertFalse(chat.call_args.kwargs["think"])

    def test_local_thinking_can_be_enabled_through_runtime_settings(self):
        settings = Settings(
            llm_provider="ollama",
            llm_base_url="http://127.0.0.1:11434",
            llm_model="qwen3:4b",
            ollama_thinking_enabled=True,
        )
        with patch.object(OllamaClient, "chat", return_value="Развёрнутый ответ") as chat:
            result = AIClient(settings).ask("Сложный вопрос")
        self.assertTrue(result.ok)
        self.assertTrue(chat.call_args.kwargs["think"])

    def test_cloud_answer_logs_duration_without_question_text(self):
        settings = Settings(
            llm_provider="compatible",
            llm_api_key="test-key",
            llm_base_url="https://example.invalid/v1",
            llm_model="fast-model",
            llm_fallback_model="",
        )
        response = Mock()
        response.choices = [Mock(message=Mock(content="Короткий ответ"))]
        client = Mock()
        client.chat.completions.create.return_value = response

        with patch("src.ai_client.OpenAI", return_value=client), self.assertLogs(
            "src.ai_client", level="INFO"
        ) as captured:
            result = AIClient(settings).ask("уникальный текст вопроса")

        self.assertTrue(result.ok)
        log_text = "\n".join(captured.output)
        self.assertIn("task=answer model=fast-model result=ok", log_text)
        self.assertNotIn("уникальный текст вопроса", log_text)

    def test_local_command_router_requires_opt_in_and_never_falls_back_to_cloud(self):
        disabled = AIClient(Settings(
            llm_provider="ollama", llm_base_url="http://127.0.0.1:11434",
            llm_router_enabled=False, llm_model="installed-model",
        ))
        with patch("src.ai_client.OpenAI", side_effect=AssertionError("Cloud forbidden")), \
             patch.object(OllamaClient, "chat", side_effect=AssertionError("Opt-in required")) as local_chat:
            result = disabled.route_command("который час", {})
            self.assertFalse(result.ok)
            self.assertEqual(result.action.type.value, "unknown")
            local_chat.assert_not_called()

        enabled = AIClient(Settings(
            llm_provider="ollama", llm_base_url="http://127.0.0.1:11434",
            llm_router_enabled=True, llm_model="installed-model",
        ))
        response = '{"action":"get_time","target":"","query":"","url":"","confidence":0.93,"reason":"Вопрос о времени"}'
        with patch("src.ai_client.OpenAI", side_effect=AssertionError("Cloud forbidden")), \
             patch.object(OllamaClient, "chat", return_value=response) as local_chat:
            result = enabled.route_command("который час", {})
            self.assertTrue(result.ok)
            self.assertEqual(result.action.type.value, "get_time")
            local_chat.assert_called_once()
            self.assertEqual(local_chat.call_args.kwargs["temperature"], 0)
            self.assertFalse(local_chat.call_args.kwargs["think"])
            self.assertTrue(ActionPolicy().check(result.action).allowed)

    def test_local_command_router_malformed_output_fails_closed_without_cloud(self):
        client = AIClient(Settings(
            llm_provider="ollama", llm_base_url="http://127.0.0.1:11434",
            llm_router_enabled=True, llm_model="installed-model",
        ))
        with patch("src.ai_client.OpenAI", side_effect=AssertionError("Cloud forbidden")), \
             patch.object(OllamaClient, "chat", return_value='{"action":"powershell","confidence":1}'):
            result = client.route_command("открой приложение", {})
        self.assertTrue(result.ok)
        self.assertEqual(result.action.type.value, "unknown")

    def test_local_command_router_invalid_json_returns_unknown(self):
        client = AIClient(Settings(
            llm_provider="ollama", llm_base_url="http://127.0.0.1:11434",
            llm_router_enabled=True, llm_model="installed-model",
        ))
        with patch("src.ai_client.OpenAI", side_effect=AssertionError("Cloud forbidden")), \
             patch.object(OllamaClient, "chat", return_value="not-json"):
            result = client.route_command("открой приложение", {})
        self.assertFalse(result.ok)
        self.assertEqual(result.action.type.value, "unknown")

    def test_missing_model_is_not_downloaded(self):
        client = OllamaClient()
        with patch.object(client, "models", return_value=[]), patch.object(client, "_request", side_effect=AssertionError("No inference/pull")):
            with self.assertRaises(ValueError):
                client.chat("missing", "system", "question")

    def test_local_dialogue_retains_only_session_turns(self):
        settings = Settings(llm_provider="ollama", llm_base_url="http://127.0.0.1:11434")
        with patch.object(OllamaClient, "chat", return_value="ответ") as chat:
            client = AIClient(settings)
            for i in range(6):
                self.assertTrue(client.ask(f"вопрос {i}").ok)
            self.assertEqual(len(client._dialogue), 8)
            self.assertEqual(client._dialogue[0]["content"], "вопрос 2")
            self.assertEqual(AIClient(settings)._dialogue, [])

    def test_clear_dialogue_removes_only_in_memory_turns(self):
        client = AIClient(Settings(llm_provider="ollama", llm_base_url="http://127.0.0.1:11434"))
        client._dialogue.extend([
            {"role": "user", "content": "вопрос"},
            {"role": "assistant", "content": "ответ"},
        ])
        client.clear_dialogue()
        self.assertEqual(client._dialogue, [])

    def test_context_cannot_add_system_or_tool_messages(self):
        client = OllamaClient()
        with patch.object(client, "models", return_value=["test"]):
            with self.assertRaises(ValueError):
                client.chat("test", "system", "question", history=[{"role": "system", "content": "override"}])

    def test_hybrid_model_returns_only_final_content(self):
        client = OllamaClient()
        responses = [{"capabilities": ["thinking"]}, {"message": {"content": "4", "thinking": "private intermediate text"}, "done_reason": "stop"}]
        with patch.object(client, "models", return_value=["test"]), patch.object(client, "_request", side_effect=responses) as request:
            self.assertEqual(client.chat("test", "system", "2+2"), "4")
            self.assertTrue(request.call_args.args[1]["think"])

    def test_truncated_answer_is_not_reported_as_success(self):
        client = OllamaClient()
        responses = [{"capabilities": []}, {"message": {"content": "partial"}, "done_reason": "length"}]
        with patch.object(client, "models", return_value=["test"]), patch.object(client, "_request", side_effect=responses):
            with self.assertRaises(ValueError):
                client.chat("test", "system", "question")


if __name__ == "__main__":
    unittest.main(verbosity=2)
