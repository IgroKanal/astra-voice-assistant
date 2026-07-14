from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


class ConfigError(Exception):
    """Ошибка конфигурации проекта."""


@dataclass(frozen=True)
class Settings:
    assistant_name: str = "Астра"
    wake_phrases: list[str] = field(
        default_factory=lambda: ["астра", "эй астра", "привет астра"]
    )
    allow_commands_without_wake: bool = False
    allow_text_conversation_without_wake: bool = True
    allow_voice_conversation_without_wake: bool = False

    voice_runtime_mode: str = "wake_only"
    wake_only_mode: bool = True
    wake_response_enabled: bool = True
    wake_response_text: str = "Слушаю."
    wake_listen_timeout_seconds: int = 4
    wake_phrase_time_limit_seconds: int = 4
    command_listen_timeout_seconds: int = 10
    command_phrase_time_limit_seconds: int = 16
    wake_allow_direct_command: bool = True

    router_cooldown_seconds: float = 2.0

    stt_command_aware_alternatives: bool = True
    stt_mistake_log_enabled: bool = True
    stt_mistake_log_path: str = "logs/stt_mistakes.log"

    browser_preferred: str = ""
    browser_focus_missing_timeout_seconds: float = 0.35

    routines_enabled: bool = True
    routines_config_path: str = "config/routines.json"
    context_ttl_seconds: float = 120.0

    voice_max_speak_chars: int = 180
    voice_short_responses: bool = True

    vpn_enabled: bool = True
    vpn_provider: str = "amneziawg"
    vpn_tunnel_service_name: str = "AmneziaWGTunnel$pc-awg-2"
    vpn_manager_service_name: str = "AmneziaWGManager"
    vpn_command_timeout_seconds: float = 15.0

    llm_enabled: bool = True
    llm_provider: str = "gemini"
    llm_api_key: str = ""
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_model: str = "gemma-4-31b-it"
    llm_fallback_model: str = "gemini-3.5-flash"
    llm_system_prompt: str = (
        "Ты голосовой ассистент для ПК. Твоё имя Астра. "
        "Отвечай кратко, понятно и по делу. Обычно 1–3 предложения."
    )
    llm_temperature: float = 0.2
    llm_max_tokens: int = 500
    llm_timeout_seconds: int = 30

    llm_router_enabled: bool = True
    llm_router_min_confidence: float = 0.55

    speech_language: str = "ru-RU"
    listen_timeout_seconds: int = 10
    phrase_time_limit_seconds: int = 16
    ambient_noise_duration_seconds: float = 0.6

    stt_dynamic_energy_threshold: bool = True
    stt_energy_threshold: int = 0
    stt_pause_threshold: float = 1.15
    stt_non_speaking_duration: float = 0.8
    stt_show_alternatives: bool = True
    stt_prefer_cyrillic: bool = True

    tts_enabled: bool = True
    tts_engine: str = "edge"

    tts_edge_voice: str = "ru-RU-SvetlanaNeural"
    tts_edge_fallback_voice: str = "ru-RU-DmitryNeural"
    tts_edge_rate: str = "+10%"
    tts_edge_volume: str = "+0%"
    tts_edge_pitch: str = "+0Hz"

    tts_cache_enabled: bool = True
    tts_cache_dir: str = ""
    tts_cache_prewarm_enabled: bool = True
    tts_cache_prewarm_max_new_phrases: int = 1
    tts_cache_generation_timeout_seconds: int = 8
    tts_cache_prewarm_phrases: list[str] = field(
        default_factory=lambda: [
            "Астра запущена.",
            "Слушаю.",
            "Открываю.",
            "Открываю сайт.",
            "Закрываю.",
            "Ищу.",
            "Завершаю работу.",
            "Не расслышал, повтори.",
            "Что открыть?",
            "Что закрыть?",
            "Готово.",
            "Пишу.",
            "Закрываю вкладку.",
            "Открываю новую вкладку.",
            "Обновляю.",
            "Открываю папку.",
            "Скриншот сохранён.",
            "Громче.",
            "Тише.",
            "Переключаю звук.",
            "VPN включён.",
            "VPN выключен.",
            "Открытие окна отключено.",
            "Закрытие окна отключено.",
            "Показываю рабочий стол.",
            "Сворачиваю окно.",
            "Разворачиваю окно.",
            "Пока нечего повторять.",
            "Интернет доступен.",
            "Открываю загрузки.",
            "Открываю историю.",
        ]
    )
    tts_log_timing: bool = True

    tts_rate: int = 180
    tts_volume: float = 1.0
    tts_voice_name: str = ""
    tts_debug_voices: bool = True


@dataclass(frozen=True)
class AppConfig:
    name: str
    aliases: list[str]
    open_command: list[str]
    process_name: str


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "да",
        "on",
        "вкл",
    }


def _int_from_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(
            f"Переменная {name} должна быть числом, сейчас: {value!r}"
        ) from exc


def _float_from_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default

    try:
        return float(value.replace(",", "."))
    except ValueError as exc:
        raise ConfigError(
            f"Переменная {name} должна быть числом, сейчас: {value!r}"
        ) from exc


def _list_from_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default

    return [item.strip() for item in value.split(",") if item.strip()]


def _str_from_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default

    return value.strip() or default



def _looks_like_mojibake(value: str) -> bool:
    return any(marker in value for marker in ("Р", "СЃ", "С€", "СЋ", "Р»"))


def _repair_common_mojibake(value: str) -> str:
    """Repairs common UTF-8-as-Windows-1251 mojibake in .env values.

    This is intentionally conservative and is used only for user-facing text
    such as the wake response. It prevents broken responses like
    "РЎР»СѓС€Р°СЋ." when a PowerShell script or editor saved Cyrillic with
    the wrong encoding.
    """
    if not value or not _looks_like_mojibake(value):
        return value

    try:
        repaired = value.encode("cp1251").decode("utf-8")
    except UnicodeError:
        return value

    # Keep the repaired value only if it became plausible Cyrillic.
    if any("а" <= char <= "я" or "А" <= char <= "Я" for char in repaired):
        return repaired

    return value


def _text_from_env(name: str, default: str) -> str:
    return _repair_common_mojibake(_str_from_env(name, default))


def _gemini_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", os.getenv("LLM_API_KEY", "")).strip()


def _gemini_models() -> tuple[str, str]:
    legacy_model = _str_from_env("LLM_MODEL", "gemma-4-31b-it")
    legacy_fallback = _str_from_env("LLM_FALLBACK_MODEL", "gemini-3.5-flash")

    primary = _str_from_env("GEMINI_MODEL", legacy_model)
    fallback = _str_from_env("GEMINI_FALLBACK_MODEL", legacy_fallback)

    return primary, fallback


def load_settings(env_path: str | Path = ".env") -> Settings:
    """Загружает настройки из .env. Если .env нет, используются дефолты."""
    load_dotenv(dotenv_path=env_path)

    default_name = "Астра"
    assistant_name = os.getenv("ASSISTANT_NAME", default_name).strip() or default_name

    default_wake_phrases = list(
        dict.fromkeys(
            [
                assistant_name.lower(),
                f"эй {assistant_name.lower()}",
                f"привет {assistant_name.lower()}",
                "астро",
                "остра",
                "а стра",
                "астер",
                "астэр",
                "астры",
            ]
        )
    )

    default_system_prompt = (
        f"Ты голосовой ассистент для ПК. Твоё имя {assistant_name}. "
        "Отвечай кратко, понятно и законченными фразами. "
        "Обычно 1–3 предложения. Не используй markdown и черновики."
    )

    gemini_model, gemini_fallback_model = _gemini_models()

    return Settings(
        assistant_name=assistant_name,
        wake_phrases=_list_from_env("WAKE_PHRASES", default_wake_phrases),
        allow_commands_without_wake=_bool_from_env(
            "ALLOW_COMMANDS_WITHOUT_WAKE",
            False,
        ),
        allow_text_conversation_without_wake=_bool_from_env(
            "ALLOW_TEXT_CONVERSATION_WITHOUT_WAKE",
            True,
        ),
        allow_voice_conversation_without_wake=_bool_from_env(
            "ALLOW_VOICE_CONVERSATION_WITHOUT_WAKE",
            False,
        ),
        voice_runtime_mode=_str_from_env(
            "VOICE_RUNTIME_MODE",
            "wake_only",
        ).lower(),
        wake_only_mode=_bool_from_env(
            "WAKE_ONLY_MODE",
            True,
        ),
        wake_response_enabled=_bool_from_env(
            "WAKE_RESPONSE_ENABLED",
            True,
        ),
        wake_response_text=_text_from_env(
            "WAKE_RESPONSE_TEXT",
            "Слушаю.",
        ),
        wake_listen_timeout_seconds=_int_from_env(
            "WAKE_LISTEN_TIMEOUT_SECONDS",
            4,
        ),
        wake_phrase_time_limit_seconds=_int_from_env(
            "WAKE_PHRASE_TIME_LIMIT_SECONDS",
            4,
        ),
        command_listen_timeout_seconds=_int_from_env(
            "COMMAND_LISTEN_TIMEOUT_SECONDS",
            10,
        ),
        command_phrase_time_limit_seconds=_int_from_env(
            "COMMAND_PHRASE_TIME_LIMIT_SECONDS",
            16,
        ),
        wake_allow_direct_command=_bool_from_env(
            "WAKE_ALLOW_DIRECT_COMMAND",
            True,
        ),
        router_cooldown_seconds=_float_from_env(
            "ROUTER_COOLDOWN_SECONDS",
            2.0,
        ),
        stt_command_aware_alternatives=_bool_from_env(
            "STT_COMMAND_AWARE_ALTERNATIVES",
            True,
        ),
        stt_mistake_log_enabled=_bool_from_env(
            "STT_MISTAKE_LOG_ENABLED",
            True,
        ),
        stt_mistake_log_path=_str_from_env(
            "STT_MISTAKE_LOG_PATH",
            "logs/stt_mistakes.log",
        ),
        browser_preferred=_str_from_env("BROWSER_PREFERRED", ""),
        browser_focus_missing_timeout_seconds=_float_from_env(
            "BROWSER_FOCUS_MISSING_TIMEOUT_SECONDS",
            0.35,
        ),
        routines_enabled=_bool_from_env("ROUTINES_ENABLED", True),
        routines_config_path=_str_from_env(
            "ROUTINES_CONFIG_PATH",
            "config/routines.json",
        ),
        context_ttl_seconds=_float_from_env("CONTEXT_TTL_SECONDS", 120.0),
        voice_max_speak_chars=_int_from_env("VOICE_MAX_SPEAK_CHARS", 180),
        voice_short_responses=_bool_from_env("VOICE_SHORT_RESPONSES", True),

        vpn_enabled=_bool_from_env("VPN_ENABLED", True),
        vpn_provider=_str_from_env("VPN_PROVIDER", "amneziawg"),
        vpn_tunnel_service_name=_str_from_env(
            "VPN_TUNNEL_SERVICE_NAME",
            "AmneziaWGTunnel$pc-awg-2",
        ),
        vpn_manager_service_name=_str_from_env(
            "VPN_MANAGER_SERVICE_NAME",
            "AmneziaWGManager",
        ),
        vpn_command_timeout_seconds=_float_from_env(
            "VPN_COMMAND_TIMEOUT_SECONDS",
            15.0,
        ),
        llm_enabled=_bool_from_env("LLM_ENABLED", True),
        llm_provider=os.getenv("LLM_PROVIDER", "gemini").strip().lower(),
        llm_api_key=_gemini_api_key(),
        llm_base_url=os.getenv(
            "LLM_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ).strip(),
        llm_model=gemini_model,
        llm_fallback_model=gemini_fallback_model,
        llm_system_prompt=os.getenv(
            "LLM_SYSTEM_PROMPT",
            default_system_prompt,
        ).strip(),
        llm_temperature=_float_from_env("LLM_TEMPERATURE", 0.2),
        llm_max_tokens=_int_from_env("LLM_MAX_TOKENS", 500),
        llm_timeout_seconds=_int_from_env("LLM_TIMEOUT_SECONDS", 30),
        llm_router_enabled=_bool_from_env("LLM_ROUTER_ENABLED", True),
        llm_router_min_confidence=_float_from_env(
            "LLM_ROUTER_MIN_CONFIDENCE",
            0.55,
        ),
        speech_language=os.getenv("SPEECH_LANGUAGE", "ru-RU").strip(),
        listen_timeout_seconds=_int_from_env("LISTEN_TIMEOUT_SECONDS", 10),
        phrase_time_limit_seconds=_int_from_env("PHRASE_TIME_LIMIT_SECONDS", 16),
        ambient_noise_duration_seconds=_float_from_env(
            "AMBIENT_NOISE_DURATION_SECONDS",
            0.6,
        ),
        stt_dynamic_energy_threshold=_bool_from_env(
            "STT_DYNAMIC_ENERGY_THRESHOLD",
            True,
        ),
        stt_energy_threshold=_int_from_env("STT_ENERGY_THRESHOLD", 0),
        stt_pause_threshold=_float_from_env("STT_PAUSE_THRESHOLD", 1.15),
        stt_non_speaking_duration=_float_from_env(
            "STT_NON_SPEAKING_DURATION",
            0.8,
        ),
        stt_show_alternatives=_bool_from_env("STT_SHOW_ALTERNATIVES", True),
        stt_prefer_cyrillic=_bool_from_env("STT_PREFER_CYRILLIC", True),
        tts_enabled=_bool_from_env("TTS_ENABLED", True),
        tts_engine=_str_from_env("TTS_ENGINE", "edge").lower(),
        tts_edge_voice=_str_from_env("TTS_EDGE_VOICE", "ru-RU-SvetlanaNeural"),
        tts_edge_fallback_voice=_str_from_env(
            "TTS_EDGE_FALLBACK_VOICE",
            "ru-RU-DmitryNeural",
        ),
        tts_edge_rate=_str_from_env("TTS_EDGE_RATE", "+10%"),
        tts_edge_volume=_str_from_env("TTS_EDGE_VOLUME", "+0%"),
        tts_edge_pitch=_str_from_env("TTS_EDGE_PITCH", "+0Hz"),
        tts_cache_enabled=_bool_from_env("TTS_CACHE_ENABLED", True),
        tts_cache_dir=os.getenv("TTS_CACHE_DIR", "").strip(),
        tts_cache_prewarm_enabled=_bool_from_env(
            "TTS_CACHE_PREWARM_ENABLED",
            True,
        ),
        tts_cache_prewarm_max_new_phrases=_int_from_env(
            "TTS_CACHE_PREWARM_MAX_NEW_PHRASES",
            1,
        ),
        tts_cache_generation_timeout_seconds=_int_from_env(
            "TTS_CACHE_GENERATION_TIMEOUT_SECONDS",
            8,
        ),
        tts_cache_prewarm_phrases=_list_from_env(
            "TTS_CACHE_PREWARM_PHRASES",
            Settings().tts_cache_prewarm_phrases,
        ),
        tts_log_timing=_bool_from_env("TTS_LOG_TIMING", True),
        tts_rate=_int_from_env("TTS_RATE", 180),
        tts_volume=_float_from_env("TTS_VOLUME", 1.0),
        tts_voice_name=os.getenv("TTS_VOICE_NAME", "").strip(),
        tts_debug_voices=_bool_from_env("TTS_DEBUG_VOICES", True),
    )


def load_apps_config(path: str | Path = "config/apps.json") -> dict[str, AppConfig]:
    """Загружает список разрешённых Windows-приложений из config/apps.json."""
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Файл {config_path} не найден.")

    try:
        raw_data: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"Файл {config_path} содержит неправильный JSON: {exc}"
        ) from exc

    raw_apps = raw_data.get("apps")
    if not isinstance(raw_apps, dict) or not raw_apps:
        raise ConfigError("В config/apps.json должен быть непустой объект apps.")

    apps: dict[str, AppConfig] = {}

    for app_name, app_data in raw_apps.items():
        if not isinstance(app_data, dict):
            raise ConfigError(f"Приложение {app_name!r} должно быть объектом.")

        aliases = app_data.get("aliases", [])
        open_command = app_data.get("open_command")
        process_name = app_data.get("process_name")

        if not isinstance(aliases, list) or not all(
            isinstance(item, str) for item in aliases
        ):
            raise ConfigError(
                f"У приложения {app_name!r} aliases должен быть списком строк."
            )

        if isinstance(open_command, str):
            open_command = [open_command]

        if not isinstance(open_command, list) or not all(
            isinstance(item, str) for item in open_command
        ):
            raise ConfigError(
                f"У приложения {app_name!r} open_command должен быть строкой "
                "или списком строк."
            )

        if not isinstance(process_name, str) or not process_name.strip():
            raise ConfigError(
                f"У приложения {app_name!r} process_name должен быть строкой."
            )

        clean_name = str(app_name).strip().lower()
        all_aliases = sorted(
            {
                clean_name,
                *(alias.strip().lower() for alias in aliases if alias.strip()),
            }
        )

        apps[clean_name] = AppConfig(
            name=clean_name,
            aliases=all_aliases,
            open_command=open_command,
            process_name=process_name.strip(),
        )

    return apps
