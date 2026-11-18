"""Per-user adaptive capability preferences, kept separate from app config."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets


_VERSION = 2
_MAX_BYTES = 16_384
_PREFERENCE_RE = re.compile(r"^[\w.-]{1,80}$", re.UNICODE)
_VPN_SERVICE_RE = re.compile(r"^[A-Za-z0-9_$.-]{1,256}$")


@dataclass(frozen=True)
class CapabilityOverrides:
    """Small user-only preference set; discovered system facts are not stored."""

    browser_preferred: str = ""
    disabled_auto_scopes: tuple[str, ...] = ()
    vpn_service_preferred: str = ""

    def validate(self) -> "CapabilityOverrides":
        if not isinstance(self.browser_preferred, str):
            raise ValueError("Некорректный выбор браузера")
        value = self.browser_preferred.strip()
        if value and not _PREFERENCE_RE.fullmatch(value):
            raise ValueError("В выборе браузера допустимо только имя приложения")
        if not isinstance(self.vpn_service_preferred, str):
            raise ValueError("Некорректное имя службы VPN")
        vpn_service = self.vpn_service_preferred.strip()
        if vpn_service and not _VPN_SERVICE_RE.fullmatch(vpn_service):
            raise ValueError("Некорректное имя службы VPN")
        if not isinstance(self.disabled_auto_scopes, (tuple, list)) or any(
            not isinstance(scope, str) or scope not in {"browser", "system"} for scope in self.disabled_auto_scopes
        ):
            raise ValueError("Неизвестное ограничение автоматических возможностей")
        return CapabilityOverrides(browser_preferred=value.casefold(),
                                   disabled_auto_scopes=tuple(sorted(set(self.disabled_auto_scopes))),
                                   vpn_service_preferred=vpn_service)


class CapabilityOverrideStore:
    """Atomically stores non-secret user preferences outside the project tree."""

    def __init__(self, path: Path | None = None):
        local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home())
        self.path = Path(path) if path is not None else Path(local_app_data) / "AstraVoiceAssistant" / "capability_overrides.json"

    def load(self) -> CapabilityOverrides:
        if not self.path.exists():
            return CapabilityOverrides()
        if self.path.is_symlink() or self.path.stat().st_size > _MAX_BYTES:
            raise ValueError("Недопустимый файл пользовательских предпочтений Astra")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Не удалось прочитать пользовательские предпочтения Astra") from exc
        version = data.get("version") if isinstance(data, dict) else None
        if not isinstance(data, dict) or type(version) is not int or version not in {1, _VERSION}:
            raise ValueError("Неподдерживаемый формат пользовательских предпочтений Astra")
        allowed_keys = {"version", "browser_preferred", "disabled_auto_scopes"}
        if version >= 2:
            allowed_keys.add("vpn_service_preferred")
        if set(data) - allowed_keys:
            raise ValueError("В пользовательских предпочтениях есть неизвестные поля")
        return CapabilityOverrides(browser_preferred=data.get("browser_preferred", ""),
                                   disabled_auto_scopes=data.get("disabled_auto_scopes", ()),
                                   vpn_service_preferred=data.get("vpn_service_preferred", "")).validate()

    def save(self, overrides: CapabilityOverrides) -> None:
        clean = overrides.validate()
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if parent.is_symlink() or self.path.is_symlink():
            raise ValueError("Путь пользовательских предпочтений подменён ссылкой")
        encoded = json.dumps(
            {"version": _VERSION, "browser_preferred": clean.browser_preferred,
             "disabled_auto_scopes": clean.disabled_auto_scopes,
             "vpn_service_preferred": clean.vpn_service_preferred},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_BYTES:
            raise ValueError("Пользовательские предпочтения Astra слишком велики")
        temporary = self.path.with_name(self.path.name + "." + secrets.token_hex(8) + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
