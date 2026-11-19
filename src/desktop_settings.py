"""User-selected AI profile, encrypted locally with Windows DPAPI."""
from dataclasses import asdict, dataclass, field, replace
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

import win32crypt

from src.audio_device_discovery import (
    audio_input_identities_for_index,
    discover_audio_inputs,
    resolve_audio_input_index,
)
from src.capability_overrides import CapabilityOverrideStore
from src.config_loader import Settings
from src.action_policy import ALL_SCOPES, DEFAULT_SCOPES


AVATAR_PROFILES = {
    "female_miku": {"label": "Мику · женский образ", "default_name": "Мику", "gender": "female", "asset": "full_female.png", "speaking_asset": "full_female_speaking.png"},
    "male_ren": {"label": "Рэн · мужской образ", "default_name": "Рэн", "gender": "male", "asset": "full_male.png", "speaking_asset": "full_male_speaking.png"},
    "female_saya": {"label": "Сая · женский образ", "default_name": "Сая", "gender": "female", "asset": "full_female_saya.png", "speaking_asset": "full_female_saya_speaking.png"},
    "male_kai": {"label": "Кай · мужской образ", "default_name": "Кай", "gender": "male", "asset": "full_male_kai.png", "speaking_asset": "full_male_kai_speaking.png"},
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
    cloud_dialogue_enabled: bool = False
    local_command_router_enabled: bool = False
    allowed_scopes: tuple[str, ...] = DEFAULT_SCOPES
    assistant_name: str | None = None
    voice_id: str = ""
    microphone_index: int | None = None
    microphone_identity: str = field(default="", repr=False)
    voice_rate: int = 180
    voice_volume: float = 1.0
    avatar_id: str = DEFAULT_AVATAR_ID
    character_profiles: dict[str, dict[str, str]] = field(default_factory=dict, repr=False)
    avatar_mode: str = "2d"
    ui_scale: int = 100
    reduced_motion: bool = False

    def validate(self):
        if self.provider not in {"env", "disabled", "ollama", "gemini", "compatible"}:
            raise ValueError("Неизвестный провайдер")
        if not isinstance(self.allowed_scopes, (tuple, list)) or len(self.allowed_scopes) > len(ALL_SCOPES) or any(scope not in ALL_SCOPES for scope in self.allowed_scopes):
            raise ValueError("Неизвестное разрешение навыка")
        if not isinstance(self.memory_enabled, bool) or (self.memory_enabled and self.provider != "ollama"):
            raise ValueError("Личная память разрешена только для локального Ollama")
        if not isinstance(self.cloud_dialogue_enabled, bool) or (self.cloud_dialogue_enabled and self.provider not in {"gemini", "compatible"}):
            raise ValueError("Контекст облачного диалога доступен только для выбранного облачного провайдера")
        if not isinstance(self.local_command_router_enabled, bool) or (self.local_command_router_enabled and self.provider != "ollama"):
            raise ValueError("Некорректная настройка локального распознавания команд")
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
        if not isinstance(self.microphone_identity, str) or (self.microphone_identity and not re.fullmatch(r"[a-f0-9]{64}", self.microphone_identity)):
            raise ValueError("Некорректный идентификатор микрофона")
        if type(self.voice_rate) is not int or not 80 <= self.voice_rate <= 300:
            raise ValueError("Скорость голоса должна быть от 80 до 300")
        if type(self.voice_volume) not in (int, float) or not 0 <= self.voice_volume <= 1:
            raise ValueError("Громкость голоса должна быть от 0 до 1")
        if self.avatar_mode not in {"2d", "3d"}:
            raise ValueError("Режим персонажа должен быть 2D или 3D")
        if type(self.ui_scale) is not int or self.ui_scale not in {100, 110, 125, 150}:
            raise ValueError("Масштаб интерфейса должен быть 100, 110, 125 или 150%")
        if not isinstance(self.reduced_motion, bool):
            raise ValueError("Некорректная настройка анимации")
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
            if url.hostname == "openrouter.ai" and self.model.strip() == "openai/gpt-6-luna-decisions":
                raise ValueError("Luna Decisions не предназначена для диалога. Выбери openai/gpt-6-luna.")
        return self


class DesktopSettings:
    def __init__(
        self,
        path: Path | None = None,
        capability_override_store: CapabilityOverrideStore | None = None,
    ):
        self.path = path or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AstraVoiceAssistant" / "settings.dpapi"
        if capability_override_store is not None:
            self.capability_override_store = capability_override_store
        elif path is not None:
            self.capability_override_store = CapabilityOverrideStore(
                self.path.parent / "capability_overrides.json"
            )
        else:
            self.capability_override_store = CapabilityOverrideStore()

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
        previous_profile = None
        if self.path.exists():
            try:
                previous_profile = self.load()
            except Exception:
                # Saving a corrected profile must remain possible after a
                # damaged DPAPI file; the new selection is validated below.
                previous_profile = None

        endpoint_identity_update = None
        if profile.microphone_index is None:
            selected_a_different_saved_device = (
                previous_profile is not None
                and previous_profile.microphone_index is not None
                and profile.microphone_identity == previous_profile.microphone_identity
            )
            if not profile.microphone_identity or selected_a_different_saved_device:
                # The settings UI represents Windows' default input as None;
                # it may still carry the previous profile's identity. Portable
                # profile imports also intentionally clear local device fields.
                profile = replace(profile, microphone_identity="")
                endpoint_identity_update = ""
            elif profile.microphone_identity:
                # A profile from another machine can contain a stable label
                # fingerprint but no useful PortAudio index. Remap only when
                # it matches exactly one device on this computer.
                endpoint_identity = ""
                if (
                    previous_profile is not None
                    and profile.microphone_identity
                    == previous_profile.microphone_identity
                ):
                    endpoint_identity = (
                        self.capability_override_store.load().microphone_endpoint_identity
                    )
                devices = discover_audio_inputs()
                resolved_index = resolve_audio_input_index(
                    profile.microphone_identity,
                    devices,
                    endpoint_identity=endpoint_identity,
                )
                if resolved_index is not None:
                    device = next(
                        item for item in devices if item.index == resolved_index
                    )
                    profile = replace(
                        profile,
                        microphone_index=resolved_index,
                        microphone_identity=device.identity,
                    )
                    endpoint_identity_update = device.endpoint_identity
                elif (
                    previous_profile is None
                    or profile.microphone_identity
                    != previous_profile.microphone_identity
                ):
                    # Never apply the previous profile's endpoint hash to a
                    # different fingerprint if the new identity is unresolved.
                    endpoint_identity_update = ""
        elif (
            previous_profile is None
            or profile.microphone_index != previous_profile.microphone_index
            or profile.microphone_identity != previous_profile.microphone_identity
        ):
            # A changed index is a new explicit selection, even when an older
            # identity is still present in the profile object.
            identity, endpoint_identity = audio_input_identities_for_index(
                profile.microphone_index
            )
            if not identity:
                raise ValueError(
                    "Не удалось проверить выбранный микрофон. "
                    "Обнови список устройств или выбери системный микрофон Windows."
                )
            profile = replace(profile, microphone_identity=identity)
            endpoint_identity_update = endpoint_identity
        elif profile.microphone_identity:
            # A stored PortAudio index is only a hint: device ordering can
            # change after reconnects or on another PC. Re-resolve a stable
            # fingerprint on save and persist the current local index.
            stored_endpoint_identity = (
                self.capability_override_store.load().microphone_endpoint_identity
            )
            devices = discover_audio_inputs()
            resolved_index = resolve_audio_input_index(
                profile.microphone_identity,
                devices,
                endpoint_identity=stored_endpoint_identity,
            )
            if resolved_index is None:
                # Do not let a stale numeric index silently select another
                # device. Keep the fingerprint so a future save can remap it.
                profile = replace(profile, microphone_index=None)
            else:
                device = next(
                    item for item in devices if item.index == resolved_index
                )
                profile = replace(
                    profile,
                    microphone_index=resolved_index,
                    microphone_identity=device.identity,
                )
                endpoint_identity_update = device.endpoint_identity

        data = asdict(profile)
        if not profile.microphone_identity:
            data.pop("microphone_identity", None)
        # Older clients can still read profiles that do not opt in.
        if not profile.cloud_dialogue_enabled:
            data.pop("cloud_dialogue_enabled")
        raw = json.dumps(dict(version=1, **data), ensure_ascii=False).encode("utf-8")
        encrypted = win32crypt.CryptProtectData(raw, "Astra settings", None, None, None, 1)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + "." + secrets.token_hex(8) + ".tmp")
        old_overrides = None
        overrides_updated = False
        try:
            with temporary.open("xb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            if endpoint_identity_update is not None:
                old_overrides = self.capability_override_store.load()
                updated_overrides = replace(
                    old_overrides,
                    microphone_endpoint_identity=endpoint_identity_update,
                )
                if updated_overrides != old_overrides:
                    self.capability_override_store.save(updated_overrides)
                    overrides_updated = True
            os.replace(temporary, self.path)
        except Exception:
            if overrides_updated and old_overrides is not None:
                self.capability_override_store.save(old_overrides)
            raise
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def apply(self, settings: Settings) -> Settings:
        profile = self.load()
        endpoint_identity = ""
        if profile.microphone_identity:
            try:
                endpoint_identity = (
                    self.capability_override_store.load().microphone_endpoint_identity
                )
            except (OSError, ValueError):
                # A malformed preference sidecar must not prevent startup;
                # the stable profile fingerprint remains a safe fallback.
                endpoint_identity = ""
        character = profile.character_profiles.get(profile.avatar_id)
        if character is None:
            # Profiles created before per-character settings keep using their
            # top-level name and voice as a backwards-compatible fallback.
            name = profile.assistant_name or settings.assistant_name
            voice_id = profile.voice_id
        else:
            name = character["assistant_name"]
            # Empty means automatic voice selection for the character's gender.
            voice_id = character["voice_id"]
        phrases = list(dict.fromkeys([name.casefold(), *settings.wake_phrases]))
        settings = replace(settings, action_permissions=tuple(profile.allowed_scopes), assistant_name=name, assistant_gender=AVATAR_PROFILES[profile.avatar_id]["gender"], assistant_avatar_id=profile.avatar_id, wake_phrases=phrases, tts_engine="sapi", tts_voice_name=voice_id, tts_rate=profile.voice_rate, tts_volume=profile.voice_volume, stt_device_index=profile.microphone_index, stt_device_identity=profile.microphone_identity, stt_device_endpoint_identity=endpoint_identity)
        if profile.provider == "env":
            return settings
        if profile.provider == "disabled":
            return replace(settings, llm_enabled=False, llm_router_enabled=False)
        if profile.provider == "ollama":
            return replace(settings, llm_enabled=True, llm_provider="ollama", llm_base_url=profile.base_url.rstrip("/"), llm_model=profile.model, llm_fallback_model="", llm_api_key="", llm_timeout_seconds=120, llm_router_enabled=profile.local_command_router_enabled, personal_memory_enabled=profile.memory_enabled)
        endpoint = "https://generativelanguage.googleapis.com/v1beta/openai/" if profile.provider == "gemini" else profile.base_url
        return replace(settings, llm_enabled=True, llm_provider=profile.provider, llm_base_url=endpoint, llm_model=profile.model, llm_fallback_model="", llm_api_key=profile.api_key, llm_cloud_dialogue_enabled=profile.cloud_dialogue_enabled)
