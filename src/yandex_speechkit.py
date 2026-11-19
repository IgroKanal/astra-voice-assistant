"""Opt-in Yandex SpeechKit v3 streaming synthesis for Russian replies.

The adapter is deliberately small and uses the standard library. It does not
make network requests until ``stream_synthesize`` is called, never writes
audio or spoken text to disk, and exposes audio chunks to the caller as they
arrive so the Windows runtime can play them incrementally.
"""
from __future__ import annotations

import base64
import binascii
import codecs
from dataclasses import dataclass
import json
import re
from typing import BinaryIO, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"
AUDIO_SAMPLE_RATE_HZ = 22_050
MAX_REQUEST_CHARS = 250
MAX_RESPONSE_LINE_BYTES = 1_048_576
MAX_RESPONSE_AUDIO_BYTES = 8 * 1_048_576


class YandexSpeechKitError(RuntimeError):
    """Safe, payload-free error from the SpeechKit adapter."""


class YandexSpeechKitCancelled(YandexSpeechKitError):
    """The caller cancelled an in-flight synthesis request."""


@dataclass(frozen=True)
class RussianVoice:
    voice_id: str
    gender: str
    default_role: str = ""


# Four distinct Russian general-model voices. The names and genders follow
# the provider's published voice table; Egor still needs to audition them.
RUSSIAN_VOICES = {
    "jane": RussianVoice("jane", "female", "neutral"),
    "masha": RussianVoice("masha", "female", "good"),
    "filipp": RussianVoice("filipp", "male"),
    "zahar": RussianVoice("zahar", "male", "neutral"),
}

DEFAULT_VOICE_BY_AVATAR = {
    "female_miku": "jane",
    "female_saya": "masha",
    "male_ren": "filipp",
    "male_kai": "zahar",
}


def resolve_russian_voice(
    *, avatar_id: str = "", gender: str = "female", requested_voice: str = ""
) -> RussianVoice:
    """Resolve a built-in voice without permitting a known gender mismatch."""
    requested = str(requested_voice or "").strip().casefold()
    if requested.startswith("yandex:"):
        requested = requested.split(":", 1)[1].strip()
    if requested:
        voice = RUSSIAN_VOICES.get(requested)
        if voice is None:
            raise ValueError("Выбранный голос не входит в каталог русских голосов Astra")
    else:
        voice_id = DEFAULT_VOICE_BY_AVATAR.get(str(avatar_id or ""))
        voice = RUSSIAN_VOICES.get(voice_id or "")
        if voice is None or voice.gender != gender:
            voice = RUSSIAN_VOICES["jane" if gender == "female" else "filipp"]
    if gender in {"female", "male"} and voice.gender != gender:
        raise ValueError("Пол голоса не совпадает с выбранным персонажем")
    return voice


def split_text_for_requests(text: str, *, max_chars: int = MAX_REQUEST_CHARS) -> list[str]:
    """Split spoken text into bounded phrases, preferring sentence/word edges."""
    if not isinstance(text, str):
        raise TypeError("Текст для синтеза должен быть строкой")
    if type(max_chars) is not int or not 1 <= max_chars <= MAX_REQUEST_CHARS:
        raise ValueError("Некорректный предел длины фразы")
    text = text.strip()
    if not text:
        return []

    sentences = re.split(r"(?<=[.!?…])\s+", text)
    phrases: list[str] = []
    current = ""
    for sentence in sentences:
        words = sentence.split()
        if not words:
            continue
        for word in words:
            if len(word) > max_chars:
                raise ValueError("Слово длиннее допустимой фразы SpeechKit")
            candidate = f"{current} {word}".strip()
            if len(candidate) > max_chars:
                phrases.append(current)
                current = word
            else:
                current = candidate
    if current:
        phrases.append(current)
    return phrases


def _read_json_lines(response: BinaryIO) -> Iterable[dict]:
    """Incrementally decode concatenated/NDJSON response messages."""
    read_chunk = getattr(response, "read1", None)
    if not callable(read_chunk):
        read_chunk = response.read
    utf8 = codecs.getincrementaldecoder("utf-8")()
    json_decoder = json.JSONDecoder()
    buffer = ""
    received_bytes = 0
    while True:
        raw = read_chunk(64 * 1024)
        received_bytes += len(raw or b"")
        if received_bytes > MAX_RESPONSE_AUDIO_BYTES * 2:
            raise YandexSpeechKitError("Превышен предел ответа SpeechKit")
        buffer += utf8.decode(raw or b"", final=not raw)
        finished = not raw
        if len(buffer.encode("utf-8")) > MAX_RESPONSE_LINE_BYTES and not raw:
            raise YandexSpeechKitError("Слишком большой фрагмент ответа SpeechKit")

        while True:
            buffer = buffer.lstrip()
            if not buffer:
                break
            try:
                value, end = json_decoder.raw_decode(buffer)
            except json.JSONDecodeError as exc:
                if len(buffer.encode("utf-8")) > MAX_RESPONSE_LINE_BYTES:
                    raise YandexSpeechKitError("Слишком большой фрагмент ответа SpeechKit") from exc
                if finished:
                    raise YandexSpeechKitError("Некорректный формат ответа SpeechKit") from exc
                break
            if len(buffer[:end].encode("utf-8")) > MAX_RESPONSE_LINE_BYTES:
                raise YandexSpeechKitError("Слишком большой фрагмент ответа SpeechKit")
            buffer = buffer[end:]
            if not isinstance(value, dict):
                raise YandexSpeechKitError("Некорректная структура ответа SpeechKit")
            yield value

        if finished:
            if buffer.strip():
                raise YandexSpeechKitError("Некорректный формат ответа SpeechKit")
            return


class YandexSpeechKitClient:
    """Streaming SpeechKit v3 REST client with bounded audio output."""

    def __init__(
        self,
        api_key: str,
        *,
        folder_id: str = "",
        timeout_seconds: float = 25.0,
        opener: Callable[..., BinaryIO] | None = None,
    ) -> None:
        key = str(api_key or "").strip()
        if not key or len(key) > 10_000 or any(ord(char) < 32 for char in key):
            raise ValueError("Для SpeechKit требуется API-ключ")
        folder = str(folder_id or "").strip()
        if len(folder) > 128 or any(ord(char) < 32 for char in folder):
            raise ValueError("Некорректный идентификатор каталога SpeechKit")
        if type(timeout_seconds) not in (int, float) or not 1 <= timeout_seconds <= 60:
            raise ValueError("Тайм-аут SpeechKit должен быть от 1 до 60 секунд")
        self._api_key = key
        self._folder_id = folder
        self.timeout_seconds = float(timeout_seconds)
        self._opener = opener or urlopen

    def stream_synthesize(
        self,
        text: str,
        *,
        voice: str,
        on_audio_chunk: Callable[[bytes], None],
        cancelled: Callable[[], bool] | None = None,
    ) -> int:
        """Stream raw 16-bit mono PCM chunks to the caller; returns byte count."""
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_REQUEST_CHARS:
            raise ValueError("Одна фраза SpeechKit должна содержать от 1 до 250 символов")
        if not callable(on_audio_chunk):
            raise TypeError("Нужен обработчик аудиофрагментов")
        selected = RUSSIAN_VOICES.get(str(voice or "").strip().casefold())
        if selected is None:
            raise ValueError("Выбранный голос не входит в каталог русских голосов Astra")
        if cancelled is not None and not callable(cancelled):
            raise ValueError("Некорректный обработчик отмены")

        def is_cancelled() -> bool:
            if cancelled is None:
                return False
            try:
                return bool(cancelled())
            except Exception:
                return True

        if is_cancelled():
            raise YandexSpeechKitCancelled("Синтез отменён")

        hints = [{"voice": selected.voice_id}]
        if selected.default_role:
            hints.append({"role": selected.default_role})
        payload = {
            "text": text.strip(),
            "hints": hints,
            "outputAudioSpec": {
                "rawAudio": {
                    "audioEncoding": "LINEAR16_PCM",
                    "sampleRateHertz": str(AUDIO_SAMPLE_RATE_HZ),
                }
            },
            "loudnessNormalizationType": "LUFS",
        }
        headers = {
            "Authorization": f"Api-key {self._api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        }
        if self._folder_id:
            headers["x-folder-id"] = self._folder_id
        request = Request(
            API_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        total_bytes = 0
        chunks = 0
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                for message in _read_json_lines(response):
                    if is_cancelled():
                        raise YandexSpeechKitCancelled("Синтез отменён")
                    result = message.get("result")
                    if isinstance(result, dict):
                        message = result
                    if message.get("error") or message.get("code") and not message.get("audioChunk"):
                        raise YandexSpeechKitError("SpeechKit отклонил запрос на синтез")
                    audio = message.get("audioChunk")
                    encoded = audio.get("data") if isinstance(audio, dict) else None
                    if encoded is None:
                        continue
                    if not isinstance(encoded, str):
                        raise YandexSpeechKitError("Некорректный аудиофрагмент SpeechKit")
                    try:
                        decoded = base64.b64decode(encoded, validate=True)
                    except (binascii.Error, ValueError) as exc:
                        raise YandexSpeechKitError("Повреждён аудиофрагмент SpeechKit") from exc
                    if not decoded or len(decoded) % 2:
                        raise YandexSpeechKitError("Некорректный PCM-фрагмент SpeechKit")
                    total_bytes += len(decoded)
                    if total_bytes > MAX_RESPONSE_AUDIO_BYTES:
                        raise YandexSpeechKitError("Превышен предел аудиоданных SpeechKit")
                    on_audio_chunk(decoded)
                    chunks += 1
        except HTTPError as exc:
            raise YandexSpeechKitError(f"SpeechKit вернул HTTP {int(exc.code)}") from None
        except URLError as exc:
            reason = getattr(exc, "reason", None)
            kind = type(reason).__name__ if reason is not None else "NetworkError"
            raise YandexSpeechKitError(f"Сеть SpeechKit недоступна ({kind})") from None
        except TimeoutError:
            raise YandexSpeechKitError("Истёк тайм-аут SpeechKit") from None
        except YandexSpeechKitError:
            raise
        except Exception as exc:
            # Never expose provider exception text: it may include request data.
            raise YandexSpeechKitError(
                f"Ошибка обмена с SpeechKit ({type(exc).__name__})"
            ) from None
        if chunks == 0:
            raise YandexSpeechKitError("SpeechKit не вернул аудиоданные")
        return total_bytes
