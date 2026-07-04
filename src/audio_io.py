from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyttsx3
import speech_recognition as sr

from src.config_loader import Settings


@dataclass(frozen=True)
class ListenResult:
    ok: bool
    text: str = ""
    error: str = ""
    alternatives: list[str] = field(default_factory=list)


class VoiceIO:
    """Распознавание речи и озвучка ответа."""

    _RUSSIAN_VOICE_MARKERS = (
        "ru",
        "ru-ru",
        "russian",
        "рус",
        "irina",
        "pavel",
        "elena",
        "dmitry",
        "svetlana",
    )

    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self.recognizer = sr.Recognizer()
        self.microphone: sr.Microphone | None = None

        self.tts_engine: Any | None = None
        self.tts_has_russian_voice = False
        self.edge_playback_command: str | None = None
        self.edge_tts_command: str | None = None
        self.tts_cache_dir: Path | None = None

        self._apply_recognizer_settings()
        self._init_microphone()
        self._init_tts()

    def _apply_recognizer_settings(self) -> None:
        self.recognizer.dynamic_energy_threshold = (
            self.settings.stt_dynamic_energy_threshold
        )

        if self.settings.stt_energy_threshold > 0:
            self.recognizer.energy_threshold = self.settings.stt_energy_threshold

        self.recognizer.pause_threshold = self.settings.stt_pause_threshold
        self.recognizer.non_speaking_duration = (
            self.settings.stt_non_speaking_duration
        )

        self.logger.info(
            "STT настройки: dynamic_energy=%s, energy=%s, pause=%s, non_speaking=%s",
            self.recognizer.dynamic_energy_threshold,
            self.recognizer.energy_threshold,
            self.recognizer.pause_threshold,
            self.recognizer.non_speaking_duration,
        )

    def _init_microphone(self) -> None:
        try:
            self.microphone = sr.Microphone()
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(
                    source,
                    duration=self.settings.ambient_noise_duration_seconds,
                )
            self.logger.info("Микрофон инициализирован")
        except Exception:
            self.microphone = None
            self.logger.exception("Не удалось инициализировать микрофон")

    def _init_tts(self) -> None:
        if not self.settings.tts_enabled:
            self.logger.info("TTS отключён в настройках")
            return

        if self.settings.tts_engine == "edge":
            self._init_edge_tts()
            return

        if self.settings.tts_engine in {"sapi", "pyttsx3"}:
            self._init_sapi_tts()
            return

        self.logger.warning(
            "Неизвестный TTS_ENGINE=%r. Использую edge.",
            self.settings.tts_engine,
        )
        self._init_edge_tts()

    def _init_edge_tts(self) -> None:
        self.edge_playback_command = self._find_cli_command("edge-playback")
        self.edge_tts_command = self._find_cli_command("edge-tts")

        if self.edge_playback_command is None:
            self.logger.error(
                "edge-playback не найден. Установи пакет: pip install edge-tts"
            )
            return

        if self.settings.tts_cache_enabled and self.edge_tts_command is None:
            self.logger.warning(
                "edge-tts не найден. TTS-кэш будет отключён, но edge-playback останется."
            )

        self.tts_cache_dir = self._resolve_tts_cache_dir()
        if self.settings.tts_cache_enabled and self.edge_tts_command is not None:
            self.tts_cache_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            "Edge TTS инициализирован. voice=%s, fallback=%s, rate=%s, "
            "volume=%s, pitch=%s, cache=%s, cache_dir=%s",
            self.settings.tts_edge_voice,
            self.settings.tts_edge_fallback_voice,
            self.settings.tts_edge_rate,
            self.settings.tts_edge_volume,
            self.settings.tts_edge_pitch,
            self.settings.tts_cache_enabled,
            self.tts_cache_dir,
        )

        if (
            self.settings.tts_cache_enabled
            and self.settings.tts_cache_prewarm_enabled
            and self.edge_tts_command is not None
        ):
            self._prewarm_tts_cache()

    def _find_cli_command(self, name: str) -> str | None:
        command_from_path = shutil.which(name)
        if command_from_path:
            return command_from_path

        scripts_dir = Path(sys.executable).parent
        candidates = [
            scripts_dir / f"{name}.exe",
            scripts_dir / name,
        ]

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        return None

    def _resolve_tts_cache_dir(self) -> Path:
        configured = self.settings.tts_cache_dir.strip()
        if configured:
            return Path(configured).expanduser().resolve()

        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "AstraVoiceAssistant" / "tts_cache"

        return Path(tempfile.gettempdir()) / "AstraVoiceAssistant" / "tts_cache"

    def _prewarm_tts_cache(self) -> None:
        phrases = [
            phrase.strip()
            for phrase in self.settings.tts_cache_prewarm_phrases
            if phrase.strip()
        ]
        if not phrases:
            return

        start = time.perf_counter()
        generated = 0

        for phrase in phrases:
            try:
                media = self._ensure_edge_cached_media(phrase)
                if media is not None:
                    generated += 1
            except Exception:
                self.logger.exception("Не удалось подготовить TTS-кэш для: %r", phrase)

        elapsed = time.perf_counter() - start
        self.logger.info(
            "TTS prewarm завершён: phrases=%s, ready=%s, elapsed=%.2fs",
            len(phrases),
            generated,
            elapsed,
        )

    def _init_sapi_tts(self) -> None:
        try:
            engine = pyttsx3.init()
            voices = list(engine.getProperty("voices") or [])

            self._log_available_voices(voices)

            selected_voice = self._select_sapi_voice(voices)
            if selected_voice is not None:
                engine.setProperty("voice", selected_voice.id)
                self.tts_has_russian_voice = self._is_russian_sapi_voice(
                    selected_voice
                )
                self.logger.info(
                    "Выбран SAPI TTS-голос: %s | %s",
                    selected_voice.name,
                    selected_voice.id,
                )
            else:
                self.logger.warning("SAPI TTS-голоса не найдены.")

            engine.setProperty("rate", self.settings.tts_rate)
            engine.setProperty("volume", self.settings.tts_volume)

            self.tts_engine = engine
            self.logger.info(
                "SAPI TTS инициализирован. rate=%s, volume=%s, russian_voice=%s",
                self.settings.tts_rate,
                self.settings.tts_volume,
                self.tts_has_russian_voice,
            )
        except Exception:
            self.tts_engine = None
            self.logger.exception("Не удалось инициализировать SAPI TTS")

    def _log_available_voices(self, voices: list[Any]) -> None:
        if not self.settings.tts_debug_voices:
            return

        self.logger.info("Доступно SAPI TTS-голосов: %s", len(voices))
        for index, voice in enumerate(voices):
            self.logger.info(
                "SAPI voice #%s: name=%s | id=%s",
                index,
                getattr(voice, "name", ""),
                getattr(voice, "id", ""),
            )

    def _select_sapi_voice(self, voices: list[Any]) -> Any | None:
        if not voices:
            return None

        requested_voice = self.settings.tts_voice_name.strip().lower()
        if requested_voice:
            for voice in voices:
                voice_name = str(getattr(voice, "name", "")).lower()
                voice_id = str(getattr(voice, "id", "")).lower()

                if requested_voice in voice_name or requested_voice in voice_id:
                    return voice

        for voice in voices:
            if self._is_russian_sapi_voice(voice):
                return voice

        return voices[0]

    def _is_russian_sapi_voice(self, voice: Any) -> bool:
        voice_text = (
            f"{getattr(voice, 'name', '')} "
            f"{getattr(voice, 'id', '')} "
            f"{getattr(voice, 'languages', '')}"
        ).lower()

        return any(marker in voice_text for marker in self._RUSSIAN_VOICE_MARKERS)

    def _has_cyrillic(self, text: str) -> bool:
        return any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in text)

    def listen_once(self) -> ListenResult:
        if self.microphone is None:
            return ListenResult(False, error="Микрофон не доступен.")

        listen_started = time.perf_counter()
        try:
            with self.microphone as source:
                print("Слушаю...")
                audio = self.recognizer.listen(
                    source,
                    timeout=self.settings.listen_timeout_seconds,
                    phrase_time_limit=self.settings.phrase_time_limit_seconds,
                )

            alternatives = self._recognize_google_alternatives(audio)
            elapsed = time.perf_counter() - listen_started

            if not alternatives:
                self._log_timing("STT", elapsed, "no_alternatives")
                return ListenResult(False, error="Не удалось распознать речь.")

            text = self._select_best_stt_alternative(alternatives)
            self.logger.info("Распознано: %s", text)
            self._log_timing("STT", elapsed, "ok")

            if len(alternatives) > 1:
                self.logger.info("STT варианты: %s", alternatives)

            return ListenResult(True, text=text, alternatives=alternatives)
        except sr.WaitTimeoutError:
            self._log_timing("STT", time.perf_counter() - listen_started, "timeout")
            return ListenResult(False, error="Не услышал речь.")
        except sr.UnknownValueError:
            self._log_timing("STT", time.perf_counter() - listen_started, "unknown")
            return ListenResult(False, error="Не удалось распознать речь.")
        except sr.RequestError:
            self.logger.exception("Ошибка сервиса распознавания речи")
            self._log_timing("STT", time.perf_counter() - listen_started, "request_error")
            return ListenResult(
                False,
                error="Сервис распознавания речи недоступен. Проверь интернет.",
            )
        except Exception:
            self.logger.exception("Непредвиденная ошибка STT")
            self._log_timing("STT", time.perf_counter() - listen_started, "error")
            return ListenResult(False, error="Произошла ошибка распознавания речи.")

    def _recognize_google_alternatives(self, audio: sr.AudioData) -> list[str]:
        if not self.settings.stt_show_alternatives:
            text = self.recognizer.recognize_google(
                audio,
                language=self.settings.speech_language,
            )
            return [text.strip()] if text.strip() else []

        raw_result = self.recognizer.recognize_google(
            audio,
            language=self.settings.speech_language,
            show_all=True,
        )

        if not isinstance(raw_result, dict):
            return []

        alternatives: list[str] = []
        for item in raw_result.get("alternative", []):
            transcript = str(item.get("transcript", "")).strip()
            if transcript:
                alternatives.append(transcript)

        return alternatives

    def _select_best_stt_alternative(self, alternatives: list[str]) -> str:
        if not alternatives:
            return ""

        if not self.settings.stt_prefer_cyrillic:
            return alternatives[0].strip()

        def score(text: str) -> tuple[int, int]:
            cyrillic_count = sum(
                1 for char in text if "а" <= char.lower() <= "я" or char == "ё"
            )
            return cyrillic_count, len(text)

        return max(alternatives, key=score).strip()

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        print(f"Астра: {text}")
        self.logger.info("Ответ: %s", text)

        if not self.settings.tts_enabled:
            return

        if self.settings.tts_engine == "edge":
            self._speak_edge(text)
            return

        self._speak_sapi(text)

    def _speak_edge(self, text: str) -> None:
        started = time.perf_counter()

        if self.edge_playback_command is None:
            self.logger.error("Edge TTS недоступен: edge-playback не найден.")
            return

        if self.settings.tts_cache_enabled and self.edge_tts_command is not None:
            media_path = self._ensure_edge_cached_media(text)
            if media_path is not None and self._play_cached_media(media_path):
                self._log_timing("TTS", time.perf_counter() - started, "cache")
                return

            self.logger.warning("TTS cache fallback: использую edge-playback напрямую.")

        self._speak_edge_direct(text)
        self._log_timing("TTS", time.perf_counter() - started, "direct")

    def _edge_voice_candidates(self) -> list[str]:
        voices: list[str] = []
        for voice in (
            self.settings.tts_edge_voice,
            self.settings.tts_edge_fallback_voice,
        ):
            clean = voice.strip()
            if clean and clean not in voices:
                voices.append(clean)

        return voices

    def _ensure_edge_cached_media(self, text: str) -> Path | None:
        if self.tts_cache_dir is None or self.edge_tts_command is None:
            return None

        for voice in self._edge_voice_candidates():
            media_path = self._cache_path(text=text, voice=voice)
            if media_path.exists() and media_path.stat().st_size > 0:
                self.logger.info("TTS cache hit: %s", media_path.name)
                return media_path

            self.logger.info("TTS cache miss: %s", media_path.name)
            if self._generate_edge_media(text=text, voice=voice, output_path=media_path):
                return media_path

        return None

    def _cache_path(self, text: str, voice: str) -> Path:
        if self.tts_cache_dir is None:
            raise RuntimeError("TTS cache directory is not initialized.")

        key_source = "|".join(
            (
                voice,
                self.settings.tts_edge_rate,
                self.settings.tts_edge_volume,
                self.settings.tts_edge_pitch,
                text,
            )
        )
        digest = hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:24]
        return self.tts_cache_dir / f"{digest}.mp3"

    def _generate_edge_media(self, text: str, voice: str, output_path: Path) -> bool:
        command = [
            self.edge_tts_command or "edge-tts",
            "--voice",
            voice,
            "--rate",
            self.settings.tts_edge_rate,
            "--volume",
            self.settings.tts_edge_volume,
            "--pitch",
            self.settings.tts_edge_pitch,
            "--text",
            text,
            "--write-media",
            str(output_path),
        ]

        started = time.perf_counter()
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._log_timing(
                "TTS generate",
                time.perf_counter() - started,
                f"voice={voice}",
            )
            return output_path.exists() and output_path.stat().st_size > 0
        except subprocess.CalledProcessError as exc:
            self.logger.warning(
                "Edge TTS generation failed for voice=%s: %s",
                voice,
                exc.stderr,
            )
            output_path.unlink(missing_ok=True)
            return False
        except Exception:
            self.logger.exception("Непредвиденная ошибка генерации Edge TTS")
            output_path.unlink(missing_ok=True)
            return False

    def _play_cached_media(self, media_path: Path) -> bool:
        script = r'''
Add-Type -AssemblyName PresentationCore
$mediaPath = $args[0]
$player = New-Object System.Windows.Media.MediaPlayer
$player.Open([System.Uri]::new($mediaPath))
$player.Play()
$deadline = (Get-Date).AddSeconds(10)
while (-not $player.NaturalDuration.HasTimeSpan -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 40
}
if ($player.NaturalDuration.HasTimeSpan) {
    $durationMs = [int]$player.NaturalDuration.TimeSpan.TotalMilliseconds + 250
    Start-Sleep -Milliseconds $durationMs
} else {
    Start-Sleep -Seconds 2
}
$player.Stop()
$player.Close()
'''.strip()

        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                    str(media_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except subprocess.CalledProcessError as exc:
            self.logger.warning("Не удалось воспроизвести TTS cache: %s", exc.stderr)
            return False
        except Exception:
            self.logger.exception("Непредвиденная ошибка воспроизведения TTS cache")
            return False

    def _speak_edge_direct(self, text: str) -> None:
        for voice in self._edge_voice_candidates():
            command = [
                self.edge_playback_command or "edge-playback",
                "--voice",
                voice,
                "--rate",
                self.settings.tts_edge_rate,
                "--volume",
                self.settings.tts_edge_volume,
                "--pitch",
                self.settings.tts_edge_pitch,
                "--text",
                text,
            ]

            try:
                subprocess.run(
                    command,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return
            except subprocess.CalledProcessError as exc:
                self.logger.warning("Ошибка Edge TTS voice=%s: %s", voice, exc.stderr)
            except Exception:
                self.logger.exception("Непредвиденная ошибка Edge TTS voice=%s", voice)

        print("[TTS ошибка] Edge TTS не смог озвучить ответ.")

    def _speak_sapi(self, text: str) -> None:
        if self.tts_engine is None:
            return

        if self._has_cyrillic(text) and not self.tts_has_russian_voice:
            self.logger.warning(
                "Ответ содержит кириллицу, но русский SAPI-голос не найден. "
                "Озвучка пропущена."
            )
            return

        started = time.perf_counter()
        try:
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
            self._log_timing("TTS", time.perf_counter() - started, "sapi")
        except Exception:
            self.logger.exception("Ошибка SAPI TTS")
            print("[TTS ошибка] Не удалось озвучить ответ, но текст выведен.")

    def _log_timing(self, label: str, seconds: float, mode: str) -> None:
        if self.settings.tts_log_timing or label == "STT":
            self.logger.info("%s timing: %.2fs [%s]", label, seconds, mode)
