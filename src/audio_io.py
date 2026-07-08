from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

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
        self.tts_cache_dir = self._resolve_tts_cache_dir()
        self.alternative_selector: Callable[[list[str]], str] | None = None

        self._apply_recognizer_settings()
        self._init_microphone()
        self._init_tts()

    def set_alternative_selector(
        self,
        selector: Callable[[list[str]], str] | None,
    ) -> None:
        self.alternative_selector = selector

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
        playback_command = self._find_script_command("edge-playback")
        tts_command = self._find_script_command("edge-tts")

        if playback_command is None:
            self.edge_playback_command = None
            self.logger.error(
                "edge-playback не найден. Установи пакет: pip install edge-tts"
            )
            return

        self.edge_playback_command = playback_command
        self.edge_tts_command = tts_command

        if self.settings.tts_cache_enabled:
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

        if self.settings.tts_cache_enabled and self.edge_tts_command is None:
            self.logger.warning(
                "edge-tts не найден. TTS-кэш не сможет генерировать mp3, "
                "но прямой edge-playback останется доступен."
            )

        if (
            self.settings.tts_cache_enabled
            and self.settings.tts_cache_prewarm_enabled
            and self.edge_tts_command is not None
        ):
            self._prewarm_tts_cache()

    def _find_script_command(self, command_name: str) -> str | None:
        command_from_path = shutil.which(command_name)
        if command_from_path:
            return command_from_path

        scripts_dir = Path(sys.executable).parent
        for candidate in (
            scripts_dir / f"{command_name}.exe",
            scripts_dir / command_name,
        ):
            if candidate.exists():
                return str(candidate)

        return None

    def _resolve_tts_cache_dir(self) -> Path:
        configured = getattr(self.settings, "tts_cache_dir", "").strip()
        if configured:
            return Path(configured).expanduser()

        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "AstraVoiceAssistant" / "tts_cache"

        return Path.home() / ".astra_voice_assistant" / "tts_cache"

    def _prewarm_tts_cache(self) -> None:
        start = time.perf_counter()
        ready = 0
        generated = 0
        skipped_missing = 0
        max_new = max(0, self.settings.tts_cache_prewarm_max_new_phrases)

        for phrase in self.settings.tts_cache_prewarm_phrases:
            phrase = phrase.strip()
            if not phrase:
                continue

            cache_path = self._edge_cache_path(
                text=phrase,
                voice=self.settings.tts_edge_voice,
            )
            if cache_path.exists():
                self.logger.info("TTS cache hit: %s", cache_path.name)
                ready += 1
                continue

            # v0.10.6: не генерируем десятки новых фраз синхронно при старте.
            # Иначе запуск голосового режима может висеть 40-60 секунд.
            if generated >= max_new:
                skipped_missing += 1
                self.logger.debug("TTS prewarm skip missing: %s", cache_path.name)
                continue

            cached = self._ensure_edge_cached_audio(
                text=phrase,
                voice=self.settings.tts_edge_voice,
            )
            if cached is not None and cached.exists():
                ready += 1
                generated += 1

        elapsed = time.perf_counter() - start
        self.logger.info(
            "TTS prewarm завершён: phrases=%s, ready=%s, generated=%s, "
            "skipped_missing=%s, elapsed=%.2fs",
            len(self.settings.tts_cache_prewarm_phrases),
            ready,
            generated,
            skipped_missing,
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

        start = time.perf_counter()

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

            elapsed = time.perf_counter() - start
            self.logger.info("STT timing: %.2fs [ok]", elapsed)

            if len(alternatives) > 1:
                self.logger.info("STT варианты: %s", alternatives)
                if text != alternatives[0].strip():
                    self._log_stt_diagnostic(
                        kind="alternative_selected",
                        text=text,
                        alternatives=alternatives,
                        elapsed=elapsed,
                    )

            return ListenResult(True, text=text, alternatives=alternatives)
        except sr.WaitTimeoutError:
            elapsed = time.perf_counter() - start
            self.logger.info("STT timing: %.2fs [timeout]", elapsed)
            self._log_stt_diagnostic(
                kind="timeout",
                text="",
                alternatives=[],
                elapsed=elapsed,
            )
            return ListenResult(False, error="Не услышал речь.")
        except sr.UnknownValueError:
            elapsed = time.perf_counter() - start
            self.logger.info("STT timing: %.2fs [unknown]", elapsed)
            self._log_stt_diagnostic(
                kind="unknown",
                text="",
                alternatives=[],
                elapsed=elapsed,
            )
            return ListenResult(False, error="Не удалось распознать речь.")
        except sr.RequestError:
            elapsed = time.perf_counter() - start
            self.logger.info("STT timing: %.2fs [request_error]", elapsed)
            self.logger.exception("Ошибка сервиса распознавания речи")
            return ListenResult(
                False,
                error="Сервис распознавания речи недоступен. Проверь интернет.",
            )
        except Exception:
            elapsed = time.perf_counter() - start
            self.logger.info("STT timing: %.2fs [error]", elapsed)
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

        cleaned = [item.strip() for item in alternatives if item.strip()]
        if not cleaned:
            return ""

        if (
            self.settings.stt_command_aware_alternatives
            and self.alternative_selector is not None
        ):
            try:
                selected = self.alternative_selector(cleaned).strip()
                if selected:
                    return selected
            except Exception:
                self.logger.exception("Ошибка command-aware выбора STT alternative")

        if not self.settings.stt_prefer_cyrillic:
            return cleaned[0]

        def score(text: str) -> tuple[int, int]:
            cyrillic_count = sum(
                1 for char in text if "а" <= char.lower() <= "я" or char == "ё"
            )
            return cyrillic_count, len(text)

        return max(cleaned, key=score).strip()

    def _log_stt_diagnostic(
        self,
        kind: str,
        text: str,
        alternatives: list[str],
        elapsed: float,
    ) -> None:
        if not self.settings.stt_mistake_log_enabled:
            return

        try:
            path = Path(self.settings.stt_mistake_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            line = (
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} | "
                f"{kind} | elapsed={elapsed:.2f}s | "
                f"selected={text!r} | alternatives={alternatives!r}\n"
            )
            path.open("a", encoding="utf-8").write(line)
        except Exception:
            self.logger.debug("Не удалось записать STT diagnostic log", exc_info=True)

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
        start = time.perf_counter()

        if self.edge_playback_command is None:
            self.logger.error("Edge TTS недоступен: edge-playback не найден.")
            return

        if self.settings.tts_cache_enabled and self.edge_tts_command is not None:
            cached = self._ensure_edge_cached_audio(
                text=text,
                voice=self.settings.tts_edge_voice,
            )
            if cached is not None and self._play_cached_audio(cached):
                self._log_tts_timing(start, "cache")
                return

            fallback_voice = self.settings.tts_edge_fallback_voice.strip()
            if fallback_voice:
                cached_fallback = self._ensure_edge_cached_audio(
                    text=text,
                    voice=fallback_voice,
                )
                if cached_fallback is not None and self._play_cached_audio(
                    cached_fallback
                ):
                    self._log_tts_timing(start, "cache_fallback_voice")
                    return

            self.logger.warning("TTS cache fallback: использую edge-playback напрямую.")

        if self._speak_edge_direct(text, self.settings.tts_edge_voice):
            self._log_tts_timing(start, "direct")
            return

        fallback_voice = self.settings.tts_edge_fallback_voice.strip()
        if fallback_voice and fallback_voice != self.settings.tts_edge_voice:
            self.logger.warning(
                "Edge TTS primary voice failed. Пробую fallback voice: %s",
                fallback_voice,
            )
            if self._speak_edge_direct(text, fallback_voice):
                self._log_tts_timing(start, "direct_fallback_voice")
                return

        self._log_tts_timing(start, "failed")

    def _ensure_edge_cached_audio(self, text: str, voice: str) -> Path | None:
        cache_path = self._edge_cache_path(text=text, voice=voice)
        if cache_path.exists():
            self.logger.info("TTS cache hit: %s", cache_path.name)
            return cache_path

        if self.edge_tts_command is None:
            return None

        self.logger.info("TTS cache miss: %s", cache_path.name)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = cache_path.with_suffix(".tmp.mp3")
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

        command = [
            self.edge_tts_command,
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
            str(tmp_path),
        ]

        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(5, self.settings.tts_cache_generation_timeout_seconds),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            tmp_path.replace(cache_path)
            return cache_path
        except subprocess.TimeoutExpired:
            self.logger.warning(
                "Не удалось создать TTS cache: timeout after %ss",
                max(5, self.settings.tts_cache_generation_timeout_seconds),
            )
            tmp_path.unlink(missing_ok=True)
            return None
        except subprocess.CalledProcessError as exc:
            error_text = (exc.stderr or "").strip()
            if not error_text:
                error_text = "edge-tts вернул ошибку без текста stderr"
            self.logger.warning("Не удалось создать TTS cache: %s", error_text)
            tmp_path.unlink(missing_ok=True)
            return None
        except Exception:
            self.logger.exception("Непредвиденная ошибка создания TTS cache")
            tmp_path.unlink(missing_ok=True)
            return None

    def _edge_cache_path(self, text: str, voice: str) -> Path:
        cache_key = "|".join(
            (
                voice,
                self.settings.tts_edge_rate,
                self.settings.tts_edge_volume,
                self.settings.tts_edge_pitch,
                text,
            )
        )
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24]
        return self.tts_cache_dir / f"{digest}.mp3"

    def _play_cached_audio(self, path: Path) -> bool:
        """
        Воспроизводит mp3 из кэша через Windows MCI.

        Это не использует PowerShell и не запускает отдельный плеер.
        Поэтому нет ParserError и нет зависания на WMPlayer.OCX.
        """
        alias = "astra_tts_" + hashlib.md5(
            f"{path}|{time.perf_counter()}".encode("utf-8")
        ).hexdigest()[:10]

        opened = False

        try:
            self._mci_send(f'open "{path}" type mpegvideo alias {alias}')
            opened = True
            self._mci_send(f"play {alias} wait")
            return True
        except Exception as exc:
            self.logger.warning("Не удалось воспроизвести TTS cache через MCI: %s", exc)
            return False
        finally:
            if opened:
                try:
                    self._mci_send(f"close {alias}")
                except Exception:
                    self.logger.debug("Не удалось закрыть MCI alias: %s", alias)

    def _mci_send(self, command: str) -> None:
        winmm = ctypes.windll.winmm
        error_code = winmm.mciSendStringW(command, None, 0, None)

        if error_code == 0:
            return

        buffer = ctypes.create_unicode_buffer(512)
        winmm.mciGetErrorStringW(error_code, buffer, len(buffer))
        raise RuntimeError(f"MCI error {error_code}: {buffer.value}; command={command}")

    def _speak_edge_direct(self, text: str, voice: str) -> bool:
        if self.edge_playback_command is None:
            return False

        command = [
            self.edge_playback_command,
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
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except subprocess.CalledProcessError as exc:
            self.logger.error("Ошибка Edge TTS: %s", exc.stderr)
            print("[TTS ошибка] Edge TTS не смог озвучить ответ.")
            return False
        except Exception:
            self.logger.exception("Непредвиденная ошибка Edge TTS")
            print("[TTS ошибка] Edge TTS не смог озвучить ответ.")
            return False

    def _log_tts_timing(self, start: float, mode: str) -> None:
        if not self.settings.tts_log_timing:
            return

        elapsed = time.perf_counter() - start
        self.logger.info("TTS timing: %.2fs [%s]", elapsed, mode)

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
