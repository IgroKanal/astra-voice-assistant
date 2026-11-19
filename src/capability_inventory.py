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
from src.network_adapter_discovery import discover_network_adapter_inventory
from src.ras_discovery import (
    discover_windows_ras_active_vpn_profile_names,
    discover_windows_ras_profile_names,
    discover_windows_ras_vpn_profile_names,
)


@dataclass(frozen=True)
class CapabilityInventory:
    """Bounded counts of detected resources; these facts never grant access."""

    registered_applications: int | None
    browsers: int | None
    system_default_browser: bool | None
    audio_inputs: int | None
    audio_outputs: int | None
    network_adapters: int | None
    virtual_network_adapters: int | None
    supported_vpn_tunnels: int | None
    windows_ras_profiles: int | None = None
    windows_ras_vpn_profiles: int | None = None
    active_windows_ras_vpn_profiles: int | None = None

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

        if self.network_adapters is None or self.virtual_network_adapters is None:
            parts.append("сетевые адаптеры прочитать не удалось")
        else:
            parts.append(
                f"сетевых адаптеров обнаружено: {self.network_adapters}; "
                f"виртуальных адаптеров: {self.virtual_network_adapters}"
            )
            if self.virtual_network_adapters:
                parts.append(
                    "виртуальный адаптер может относиться к VPN, виртуальной машине "
                    "или контейнеру; конкретный клиент не определён"
                )

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

        if self.windows_ras_profiles is None:
            parts.append("профили удалённого доступа Windows прочитать не удалось")
        else:
            parts.append(
                f"профилей Windows RAS обнаружено: {self.windows_ras_profiles}; "
                "среди них могут быть VPN и dial-up подключения, ими Astra пока не управляет"
            )

        if self.windows_ras_vpn_profiles is None:
            parts.append("тип VPN-профилей Windows RAS определить не удалось")
        else:
            parts.append(
                f"VPN-профилей Windows RAS обнаружено: {self.windows_ras_vpn_profiles}; "
                "подключение через Astra пока не поддерживается"
            )

        if self.active_windows_ras_vpn_profiles is None:
            parts.append("состояние активных Windows RAS VPN-подключений прочитать не удалось")
        elif self.active_windows_ras_vpn_profiles:
            parts.append(
                "активных VPN-подключений Windows RAS: "
                f"{self.active_windows_ras_vpn_profiles}"
            )
        else:
            parts.append("активные VPN-подключения Windows RAS не обнаружены")

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
    try:
        network = discover_network_adapter_inventory()
    except Exception:
        # Discovery is advisory. A registry/provider failure on one Windows
        # installation must not prevent the voice runtime from returning the
        # rest of the capability snapshot.
        network = None
    vpn_count = _read_count(discover_vpn_tunnel_services, lambda items: len(items))
    ras_count = _read_count(discover_windows_ras_profile_names, lambda items: len(items))
    ras_vpn_count = _read_count(
        discover_windows_ras_vpn_profile_names, lambda items: len(items)
    )
    active_ras_vpn_count = _read_count(
        discover_windows_ras_active_vpn_profile_names, lambda items: len(items)
    )
    return CapabilityInventory(
        registered_applications=application_count,
        browsers=browser_count,
        system_default_browser=default_browser,
        audio_inputs=audio_count,
        audio_outputs=audio_output_count,
        network_adapters=network.adapter_count if network is not None else None,
        virtual_network_adapters=(
            network.virtual_adapter_count if network is not None else None
        ),
        supported_vpn_tunnels=vpn_count,
        windows_ras_profiles=ras_count,
        windows_ras_vpn_profiles=ras_vpn_count,
        active_windows_ras_vpn_profiles=active_ras_vpn_count,
    )
