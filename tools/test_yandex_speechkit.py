from __future__ import annotations

import base64
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.audio_io import VoiceIO
from src.config_loader import Settings, load_settings
from src.desktop_settings import AIProfile, DesktopSettings
from src.yandex_speechkit import (
    API_URL,
    AUDIO_SAMPLE_RATE_HZ,
    RUSSIAN_VOICES,
    YandexSpeechKitCancelled,
    YandexSpeechKitClient,
    YandexSpeechKitError,
    resolve_russian_voice,
    split_text_for_requests,
)


class YandexSpeechKitVoiceTests(unittest.TestCase):
    def test_four_default_avatar_voices_are_distinct_and_match_gender(self):
        expected = {
            "female_miku": ("jane", "female"),
            "female_saya": ("masha", "female"),
            "male_ren": ("filipp", "male"),
            "male_kai": ("zahar", "male"),
        }
        actual = {
            avatar: (
                resolve_russian_voice(avatar_id=avatar, gender=gender).voice_id,
                resolve_russian_voice(avatar_id=avatar, gender=gender).gender,
            )
            for avatar, (_, gender) in expected.items()
        }
        self.assertEqual(actual, expected)
        self.assertEqual(len({voice for voice, _ in actual.values()}), 4)
        self.assertEqual(
            {voice.gender for voice in RUSSIAN_VOICES.values()}, {"female", "male"}
        )

    def test_explicit_voice_must_match_character_gender(self):
        self.assertEqual(
            resolve_russian_voice(gender="male", requested_voice="yandex:zahar").voice_id,
            "zahar",
        )
        with self.assertRaisesRegex(ValueError, "не совпадает"):
            resolve_russian_voice(gender="male", requested_voice="jane")
        with self.assertRaisesRegex(ValueError, "каталог"):
            resolve_russian_voice(gender="female", requested_voice="unknown")

    def test_long_text_is_split_without_exceeding_provider_limit(self):
        text = "Первое предложение. " + "длинная фраза " * 28 + "Готово!"
        chunks = split_text_for_requests(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= 250 for chunk in chunks))
        self.assertEqual(" ".join(chunks).replace("  ", " "), text)
        self.assertEqual(split_text_for_requests("  "), [])

    def test_request_uses_selected_voice_and_streams_pcm_chunks(self):
        expected_chunks = [b"\x00\x01\x02\x03", b"\x04\x05"]
        body = b"".join(
            json.dumps(
                {"audioChunk": {"data": base64.b64encode(chunk).decode("ascii")}}
            ).encode("utf-8")
            + b"\n"
            for chunk in expected_chunks
        )
        opener = Mock(return_value=io.BytesIO(body))
        received = []
        client = YandexSpeechKitClient(
            "secret-key",
            folder_id="folder-123",
            opener=opener,
        )

        total = client.stream_synthesize(
            "Проверка голоса.", voice="masha", on_audio_chunk=received.append
        )

        request = opener.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, API_URL)
        self.assertEqual(request.get_header("Authorization"), "Api-key secret-key")
        self.assertEqual(request.get_header("X-folder-id"), "folder-123")
        self.assertEqual(payload["text"], "Проверка голоса.")
        self.assertEqual(payload["hints"], [{"voice": "masha"}, {"role": "good"}])
        self.assertEqual(
            payload["outputAudioSpec"],
            {"rawAudio": {"audioEncoding": "LINEAR16_PCM", "sampleRateHertz": str(AUDIO_SAMPLE_RATE_HZ)}},
        )
        self.assertEqual(received, expected_chunks)
        self.assertEqual(total, sum(map(len, expected_chunks)))
        self.assertEqual(opener.call_args.kwargs["timeout"], 25.0)

    def test_response_reader_handles_split_utf8_and_concatenated_messages(self):
        audio_data = base64.b64encode(b"\x00\x00\x01\x00").decode("ascii")
        wire = (
            json.dumps({"textChunk": {"text": "Привет"}}, ensure_ascii=False)
            + json.dumps({"audioChunk": {"data": audio_data}}, ensure_ascii=False)
        ).encode("utf-8")

        class ChunkResponse:
            def __init__(self, content):
                self.parts = [content[:18], content[18:21], content[21:]]
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read1(self, _size): return self.parts.pop(0) if self.parts else b""

        received = []
        client = YandexSpeechKitClient("key", opener=Mock(return_value=ChunkResponse(wire)))
        total = client.stream_synthesize(
            "Проверка потока.", voice="jane", on_audio_chunk=received.append
        )
        self.assertEqual(received, [b"\x00\x00\x01\x00"])
        self.assertEqual(total, 4)

    def test_service_account_request_does_not_send_empty_folder_header(self):
        opener = Mock(return_value=io.BytesIO(
            json.dumps({"audioChunk": {"data": base64.b64encode(b"\x00\x00").decode()}}).encode()
        ))
        YandexSpeechKitClient("key", opener=opener).stream_synthesize(
            "Да.", voice="jane", on_audio_chunk=Mock()
        )
        self.assertIsNone(opener.call_args.args[0].get_header("X-folder-id"))

    def test_cancel_stops_after_first_received_chunk(self):
        parts = [b"\x00\x00", b"\x01\x00"]
        response = io.BytesIO(b"".join(
            json.dumps({"audioChunk": {"data": base64.b64encode(part).decode()}}).encode() + b"\n"
            for part in parts
        ))
        chunks = []
        checks = iter((False, False, True))
        client = YandexSpeechKitClient("key", opener=Mock(return_value=response))
        with self.assertRaises(YandexSpeechKitCancelled):
            client.stream_synthesize(
                "Коротко.", voice="jane", on_audio_chunk=chunks.append,
                cancelled=lambda: next(checks),
            )
        self.assertEqual(chunks, [parts[0]])

    def test_cancel_before_request_does_not_contact_provider(self):
        opener = Mock()
        client = YandexSpeechKitClient("key", opener=opener)
        with self.assertRaises(YandexSpeechKitCancelled):
            client.stream_synthesize(
                "Отменено.", voice="jane", on_audio_chunk=Mock(), cancelled=lambda: True
            )
        opener.assert_not_called()

    def test_bad_or_oversized_provider_audio_is_rejected(self):
        for payload in (
            b"not-json\n",
            json.dumps({"audioChunk": {"data": "%%%"}}).encode() + b"\n",
            json.dumps({"audioChunk": {"data": base64.b64encode(b"\x00").decode()}}).encode() + b"\n",
        ):
            with self.subTest(payload=payload[:20]):
                client = YandexSpeechKitClient("key", opener=Mock(return_value=io.BytesIO(payload)))
                with self.assertRaises(YandexSpeechKitError):
                    client.stream_synthesize("Тест.", voice="jane", on_audio_chunk=Mock())

    def test_transport_error_does_not_expose_provider_body_or_secret(self):
        client = YandexSpeechKitClient(
            "secret-key",
            opener=Mock(side_effect=HTTPError(API_URL, 401, "bad key", {}, io.BytesIO(b"secret body"))),
        )
        with self.assertRaises(YandexSpeechKitError) as raised:
            client.stream_synthesize("private assistant text", voice="jane", on_audio_chunk=Mock())
        self.assertIn("HTTP 401", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception))
        self.assertNotIn("private assistant text", str(raised.exception))

    def test_invalid_request_is_rejected_before_network(self):
        opener = Mock()
        client = YandexSpeechKitClient("key", opener=opener)
        for text, voice in (("x" * 251, "jane"), ("тест", "other")):
            with self.subTest(voice=voice, chars=len(text)), self.assertRaises(ValueError):
                client.stream_synthesize(text, voice=voice, on_audio_chunk=Mock())
        opener.assert_not_called()

    def test_desktop_profile_preserves_explicit_yandex_provider_and_avatar_voice(self):
        profile = AIProfile(
            provider="disabled",
            avatar_id="male_kai",
            character_profiles={"male_kai": {"assistant_name": "Кай", "voice_id": ""}},
        )
        store = DesktopSettings()
        with patch.object(DesktopSettings, "load", return_value=profile):
            settings = store.apply(Settings(tts_engine="yandex", tts_yandex_api_key="hidden-key"))
        self.assertEqual((settings.tts_engine, settings.tts_voice_name), ("yandex", "zahar"))
        self.assertNotIn("hidden-key", repr(settings))

    def test_yandex_environment_settings_load_without_writing_credentials(self):
        values = {
            "TTS_ENGINE": "yandex",
            "YANDEX_SPEECHKIT_API_KEY": "test-secret",
            "YANDEX_SPEECHKIT_FOLDER_ID": "folder-test",
            "YANDEX_SPEECHKIT_TIMEOUT_SECONDS": "17",
        }
        empty_env_file = Path("D:/Astra-Work/Temp/empty-astra-env-for-test")
        with patch.dict(os.environ, values):
            settings = load_settings(empty_env_file)
        self.assertEqual(settings.tts_engine, "yandex")
        self.assertEqual(settings.tts_yandex_folder_id, "folder-test")
        self.assertEqual(settings.tts_yandex_timeout_seconds, 17.0)
        self.assertNotIn("test-secret", repr(settings))

    def test_desktop_profile_preserves_edge_for_automatic_voice_and_sapi_for_override(self):
        automatic = AIProfile(
            provider="disabled",
            avatar_id="female_saya",
            character_profiles={"female_saya": {"assistant_name": "Сая", "voice_id": ""}},
        )
        explicit = replace(automatic, character_profiles={
            "female_saya": {"assistant_name": "Сая", "voice_id": "windows-sapi-id"}
        })
        store = DesktopSettings()
        with patch.object(DesktopSettings, "load", return_value=automatic):
            edge_settings = store.apply(Settings(tts_engine="edge"))
        with patch.object(DesktopSettings, "load", return_value=explicit):
            sapi_settings = store.apply(Settings(tts_engine="edge"))
        self.assertEqual(edge_settings.tts_engine, "edge")
        self.assertEqual(sapi_settings.tts_engine, "sapi")
        self.assertEqual(sapi_settings.tts_voice_name, "windows-sapi-id")

    def test_voiceio_yandex_path_streams_without_disk_or_provider_fallback(self):
        writes = []
        class FakeStream:
            def write(self, data, **_kwargs):
                writes.append(data)
            def stop_stream(self): pass
            def close(self): pass
        class FakeAudio:
            def open(self, **kwargs):
                self.options = kwargs
                return FakeStream()
            def terminate(self): pass
        fake_audio = FakeAudio()
        fake_pyaudio = SimpleNamespace(PyAudio=lambda: fake_audio, paInt16=8)
        fake_client = Mock()
        def stream_synthesize(_text, *, on_audio_chunk, **_kwargs):
            on_audio_chunk(b"\x00\x00\x01\x00")
            return 4
        fake_client.stream_synthesize.side_effect = stream_synthesize
        voice = object.__new__(VoiceIO)
        voice.settings = Settings(
            tts_engine="yandex", tts_yandex_api_key="secret", assistant_gender="female",
            assistant_avatar_id="female_miku", tts_log_timing=False,
        )
        voice.logger = Mock()
        voice._log_tts_timing = Mock()

        with patch.dict(sys.modules, {"pyaudio": fake_pyaudio}), patch(
            "src.yandex_speechkit.YandexSpeechKitClient", return_value=fake_client
        ):
            self.assertTrue(voice._speak_yandex("Привет."))

        self.assertEqual(writes, [b"\x00\x00\x01\x00"])
        self.assertEqual(fake_audio.options["rate"], AUDIO_SAMPLE_RATE_HZ)
        self.assertEqual(fake_client.stream_synthesize.call_args.kwargs["voice"], "jane")
        self.assertEqual(fake_client.timeout_seconds, 25.0)
        voice._log_tts_timing.assert_called_once()

    def test_voiceio_without_yandex_key_does_not_initialize_audio_or_network(self):
        voice = object.__new__(VoiceIO)
        voice.settings = Settings(tts_engine="yandex", tts_yandex_api_key="")
        voice.logger = Mock()
        with patch("src.yandex_speechkit.YandexSpeechKitClient") as client:
            self.assertFalse(voice._speak_yandex("Не отправлять."))
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
