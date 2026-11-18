"""Read-only inventory of capabilities discovered on the current computer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.audio_device_discovery import discover_audio_inputs, discover_audio_outputs
from src.system_discovery import (
    BrowserDiscovery,
    discover_registered_applications,
    discover_vpn_tunnel_services,
    discover_windows_browsers,
)


@dataclass(frozen=True)
class CapabilityInventory:
    """Bounded counts of detected resources; these facts never grant access."""

    registered_applications: int | None
    browsers: int | None
    system_default_browser: bool | None
    audio_inputs: int | None
    audio_outputs: int | None
    supported_vpn_tunnels: int | None

    def describe(self) -> str:
        parts = []
        if self.registered_applications is None:
            parts.append("список зарегистрированных приложений прочитать не удалось")
        else:
            parts.append(
                f"приложений для запуска обнаружено: {self.registered_applications}"
            )

        if self.browsers is None or self.system_default_browser is None:
            parts.append("список браузеров прочитать не удалось")
        else:
            default = "найден" if self.system_default_browser else "не найден"
            parts.append(
                f"браузеров обнаружено: {self.browsers}; системный браузер по умолчанию {default}"
            )

        if self.audio_inputs is None:
            parts.append("список устройств ввода звука прочитать не удалось")
        elif self.audio_inputs:
            parts.append(f"входных аудиоустройств обнаружено: {self.audio_inputs}")
        else:
            parts.append("входные аудиоустройства не обнаружены")

        if self.audio_outputs is None:
            parts.append("список устройств вывода звука прочитать не удалось")
        elif self.audio_outputs:
            parts.append(f"выходных аудиоустройств обнаружено: {self.audio_outputs}")
        else:
            parts.append("выходные аудиоустройства не обнаружены")

        if self.supported_vpn_tunnels is None:
            parts.append("список поддерживаемых VPN-туннелей прочитать не удалось")
        elif self.supported_vpn_tunnels:
            parts.append(
                "поддерживаемых туннелей AmneziaWG/WireGuard: "
                f"{self.supported_vpn_tunnels}; подключение и отключение требуют подтверждения"
            )
        else:
            parts.append(
                "управляемые Astra туннели AmneziaWG/WireGuard не обнаружены; "
                "это не исключает другие VPN-клиенты"
            )

        parts.append(
            "Это только инвентаризация: запуск нового приложения требует "
            "подтверждения, а обнаружение само по себе не выдаёт разрешений."
        )
        return "На этом компьютере: " + ". ".join(parts)


def _read_count(source: Callable[[], object], measure: Callable[[object], int]) -> int | None:
    try:
        return max(0, min(100_000, int(measure(source()))))
    except Exception:
        # Discovery is advisory. A broken registry, COM provider, or audio
        # backend should yield an incomplete snapshot, not stop voice runtime.
        return None


def discover_capability_inventory() -> CapabilityInventory:
    """Take a fresh bounded read-only snapshot from current Windows adapters."""
    application_count = _read_count(
        discover_registered_applications, lambda items: len(items)
    )

    browser_snapshot: BrowserDiscovery | None = None
    try:
        browser_snapshot = discover_windows_browsers()
    except Exception:
        pass

    browser_count = len(browser_snapshot.apps) if browser_snapshot is not None else None
    default_browser = (
        bool(browser_snapshot.default_browser
             and browser_snapshot.default_browser in browser_snapshot.apps)
        if browser_snapshot is not None else None
    )
    audio_count = _read_count(
        lambda: discover_audio_inputs(strict=True), lambda items: len(items)
    )
    audio_output_count = _read_count(
        lambda: discover_audio_outputs(strict=True), lambda items: len(items)
    )
    vpn_count = _read_count(discover_vpn_tunnel_services, lambda items: len(items))
    return CapabilityInventory(
        registered_applications=application_count,
        browsers=browser_count,
        system_default_browser=default_browser,
        audio_inputs=audio_count,
        audio_outputs=audio_output_count,
        supported_vpn_tunnels=vpn_count,
    )
