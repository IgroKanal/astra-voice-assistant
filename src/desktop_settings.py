"""User-selected AI profile, encrypted locally with Windows DPAPI."""
from dataclasses import asdict, dataclass, field, replace
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

import win32crypt

from src.config_loader import Settings
from src.action_policy import ALL_SCOPES


AVATAR_PROFILES = {
    "female_miku": {"label": "Мику · женский образ", "default_name": "Мику", "asset": "anime_female.png", "speaking_asset": "anime_female_speaking.png"},
    "male_ren": {"label": "Рэн · мужской образ", "default_name": "Рэн", "asset": "anime_male.png", "speaking_asset": "anime_male_speaking.png"},
    "female_saya": {"label": "Сая · женский образ", "default_name": "Сая", "asset": "anime_female_saya.png", "speaking_asset": "anime_female_saya_speaking.png"},
    "male_kai": {"label": "Кай · мужской образ", "default_name": "Кай", "asset": "anime_male_kai.png", "speaking_asset": "anime_male_kai_speaking.png"},
}
DEFAULT_AVATAR_ID = "female_miku"
COMMAND_LIKE_NAMES = ("открой", "закрой", "сверни", "разверни", "покажи", "включи", "выключи", "напомни", "следующий", "предыдущий", "обнови", "найди", "поищи", "переключи", "нажми", "напиши", "громче", "тише", "стоп")


@dataclass(frozen=True)
class AIProfile:
    provider: str = "env"
    model: str = "qwen3:4b"
    base_url: str = "http://127.0.0.1:11434"
    api_key: str = field(default="", repr=False)
    memory_enabled: bool = False
    allowed_scopes: tuple[str, ...] = ALL_SCOPES
    assistant_name: str | None = None
    voice_id: str = ""
    microphone_index: int | None = None
    voice_rate: int = 180
    voice_volume: float = 1.0
    avatar_id: str = DEFAULT_AVATAR_ID
    character_profiles: dict[str, dict[str, str]] = field(default_factory=dict, repr=False)

    def validate(self):
        if self.provider not in {"env", "disabled", "ollama", "gemini", "compatible"}:
            raise ValueError("Неизвестный провайдер")
        if not isinstance(self.allowed_scopes, (tuple, list)) or len(self.allowed_scopes) > len(ALL_SCOPES) or any(scope not in ALL_SCOPES for scope in self.allowed_scopes):
            raise ValueError("Неизвестное разрешение навыка")
        if not isinstance(self.memory_enabled, bool) or (self.memory_enabled and self.provider != "ollama"):
            raise ValueError("Личная память разрешена только для локального Ollama")
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 200:
            raise ValueError("Укажи модель (до 200 символов)")
        if not isinstance(self.api_key, str) or len(self.api_key) > 10000:
            raise ValueError("Неверный ключ")
        if self.assistant_name is not None:
            clean_name = self.assistant_name.strip()
            if not 1 <= len(clean_name) <= 32 or not re.fullmatch(r"[\w -]+", clean_name, re.UNICODE) or clean_name.casefold().split()[0] in COMMAND_LIKE_NAMES:
                raise ValueError("Имя должно содержать 1–32 буквы и не быть командой")
        if not isinstance(self.character_profiles, dict) or len(self.character_profiles) > len(AVATAR_PROFILES):
            raise ValueError("Некорректные профили персонажей")
        for identity, character in self.character_profiles.items():
            if identity not in AVATAR_PROFILES or not isinstance(character, dict) or set(character) != {"assistant_name", "voice_id"}:
                raise ValueError("Некорректный профиль персонажа")
            name = character["assistant_name"]
            voice_id = character["voice_id"]
            if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 32 or
                    not re.fullmatch(r"[\w -]+", name.strip(), re.UNICODE) or
                    name.strip().casefold().split()[0] in COMMAND_LIKE_NAMES or
                    not isinstance(voice_id, str) or len(voice_id) > 2000):
                raise ValueError("Некорректное имя или голос персонажа")
        if not isinstance(self.voice_id, str) or len(self.voice_id) > 2000:
            raise ValueError("Некорректный голос Windows")
        if not isinstance(self.avatar_id, str) or self.avatar_id not in AVATAR_PROFILES:
            raise ValueError("Неизвестный образ ассистента")
        if self.microphone_index is not None and (type(self.microphone_index) is not int or not 0 <= self.microphone_index <= 256):
            raise ValueError("Выбери обнаруженный микрофон")
        if type(self.voice_rate) is not int or not 80 <= self.voice_rate <= 300:
            raise ValueError("Скорость голоса должна быть от 80 до 300")
        if type(self.voice_volume) not in (int, float) or not 0 <= self.voice_volume <= 1:
            raise ValueError("Громкость голоса должна быть от 0 до 1")
        if self.provider == "ollama":
            url = urlsplit(self.base_url)
            if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"} or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
                raise ValueError("Ollama должен использовать локальный HTTP endpoint без пути")
            if self.api_key:
                raise ValueError("Ollama не требует API-ключ")
        elif self.provider == "compatible":
            url = urlsplit(self.base_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("Для облачного провайдера нужен HTTPS endpoint без credentials")
        return self


class DesktopSettings:
    def __init__(self, path: Path | None = None):
        self.path = path or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AstraVoiceAssistant" / "settings.dpapi"

    def load(self) -> AIProfile:
        if not self.path.exists():
            return AIProfile()
        if self.path.is_symlink() or self.path.stat().st_size > 100000:
            raise ValueError("Недопустимый файл настроек")
        raw = win32crypt.CryptUnprotectData(self.path.read_bytes(), None, None, None, 1)[1]
        data = json.loads(raw.decode("utf-8"))
        if data.pop("version", None) != 1:
            raise ValueError("Неподдерживаемая версия настроек")
        return AIProfile(**data).validate()

    def save(self, profile: AIProfile):
        profile.validate()
        raw = json.dumps(dict(version=1, **asdict(profile)), ensure_ascii=False).encode("utf-8")
        encrypted = win32crypt.CryptProtectData(raw, "Astra settings", None, None, None, 1)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + "." + secrets.token_hex(8) + ".tmp")
        with temporary.open("xb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def apply(self, settings: Settings) -> Settings:
        profile = self.load()
        name = profile.assistant_name or settings.assistant_name
        phrases = list(dict.fromkeys([name.casefold(), *settings.wake_phrases]))
        settings = replace(settings, action_permissions=tuple(profile.allowed_scopes), assistant_name=name, wake_phrases=phrases, tts_engine="sapi", tts_voice_name=profile.voice_id, tts_rate=profile.voice_rate, tts_volume=profile.voice_volume, stt_device_index=profile.microphone_index)
        if profile.provider == "env":
            return settings
        if profile.provider == "disabled":
            return replace(settings, llm_enabled=False, llm_router_enabled=False)
        if profile.provider == "ollama":
            return replace(settings, llm_enabled=True, llm_provider="ollama", llm_base_url=profile.base_url.rstrip("/"), llm_model=profile.model, llm_fallback_model="", llm_api_key="", llm_timeout_seconds=120, llm_router_enabled=False, personal_memory_enabled=profile.memory_enabled)
        endpoint = "https://generativelanguage.googleapis.com/v1beta/openai/" if profile.provider == "gemini" else profile.base_url
        return replace(settings, llm_enabled=True, llm_provider=profile.provider, llm_base_url=endpoint, llm_model=profile.model, llm_fallback_model="", llm_api_key=profile.api_key)
