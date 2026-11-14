from pathlib import Path
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import speech_recognition as sr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.audio_io import VoiceIO
from src.audio_io import ListenResult
from src.config_loader import Settings, load_settings
from src.ollama_client import OllamaClient
from src.ai_client import AIClient
from main import run_voice_mode


class LocalModelLatencyTests(unittest.TestCase):
    def test_stream_records_time_to_first_content_fragment(self):
        first = b'{"message":{"content":"first"},"done":false}\n'
        final = b'{"message":{"content":" second"},"done":true,"done_reason":"stop"}\n'

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                self.send_response(200)
                self.send_header("Content-Length", str(len(first) + len(final)))
                self.end_headers()
                self.wfile.write(first)
                self.wfile.flush()
                time.sleep(0.08)
                self.wfile.write(final)
                self.wfile.flush()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            client = OllamaClient(
                f"http://127.0.0.1:{server.server_address[1]}", timeout=3
            )
            result = client._streaming_request(
                "/api/chat", {"stream": True}, lambda: False
            )
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

        self.assertEqual(result["message"]["content"], "first second")
        self.assertGreaterEqual(result["timing"]["first_token_seconds"], 0)
        self.assertGreater(result["timing"]["elapsed_seconds"], result["timing"]["first_token_seconds"])

    def test_timing_callback_uses_stream_and_reports_only_durations(self):
        client = OllamaClient()
        callback = Mock()
        with patch.object(client, "models", return_value=["installed-model"]), patch.object(
            client, "_model_info", return_value={"capabilities": []}
        ), patch.object(
            client,
            "_streaming_request",
            return_value={
                "message": {"content": "ответ"},
                "done_reason": "stop",
                "timing": {"first_token_seconds": 0.2, "elapsed_seconds": 0.8},
            },
        ) as stream, patch.object(client, "_request", side_effect=AssertionError("timed answer must stream")):
            result = client.chat(
                "installed-model",
                "system",
                "private question",
                timing_callback=callback,
            )

        self.assertEqual(result, "ответ")
        self.assertTrue(stream.call_args.args[1]["stream"])
        callback.assert_called_once_with(
            {"first_token_seconds": 0.2, "elapsed_seconds": 0.8}
        )

    def test_timing_callback_failure_does_not_fail_local_answer(self):
        client = OllamaClient()
        callback = Mock(side_effect=RuntimeError("diagnostic unavailable"))
        with patch.object(client, "models", return_value=["installed-model"]), patch.object(
            client, "_model_info", return_value={"capabilities": []}
        ), patch.object(
            client,
            "_streaming_request",
            return_value={
                "message": {"content": "ответ"},
                "done_reason": "stop",
                "timing": {"first_token_seconds": 0.2, "elapsed_seconds": 0.8},
            },
        ):
            self.assertEqual(
                client.chat(
                    "installed-model",
                    "system",
                    "question",
                    timing_callback=callback,
                ),
                "ответ",
            )

    def test_invalid_timing_callback_is_rejected_before_inference(self):
        client = OllamaClient()
        with patch.object(client, "models", return_value=["installed-model"]), patch.object(
            client, "_model_info", side_effect=AssertionError("validate first")
        ):
            with self.assertRaises(ValueError):
                client.chat(
                    "installed-model",
                    "system",
                    "question",
                    timing_callback="not-callable",
                )

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

    def test_warmup_skips_model_that_is_not_installed(self):
        client = OllamaClient()
        with patch.object(client, "models", return_value=[]), patch.object(
            client, "_request", side_effect=AssertionError("must not load or download")
        ) as request:
            self.assertFalse(client.warmup("missing-model"))
        request.assert_not_called()

    def test_warmup_uses_bounded_local_chat_without_thinking(self):
        client = OllamaClient()
        with patch.object(client, "models", return_value=["qwen3:4b"]), patch.object(
            client,
            "_request",
            side_effect=[{"models": []}, {"done": True}],
        ) as request:
            self.assertTrue(client.warmup("qwen3:4b"))

        self.assertEqual(request.call_count, 2)
        path, payload = request.call_args.args
        self.assertEqual(path, "/api/chat")
        self.assertEqual(payload["model"], "qwen3:4b")
        self.assertFalse(payload["think"])
        self.assertEqual(payload["options"]["num_predict"], 1)
        self.assertEqual(payload["keep_alive"], "5m")

    def test_warmup_skips_model_that_is_already_loaded(self):
        client = OllamaClient()
        with patch.object(client, "models", return_value=["qwen3:4b"]), patch.object(
            client,
            "_request",
            return_value={"models": [{"name": "qwen3:4b"}]},
        ) as request:
            self.assertTrue(client.warmup("qwen3:4b"))
        request.assert_called_once_with("/api/ps")

    def test_local_http_requests_are_serialized(self):
        client = OllamaClient()
        state_lock = threading.Lock()
        release_reads = threading.Event()
        first_entered = threading.Event()
        second_lock_attempt = threading.Event()
        overlapping_requests = threading.Event()
        active_requests = 0
        maximum_active_requests = 0

        class ObservedLock:
            def __init__(self):
                self._lock = threading.Lock()
                self._attempts_lock = threading.Lock()
                self._attempts = 0

            def __enter__(self):
                with self._attempts_lock:
                    self._attempts += 1
                    if self._attempts > 1:
                        second_lock_attempt.set()
                self._lock.acquire()
                return self

            def __exit__(self, *_args):
                self._lock.release()

        client._request_lock = ObservedLock()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                nonlocal active_requests
                with state_lock:
                    active_requests -= 1

            def read(self, _limit):
                release_reads.wait(timeout=2)
                return b"{}"

        def open_request(*_args, **_kwargs):
            nonlocal active_requests, maximum_active_requests
            with state_lock:
                active_requests += 1
                maximum_active_requests = max(maximum_active_requests, active_requests)
                if active_requests > 1:
                    overlapping_requests.set()
                first_entered.set()
            return Response()

        results = []

        def request():
            results.append(client._request("/api/tags"))

        with patch.object(client.opener, "open", side_effect=open_request):
            threads = [threading.Thread(target=request) for _ in range(2)]
            for thread in threads:
                thread.start()
            self.assertTrue(first_entered.wait(timeout=2))
            self.assertTrue(second_lock_attempt.wait(timeout=2))
            self.assertFalse(overlapping_requests.is_set())
            release_reads.set()
            for thread in threads:
                thread.join(timeout=2)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(overlapping_requests.is_set())
        self.assertEqual(maximum_active_requests, 1)
        self.assertEqual(results, [{}, {}])

    def test_warmup_setting_can_be_disabled_in_environment(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"OLLAMA_WARMUP_ON_WAKE": "false"}
        ):
            settings = load_settings(Path(temp) / "missing.env")
        self.assertFalse(settings.ollama_warmup_on_wake)

    def test_voice_request_timeouts_can_be_configured(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                "STT_RECOGNITION_TIMEOUT_SECONDS": "9.5",
                "TTS_PLAYBACK_TIMEOUT_SECONDS": "31",
            },
        ):
            settings = load_settings(Path(temp) / "missing.env")

        self.assertEqual(settings.stt_recognition_timeout_seconds, 9.5)
        self.assertEqual(settings.tts_playback_timeout_seconds, 31.0)


class AIClientWarmupTests(unittest.TestCase):
    def test_local_model_warmup_runs_in_background(self):
        client = AIClient(
            Settings(
                llm_provider="ollama",
                llm_base_url="http://127.0.0.1:11434",
                llm_model="qwen3:4b",
            )
        )
        with patch.object(OllamaClient, "warmup", return_value=True) as warmup:
            thread = client.prewarm_local_async()
            self.assertIsNotNone(thread)
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        warmup.assert_called_once_with("qwen3:4b")

    def test_cloud_profile_does_not_start_local_warmup(self):
        client = AIClient(Settings(llm_provider="disabled", llm_enabled=False))
        self.assertIsNone(client.prewarm_local_async())


class WakeWarmupTests(unittest.TestCase):
    def test_only_verified_wake_starts_local_warmup(self):
        settings = Settings(
            voice_runtime_mode="wake_only",
            wake_only_mode=True,
            wake_response_enabled=False,
        )
        voice = Mock()
        voice.microphone = object()
        voice.listen_once.side_effect = [
            ListenResult(True, text="случайная фраза"),
            ListenResult(True, text="Астра"),
            ListenResult(True, text="стоп"),
        ]
        ai_client = Mock()

        with patch("main.VoiceIO", return_value=voice), patch(
            "main.emit_event", return_value=True
        ), patch("main.record_action"):
            run_voice_mode(
                settings,
                {},
                Mock(),
                Mock(),
                Mock(),
                Mock(),
                Mock(),
                Mock(),
                ai_client,
                logging.getLogger("wake-warmup-test"),
            )

        ai_client.prewarm_local_async.assert_called_once_with()

    def test_wake_warmup_can_be_disabled(self):
        settings = Settings(
            voice_runtime_mode="wake_only",
            wake_only_mode=True,
            wake_response_enabled=False,
            ollama_warmup_on_wake=False,
        )
        voice = Mock()
        voice.microphone = object()
        voice.listen_once.side_effect = [
            ListenResult(True, text="Астра"),
            ListenResult(True, text="стоп"),
        ]
        ai_client = Mock()

        with patch("main.VoiceIO", return_value=voice), patch(
            "main.emit_event", return_value=True
        ), patch("main.record_action"):
            run_voice_mode(
                settings,
                {},
                Mock(),
                Mock(),
                Mock(),
                Mock(),
                Mock(),
                Mock(),
                ai_client,
                logging.getLogger("wake-warmup-test"),
            )

        ai_client.prewarm_local_async.assert_not_called()


class TTSLatencyTests(unittest.TestCase):
    def _voice(self, cache_dir: Path) -> VoiceIO:
        voice = object.__new__(VoiceIO)
        voice.settings = Settings(
            tts_cache_enabled=True,
            tts_cache_dir=str(cache_dir),
            tts_edge_voice="ru-RU-SvetlanaNeural",
            tts_edge_fallback_voice="ru-RU-DmitryNeural",
            tts_playback_timeout_seconds=25.0,
        )
        voice.logger = logging.getLogger("astra-tts-latency-test")
        voice.edge_playback_command = "edge-playback"
        voice.edge_tts_command = "edge-tts"
        voice.tts_cache_dir = cache_dir
        voice._log_tts_timing = Mock()
        return voice

    def test_sapi_playback_logs_duration_without_speech_text(self):
        voice = object.__new__(VoiceIO)
        voice.settings = Settings(tts_enabled=True, tts_engine="sapi", tts_log_timing=True)
        voice.tts_engine = Mock()
        voice.tts_has_russian_voice = True
        voice.logger = Mock()
        voice._log_tts_timing = Mock()

        voice._speak_sapi("A short local response")

        voice.tts_engine.say.assert_called_once_with("A short local response")
        self.assertEqual(voice._log_tts_timing.call_args.args[1], "sapi")
        self.assertNotIn("A short local response", str(voice.logger.mock_calls))

    def test_dynamic_cache_miss_streams_directly_without_waiting_for_cache_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            voice = self._voice(Path(temp))
            voice._ensure_edge_cached_audio = Mock(side_effect=AssertionError("cache miss must not block on synthesis"))
            voice._play_cached_audio = Mock(return_value=False)
            voice._speak_edge_direct = Mock(return_value=True)

            voice._speak_edge("Новый ответ модели")

            voice._ensure_edge_cached_audio.assert_not_called()
            voice._play_cached_audio.assert_not_called()
            voice._speak_edge_direct.assert_called_once()
            direct_call = voice._speak_edge_direct.call_args
            self.assertEqual(direct_call.args, ("Новый ответ модели", "ru-RU-SvetlanaNeural"))
            self.assertAlmostEqual(direct_call.kwargs["timeout_seconds"], 25.0, places=6)
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

            calls = voice._speak_edge_direct.call_args_list
            self.assertEqual(
                [call.args for call in calls],
                [
                    ("Проверка резервного голоса", "ru-RU-SvetlanaNeural"),
                    ("Проверка резервного голоса", "ru-RU-DmitryNeural"),
                ],
            )
            for call in calls:
                self.assertAlmostEqual(call.kwargs["timeout_seconds"], 25.0, places=6)

    def test_fallback_voice_uses_only_remaining_total_playback_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            voice = self._voice(Path(temp))
            voice._edge_cache_path = Mock(return_value=Path(temp) / "missing.mp3")
            voice._play_cached_audio = Mock(return_value=False)
            voice._speak_edge_direct = Mock(side_effect=[False, True])

            # The primary call consumed ten seconds of the twenty-five-second budget.
            with patch("src.audio_io.time.monotonic", side_effect=[100, 100, 110]):
                voice._speak_edge("Ограниченный резерв")

            timeouts = [call.kwargs["timeout_seconds"] for call in voice._speak_edge_direct.call_args_list]
            self.assertEqual(len(timeouts), 2)
            self.assertAlmostEqual(timeouts[0], 25.0, places=6)
            self.assertAlmostEqual(timeouts[1], 15.0, places=6)

    def test_fallback_voice_is_skipped_after_total_playback_budget_expires(self):
        with tempfile.TemporaryDirectory() as temp:
            voice = self._voice(Path(temp))
            voice._edge_cache_path = Mock(return_value=Path(temp) / "missing.mp3")
            voice._play_cached_audio = Mock(return_value=False)
            voice._speak_edge_direct = Mock(return_value=False)

            with patch("src.audio_io.time.monotonic", side_effect=[100, 100, 130]):
                voice._speak_edge("Бюджет исчерпан")

            voice._speak_edge_direct.assert_called_once()

    def test_direct_edge_playback_passes_timeout_to_subprocess(self):
        with tempfile.TemporaryDirectory() as temp:
            voice = self._voice(Path(temp))
            with patch("src.audio_io.subprocess.run") as run:
                self.assertTrue(
                    voice._speak_edge_direct(
                        "Короткая фраза",
                        "ru-RU-SvetlanaNeural",
                        timeout_seconds=7.5,
                    )
                )

        self.assertEqual(run.call_args.kwargs["timeout"], 7.5)

    def test_direct_edge_playback_handles_timeout_without_logging_text(self):
        with tempfile.TemporaryDirectory() as temp:
            voice = self._voice(Path(temp))
            voice.logger = Mock()
            with patch(
                "src.audio_io.subprocess.run",
                side_effect=subprocess.TimeoutExpired("edge-playback", 7.5),
            ):
                self.assertFalse(
                    voice._speak_edge_direct(
                        "Секретная пользовательская фраза",
                        "ru-RU-SvetlanaNeural",
                        timeout_seconds=7.5,
                    )
                )

        warning_text = " ".join(str(call) for call in voice.logger.warning.call_args_list)
        self.assertNotIn("Секретная пользовательская фраза", warning_text)


class STTLatencyTests(unittest.TestCase):
    def _voice(self, settings: Settings) -> VoiceIO:
        voice = object.__new__(VoiceIO)
        voice.settings = settings
        voice.logger = Mock()
        voice.recognizer = Mock()
        voice.microphone = self._FakeMicrophone()
        voice.alternative_selector = None
        return voice

    class _FakeMicrophone:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    def test_recognizer_uses_a_finite_network_timeout(self):
        voice = self._voice(Settings(stt_recognition_timeout_seconds=8.0))
        voice._apply_recognizer_settings()
        self.assertEqual(voice.recognizer.operation_timeout, 8.0)

    def test_timing_log_splits_capture_and_recognition_without_transcript(self):
        voice = self._voice(
            Settings(
                stt_show_alternatives=False,
                stt_mistake_log_enabled=False,
            )
        )
        voice.recognizer.listen.return_value = object()
        voice.recognizer.recognize_google.return_value = "личная тестовая фраза"

        with patch("src.audio_io.emit_event", return_value=True):
            result = voice.listen_once(prompt="")

        self.assertTrue(result.ok)
        timing = next(
            call for call in voice.logger.info.call_args_list
            if str(call.args[0]).startswith("STT timing:")
        )
        self.assertIn("capture=%.2fs recognition=%.2fs total=%.2fs [%s]", timing.args[0])
        self.assertNotIn("личная тестовая фраза", repr(timing.args))

    def test_recognition_timeout_is_reported_with_split_timings(self):
        voice = self._voice(
            Settings(
                stt_show_alternatives=False,
                stt_mistake_log_enabled=False,
            )
        )
        voice.recognizer.listen.return_value = object()
        voice.recognizer.recognize_google.side_effect = sr.RequestError("offline")

        with patch("src.audio_io.emit_event", return_value=True):
            result = voice.listen_once(prompt="")

        self.assertFalse(result.ok)
        timing = next(
            call for call in voice.logger.info.call_args_list
            if str(call.args[0]).startswith("STT timing:")
        )
        self.assertEqual(timing.args[-1], "request_error")

    def test_capture_timeout_is_reported_without_starting_recognition(self):
        voice = self._voice(Settings(stt_mistake_log_enabled=False))
        voice.recognizer.listen.side_effect = sr.WaitTimeoutError()

        with patch("src.audio_io.emit_event", return_value=True):
            result = voice.listen_once(prompt="")

        self.assertFalse(result.ok)
        voice.recognizer.recognize_google.assert_not_called()
        timing = next(
            call for call in voice.logger.info.call_args_list
            if str(call.args[0]).startswith("STT timing:")
        )
        self.assertEqual(timing.args[-1], "timeout")
        self.assertEqual(timing.args[2], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
