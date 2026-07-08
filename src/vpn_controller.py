from __future__ import annotations

import base64
import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Literal

from src.config_loader import Settings


@dataclass(frozen=True)
class VpnActionResult:
    ok: bool
    message: str
    status: str = "unknown"


class VpnController:
    """Безопасное управление AmneziaWG через Windows service control.

    v0.10.0:
    - не кликает по координатам;
    - не выполняет команды из речи пользователя;
    - работает только с заранее заданной службой VPN из .env;
    - требует прав администратора, если Windows требует их для Start/Stop-Service.
    """

    def __init__(self, settings: Settings, logger: logging.Logger | None = None) -> None:
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self.tunnel_service = settings.vpn_tunnel_service_name.strip()
        self.manager_service = settings.vpn_manager_service_name.strip()
        self.timeout_seconds = max(3.0, settings.vpn_command_timeout_seconds)

    def status(self) -> VpnActionResult:
        if not self.settings.vpn_enabled:
            return VpnActionResult(False, "VPN-команды отключены в настройках.", "disabled")

        state = self._get_service_status(self.tunnel_service)
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

    def _clean_powershell_stream(self, value: str) -> str:
        clean = (value or "").strip()
        if not clean:
            return ""

        # PowerShell can write CLIXML progress records to stderr even when
        # the command succeeds. That noise makes logs huge and unreadable.
        if clean.startswith("#< CLIXML"):
            return ""

        return clean

    def _get_service_status(self, service_name: str) -> str:
        script = self._service_status_script(service_name)
        result = self._run_powershell(script, timeout=5)
        output = self._clean_powershell_stream(result.stdout).lower()
        error = self._clean_powershell_stream(result.stderr)

        if result.returncode != 0:
            self.logger.warning(
                "VPN status query failed: service=%s code=%s stdout=%r stderr=%r",
                service_name,
                result.returncode,
                output,
                error,
            )
            if "cannot find" in error.lower() or "не удается найти" in error.lower():
                return "not_found"
            return "unknown"

        if output in {"running", "stopped", "startpending", "stoppending", "paused"}:
            return output
        return output or "unknown"

    def _set_service_state(
        self,
        service_name: str,
        desired: Literal["running", "stopped"],
    ) -> VpnActionResult:
        script = self._service_set_state_script(
            service_name=service_name,
            desired=desired,
            timeout_seconds=self.timeout_seconds,
        )
        result = self._run_powershell(script, timeout=int(self.timeout_seconds) + 5)
        output = self._clean_powershell_stream(result.stdout).lower()
        error = self._clean_powershell_stream(result.stderr)

        if result.returncode == 0 and output == desired:
            self.logger.info(
                "VPN service state change: service=%s desired=%s result=%s",
                service_name,
                desired,
                output,
            )
        else:
            self.logger.warning(
                "VPN service state change failed: service=%s desired=%s code=%s stdout=%r stderr=%r",
                service_name,
                desired,
                result.returncode,
                output,
                error,
            )

        if result.returncode == 0 and output == desired:
            return VpnActionResult(True, "Готово.", desired)

        if "access" in error.lower() or "denied" in error.lower() or "отказано" in error.lower():
            return VpnActionResult(
                False,
                "Не удалось изменить VPN. Запусти Астру от имени администратора.",
                "access_denied",
            )

        if "cannot find" in error.lower() or "не удается найти" in error.lower():
            return VpnActionResult(
                False,
                "Служба VPN не найдена. Проверь VPN_TUNNEL_SERVICE_NAME в .env.",
                "not_found",
            )

        return VpnActionResult(
            False,
            "Не удалось изменить VPN. Подробности смотри в logs/app.log.",
            output or "unknown",
        )

    def _run_powershell(self, script: str, timeout: int) -> subprocess.CompletedProcess[str]:
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ]
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _service_status_script(self, service_name: str) -> str:
        encoded_name = base64.b64encode(service_name.encode("utf-8")).decode("ascii")
        return f"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$name = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{encoded_name}'))
$svc = Get-Service -Name $name -ErrorAction Stop
[Console]::Write($svc.Status.ToString())
"""

    def _service_set_state_script(
        self,
        service_name: str,
        desired: Literal["running", "stopped"],
        timeout_seconds: float,
    ) -> str:
        encoded_name = base64.b64encode(service_name.encode("utf-8")).decode("ascii")
        action = "Start-Service" if desired == "running" else "Stop-Service"
        return f"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$name = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{encoded_name}'))
$desired = '{desired}'
$svc = Get-Service -Name $name -ErrorAction Stop
if ($desired -eq 'running') {{
    if ($svc.Status -ne 'Running') {{ Start-Service -Name $name -ErrorAction Stop }}
}} else {{
    if ($svc.Status -ne 'Stopped') {{ Stop-Service -Name $name -ErrorAction Stop }}
}}
$deadline = (Get-Date).AddSeconds({timeout_seconds})
do {{
    Start-Sleep -Milliseconds 300
    $svc = Get-Service -Name $name -ErrorAction Stop
    $current = $svc.Status.ToString().ToLowerInvariant()
}} while ($current -ne $desired -and (Get-Date) -lt $deadline)
[Console]::Write($current)
"""
