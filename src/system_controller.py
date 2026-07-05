from __future__ import annotations

import base64
import ctypes
import logging
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SystemActionResult:
    ok: bool
    message: str


class SystemController:
    """Безопасные системные действия: скриншот и краткая информация о ПК."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.home = Path.home()

    def take_screenshot(self) -> SystemActionResult:
        screenshots_dir = self.home / "Pictures" / "AstraScreenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        filename = f"astra_{datetime.now():%Y%m%d_%H%M%S}.png"
        output_path = screenshots_dir / filename

        # Path is embedded as Base64 inside the script. This avoids the old
        # PowerShell `$args[0]` bug where the path was empty and Bitmap.Save failed.
        path_b64 = base64.b64encode(str(output_path).encode("utf-8")).decode("ascii")

        script = rf"""
$ErrorActionPreference = 'Stop'
$path = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{path_b64}'))

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap ([int]$bounds.Width), ([int]$bounds.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)

try {{
    $graphics.CopyFromScreen($bounds.Left, $bounds.Top, 0, 0, $bounds.Size)
    $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
}} finally {{
    $graphics.Dispose()
    $bitmap.Dispose()
}}
"""
        result = self._run_powershell_encoded(script, timeout=10)
        if result.ok and output_path.exists():
            self.logger.info("Скриншот сохранён: %s", output_path)
            return SystemActionResult(True, "Скриншот сохранён.")

        self.logger.warning("Screenshot failed: %s", result.message)
        return SystemActionResult(False, "Не удалось сделать скриншот.")

    def system_info(self, target: str) -> SystemActionResult:
        target = (target or "summary").strip().lower()

        if target == "battery":
            return self._battery_info()
        if target == "memory":
            return self._memory_info()
        if target == "disk":
            return self._disk_info()

        parts = [self._memory_info().message, self._disk_info().message]
        battery = self._battery_info()
        if battery.ok:
            parts.append(battery.message)
        return SystemActionResult(True, " ".join(parts))

    def _battery_info(self) -> SystemActionResult:
        script = r"""
$ErrorActionPreference = 'Stop'
$battery = Get-CimInstance Win32_Battery | Select-Object -First 1
if ($null -eq $battery) {
    Write-Output 'NO_BATTERY'
} else {
    Write-Output $battery.EstimatedChargeRemaining
}
"""
        result = self._run_powershell(script, timeout=5)
        if not result.ok:
            return SystemActionResult(False, "Не удалось узнать заряд батареи.")

        value = result.message.strip()
        if value == "NO_BATTERY" or not value:
            return SystemActionResult(False, "Батарея не найдена.")

        return SystemActionResult(True, f"Заряд батареи {value} процентов.")

    def _memory_info(self) -> SystemActionResult:
        try:
            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            if not ok:
                return SystemActionResult(False, "Не удалось узнать память.")

            total_gb = status.ullTotalPhys / (1024**3)
            free_gb = status.ullAvailPhys / (1024**3)
            used_percent = status.dwMemoryLoad
            return SystemActionResult(
                True,
                f"Память занята на {used_percent} процентов. Свободно примерно {free_gb:.1f} из {total_gb:.1f} гигабайт.",
            )
        except Exception:
            self.logger.exception("Memory info failed")
            return SystemActionResult(False, "Не удалось узнать память.")

    def _disk_info(self) -> SystemActionResult:
        try:
            root = Path.home().anchor or "C:\\"
            total, used, free = shutil.disk_usage(root)
            total_gb = total / (1024**3)
            free_gb = free / (1024**3)
            return SystemActionResult(
                True,
                f"На диске {root} свободно примерно {free_gb:.0f} из {total_gb:.0f} гигабайт.",
            )
        except Exception:
            self.logger.exception("Disk info failed")
            return SystemActionResult(False, "Не удалось узнать место на диске.")

    def _run_powershell(self, script: str, timeout: int) -> SystemActionResult:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            output = (result.stdout or result.stderr or "").strip()
            if result.returncode == 0:
                return SystemActionResult(True, output)
            return SystemActionResult(False, output)
        except subprocess.TimeoutExpired:
            return SystemActionResult(False, "PowerShell timeout")
        except OSError as exc:
            return SystemActionResult(False, str(exc))

    def _run_powershell_encoded(self, script: str, timeout: int) -> SystemActionResult:
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            output = (result.stdout or result.stderr or "").strip()
            if result.returncode == 0:
                return SystemActionResult(True, output)
            return SystemActionResult(False, output)
        except subprocess.TimeoutExpired:
            return SystemActionResult(False, "PowerShell timeout")
        except OSError as exc:
            return SystemActionResult(False, str(exc))


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]
