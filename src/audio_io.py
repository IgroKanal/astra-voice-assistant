from __future__ import annotations

import logging
import shutil
import subprocess
import sys
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
        command = self._find_edge_playback_command()

        if command is None:
            self.edge_playback_command = None
            self.logger.error(
                "edge-playback не найден. Установи пакет: pip install edge-tts"
            )
            return

        self.edge_playback_command = command
        self.logger.info(
            "Edge TTS инициализирован. voice=%s, rate=%s, volume=%s, pitch=%s",
            self.settings.tts_edge_voice,
            self.settings.tts_edge_rate,
            self.settings.tts_edge_volume,
            self.settings.tts_edge_pitch,
        )

    def _find_edge_playback_command(self) -> str | None:
        command_from_path = shutil.which("edge-playback")
        if command_from_path:
            return command_from_path

        scripts_dir = Path(sys.executable).parent
        windows_command = scripts_dir / "edge-playback.exe"
        if windows_command.exists():
            return str(windows_command)

        plain_command = scripts_dir / "edge-playback"
        if plain_command.exists():
            return str(plain_command)

        return None

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

        try:
            with self.microphone as source:
                print("Слушаю...")
                audio = self.recognizer.listen(
                    source,
                    timeout=self.settings.listen_timeout_seconds,
                    phrase_time_limit=self.settings.phrase_time_limit_seconds,
                )

            alternatives = self._recognize_google_alternatives(audio)
            if not alternatives:
                return ListenResult(False, error="Не удалось распознать речь.")

            text = self._select_best_stt_alternative(alternatives)
            self.logger.info("Распознано: %s", text)

            if len(alternatives) > 1:
                self.logger.info("STT варианты: %s", alternatives)

            return ListenResult(True, text=text, alternatives=alternatives)
        except sr.WaitTimeoutError:
            return ListenResult(False, error="Не услышал речь.")
        except sr.UnknownValueError:
            return ListenResult(False, error="Не удалось распознать речь.")
        except sr.RequestError:
            self.logger.exception("Ошибка сервиса распознавания речи")
            return ListenResult(
                False,
                error="Сервис распознавания речи недоступен. Проверь интернет.",
            )
        except Exception:
            self.logger.exception("Непредвиденная ошибка STT")
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
        if self.edge_playback_command is None:
            self.logger.error("Edge TTS недоступен: edge-playback не найден.")
            return

        command = [
            self.edge_playback_command,
            "--voice",
            self.settings.tts_edge_voice,
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
        except subprocess.CalledProcessError as exc:
            self.logger.error("Ошибка Edge TTS: %s", exc.stderr)
            print("[TTS ошибка] Edge TTS не смог озвучить ответ.")
        except Exception:
            self.logger.exception("Непредвиденная ошибка Edge TTS")
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

        try:
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
        except Exception:
            self.logger.exception("Ошибка SAPI TTS")
            print("[TTS ошибка] Не удалось озвучить ответ, но текст выведен.")
