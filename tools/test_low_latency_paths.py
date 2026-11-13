from pathlib import Path
import logging
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.audio_io import VoiceIO
from src.config_loader import Settings
from src.ollama_client import OllamaClient


class LocalModelLatencyTests(unittest.TestCase):
    def test_installed_model_and_metadata_are_reused_between_turns(self):
        client = OllamaClient()
        requests = []
        payloads = []

        def request(path, payload=None):
            requests.append(path)
            payloads.append(payload)
            if path == "/api/tags":
                return {"models": [{"name": "qwen3:4b"}]}
            if path == "/api/show":
                return {"capabilities": ["thinking"]}
            return {"message": {"content": "готово"}, "done_reason": "stop"}

        with patch.object(client, "_request", side_effect=request):
            self.assertEqual(client.chat("qwen3:4b", "system", "one"), "готово")
            self.assertEqual(client.chat("qwen3:4b", "system", "two"), "готово")

        self.assertEqual(requests, ["/api/tags", "/api/show", "/api/chat", "/api/chat"])
        self.assertTrue(payloads[2]["think"])
        self.assertTrue(payloads[3]["think"])

    def test_explicit_think_false_is_sent_even_for_thinking_models(self):
        client = OllamaClient()
        requests = []

        def request(path, payload=None):
            requests.append((path, payload))
            if path == "/api/tags":
                return {"models": [{"name": "qwen3:4b"}]}
            if path == "/api/show":
                return {"capabilities": ["thinking"]}
            return {"message": {"content": "быстро"}, "done_reason": "stop"}

        with patch.object(client, "_request", side_effect=request):
            result = client.chat("qwen3:4b", "system", "question", think=False)

        self.assertEqual(result, "быстро")
        chat_payload = next(payload for path, payload in requests if path == "/api/chat")
        self.assertFalse(chat_payload["think"])

    def test_non_boolean_think_mode_is_rejected(self):
        client = OllamaClient()
        with patch.object(client, "models", return_value=["qwen3:4b"]):
            with self.assertRaises(ValueError):
                client.chat("qwen3:4b", "system", "question", think="high")


class TTSLatencyTests(unittest.TestCase):
    def _voice(self, cache_dir: Path) -> VoiceIO:
        voice = object.__new__(VoiceIO)
        voice.settings = Settings(
            tts_cache_enabled=True,
            tts_cache_dir=str(cache_dir),
            tts_edge_voice="ru-RU-SvetlanaNeural",
            tts_edge_fallback_voice="ru-RU-DmitryNeural",
        )
        voice.logger = logging.getLogger("astra-tts-latency-test")
        voice.edge_playback_command = "edge-playback"
        voice.edge_tts_command = "edge-tts"
        voice.tts_cache_dir = cache_dir
        voice._log_tts_timing = Mock()
        return voice

    def test_dynamic_cache_miss_streams_directly_without_waiting_for_cache_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            voice = self._voice(Path(temp))
            voice._ensure_edge_cached_audio = Mock(side_effect=AssertionError("cache miss must not block on synthesis"))
            voice._play_cached_audio = Mock(return_value=False)
            voice._speak_edge_direct = Mock(return_value=True)

            voice._speak_edge("Новый ответ модели")

            voice._ensure_edge_cached_audio.assert_not_called()
            voice._play_cached_audio.assert_not_called()
            voice._speak_edge_direct.assert_called_once_with("Новый ответ модели", "ru-RU-SvetlanaNeural")
            voice._log_tts_timing.assert_called_once()

    def test_existing_cache_is_used_without_network_synthesis(self):
        with tempfile.TemporaryDirectory() as temp:
            voice = self._voice(Path(temp))
            cached = Path(temp) / "existing.mp3"
            cached.write_bytes(b"cached audio")
            voice._edge_cache_path = Mock(return_value=cached)
            voice._play_cached_audio = Mock(return_value=True)
            voice._speak_edge_direct = Mock(side_effect=AssertionError("cache hit should play locally"))
            voice._ensure_edge_cached_audio = Mock(side_effect=AssertionError("cache hit must not synthesize"))

            voice._speak_edge("Повторяемая фраза")

            voice._play_cached_audio.assert_called_once_with(cached)
            voice._speak_edge_direct.assert_not_called()
            voice._ensure_edge_cached_audio.assert_not_called()

    def test_primary_voice_failure_uses_configured_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            voice = self._voice(Path(temp))
            voice._edge_cache_path = Mock(return_value=Path(temp) / "missing.mp3")
            voice._play_cached_audio = Mock(return_value=False)
            voice._speak_edge_direct = Mock(side_effect=[False, True])

            voice._speak_edge("Проверка резервного голоса")

            self.assertEqual(
                voice._speak_edge_direct.call_args_list,
                [
                    unittest.mock.call("Проверка резервного голоса", "ru-RU-SvetlanaNeural"),
                    unittest.mock.call("Проверка резервного голоса", "ru-RU-DmitryNeural"),
                ],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
