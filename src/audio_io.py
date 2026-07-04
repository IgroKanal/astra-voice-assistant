from __future__ import annotations

import logging
from dataclasses import dataclass

import pyttsx3
import speech_recognition as sr

from src.config_loader import Settings


@dataclass(frozen=True)
class ListenResult:
    ok: bool
    text: str = ""
    error: str = ""


class VoiceIO:
    """Распознавание речи и озвучка ответа."""

    def __init__(self, settings: Settings, logger: logging.Logger | None = None) -> None:
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self.recognizer = sr.Recognizer()
        self.microphone: sr.Microphone | None = None
        self.tts_engine = None

        self._init_microphone()
        self._init_tts()

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

        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self.settings.tts_rate)
            engine.setProperty("volume", self.settings.tts_volume)
            self.tts_engine = engine
            self.logger.info("TTS инициализирован")
        except Exception:
            self.tts_engine = None
            self.logger.exception("Не удалось инициализировать TTS")

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

            text = self.recognizer.recognize_google(audio, language=self.settings.speech_language)
            text = text.strip()
            self.logger.info("Распознано: %s", text)
            return ListenResult(True, text=text)
        except sr.WaitTimeoutError:
            return ListenResult(False, error="Не услышал речь.")
        except sr.UnknownValueError:
            return ListenResult(False, error="Не удалось распознать речь.")
        except sr.RequestError:
            self.logger.exception("Ошибка сервиса распознавания речи")
            return ListenResult(False, error="Сервис распознавания речи недоступен. Проверь интернет.")
        except Exception:
            self.logger.exception("Непредвиденная ошибка STT")
            return ListenResult(False, error="Произошла ошибка распознавания речи.")

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        print(f"Астра: {text}")
        self.logger.info("Ответ: %s", text)

        if self.tts_engine is None:
            return

        try:
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
        except Exception:
            self.logger.exception("Ошибка TTS")
            print("[TTS ошибка] Не удалось озвучить ответ, но текст выведен в консоль.")
