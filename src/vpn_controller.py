from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Literal

from src.capability_overrides import CapabilityOverrideStore
from src.config_loader import Settings
from src.system_discovery import discover_vpn_tunnel_services, is_supported_vpn_tunnel_service
from src.windows_service_control import (
    ServiceControl,
    WindowsServiceControl,
    WindowsServiceError,
)


@dataclass(frozen=True)
class VpnActionResult:
    ok: bool
    message: str
    status: str = "unknown"


@dataclass(frozen=True)
class VpnSelectionResult:
    selected: bool
    remembered: bool


class VpnController:
    """Безопасное управление выбранным VPN-туннелем через Windows service control.

    Обнаруженный туннель выбирается только по точному элементу свежего реестра.
    Произнесённая фраза никогда не становится именем службы или командой.
    """

    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger | None = None,
        *,
        override_store: CapabilityOverrideStore | None = None,
        service_control: ServiceControl | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self.override_store = override_store
        self.tunnel_service = settings.vpn_tunnel_service_name.strip()
        self.manager_service = settings.vpn_manager_service_name.strip()
        self.timeout_seconds = min(60.0, max(3.0, settings.vpn_command_timeout_seconds))
        self._service_control = service_control

    def _services(self) -> ServiceControl:
        if self._service_control is None:
            self._service_control = WindowsServiceControl()
        return self._service_control

    def available_tunnel_services(self) -> tuple[str, ...]:
        """Return a fresh read-only inventory for voice disambiguation."""
        return discover_vpn_tunnel_services()

    def select_discovered_tunnel(self, service_name: str, *, remember: bool = False) -> VpnSelectionResult:
        """Select an exact current inventory item; speech is never a service name."""
        if not isinstance(service_name, str) or not service_name:
            return VpnSelectionResult(False, False)
        try:
            candidates = self.available_tunnel_services()
        except (OSError, ValueError):
            return VpnSelectionResult(False, False)
        selected = next(
            (candidate for candidate in candidates if candidate.casefold() == service_name.casefold()),
            "",
        )
        if not selected or not is_supported_vpn_tunnel_service(selected):
            return VpnSelectionResult(False, False)
        self.tunnel_service = selected
        self.settings = replace(self.settings, vpn_tunnel_service_name=selected)
        if not remember:
            return VpnSelectionResult(True, False)
        if self.override_store is None:
            return VpnSelectionResult(True, False)
        try:
            self.override_store.set_vpn_service_preferred(selected)
            return VpnSelectionResult(True, True)
        except (OSError, ValueError):
            self.logger.warning("VPN choice could not be saved to user preferences")
            return VpnSelectionResult(True, False)

    def selected_tunnel_is_current(self, service_name: str) -> bool:
        """Revalidate discovered service identity immediately before dispatch."""
        if (not isinstance(service_name, str) or not service_name
                or service_name.casefold() != self.tunnel_service.casefold()):
            return False
        if not is_supported_vpn_tunnel_service(service_name):
            # An explicit legacy/custom service remains controlled by its exact
            # configured name; this adapter does not reinterpret it.
            return True
        try:
            return any(item.casefold() == service_name.casefold()
                       for item in self.available_tunnel_services())
        except (OSError, ValueError):
            return False

    def status(self) -> VpnActionResult:
        if not self.settings.vpn_enabled:
            return VpnActionResult(False, "VPN-команды отключены в настройках.", "disabled")

        state = self._get_service_status(self.tunnel_service)
        if state == "not_found":
            # Inventory helps status adapt to a new PC. It does not select a
            # service for connect/disconnect, which can interrupt connectivity.
            try:
                candidates = discover_vpn_tunnel_services()
            except (OSError, ValueError):
                candidates = ()
            if len(candidates) == 1:
                state = self._get_service_status(candidates[0])
            elif len(candidates) > 1:
                return VpnActionResult(
                    False,
                    "Найдено несколько VPN-подключений. Выбери нужное голосом перед подключением или отключением.",
                    "ambiguous",
                )
        if state == "running":
            return VpnActionResult(True, "VPN включён.", state)
        if state == "stopped":
            return VpnActionResult(True, "VPN выключен.", state)
        if state == "not_found":
            return VpnActionResult(
                False,
                "Служба VPN не найдена. Проверь VPN_TUNNEL_SERVICE_NAME в .env.",
                state,
            )

        return VpnActionResult(False, "Не удалось узнать статус VPN.", state)

    def connect(self) -> VpnActionResult:
        if not self.settings.vpn_enabled:
            return VpnActionResult(False, "VPN-команды отключены в настройках.", "disabled")

        state = self._get_service_status(self.tunnel_service)
        if state == "running":
            return VpnActionResult(True, "VPN уже включён.", state)
        if state == "not_found":
            return VpnActionResult(
                False,
                "Служба VPN не найдена. Проверь VPN_TUNNEL_SERVICE_NAME в .env.",
                state,
            )

        result = self._set_service_state(self.tunnel_service, desired="running")
        if result.ok:
            return VpnActionResult(True, "VPN включён.", "running")
        return result

    def disconnect(self) -> VpnActionResult:
        if not self.settings.vpn_enabled:
            return VpnActionResult(False, "VPN-команды отключены в настройках.", "disabled")

        state = self._get_service_status(self.tunnel_service)
        if state == "stopped":
            return VpnActionResult(True, "VPN уже выключен.", state)
        if state == "not_found":
            return VpnActionResult(
                False,
                "Служба VPN не найдена. Проверь VPN_TUNNEL_SERVICE_NAME в .env.",
                state,
            )

        result = self._set_service_state(self.tunnel_service, desired="stopped")
        if result.ok:
            return VpnActionResult(True, "VPN выключен.", "stopped")
        return result

    def _get_service_status(self, service_name: str) -> str:
        try:
            return self._services().query_status(service_name)
        except WindowsServiceError as exc:
            self.logger.warning(
                "VPN status query failed: code=%s",
                exc.error_code,
            )
            if exc.error_code == WindowsServiceControl.ERROR_SERVICE_DOES_NOT_EXIST:
                return "not_found"
            return "unknown"
        except (OSError, ValueError):
            self.logger.warning("VPN status query failed")
            return "unknown"

    def _set_service_state(
        self,
        service_name: str,
        desired: Literal["running", "stopped"],
    ) -> VpnActionResult:
        try:
            output = self._services().set_state(
                service_name=service_name,
                desired=desired,
                timeout_seconds=self.timeout_seconds,
            )
        except WindowsServiceError as exc:
            self.logger.warning(
                "VPN service state change failed: desired=%s code=%s",
                desired,
                exc.error_code,
            )
            if exc.error_code == WindowsServiceControl.ERROR_ACCESS_DENIED:
                return VpnActionResult(
                    False,
                    "Не удалось изменить VPN. Запусти Астру от имени администратора.",
                    "access_denied",
                )
            if exc.error_code == WindowsServiceControl.ERROR_SERVICE_DOES_NOT_EXIST:
                return VpnActionResult(
                    False,
                    "Служба VPN не найдена. Проверь VPN_TUNNEL_SERVICE_NAME в .env.",
                    "not_found",
                )
            return VpnActionResult(
                False,
                "Не удалось изменить VPN. Подробности смотри в logs/app.log.",
                "unknown",
            )
        except (OSError, ValueError):
            self.logger.warning(
                "VPN service state change failed: desired=%s",
                desired,
            )
            return VpnActionResult(
                False,
                "Не удалось изменить VPN. Подробности смотри в logs/app.log.",
                "unknown",
            )

        if output == desired:
            self.logger.info(
                "VPN service state change: desired=%s result=%s",
                desired,
                output,
            )
            return VpnActionResult(True, "Готово.", desired)
        self.logger.warning(
            "VPN service state transition incomplete: desired=%s result=%s",
            desired,
            output,
        )
        return VpnActionResult(
            False,
            "Не удалось изменить VPN. Подробности смотри в logs/app.log.",
            output or "unknown",
        )
