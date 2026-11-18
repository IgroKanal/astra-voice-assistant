from __future__ import annotations

import ctypes
import logging
import os
import shutil
import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class SystemActionResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class BatteryStatus:
    battery_flag: int
    battery_life_percent: int


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("Reserved1", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_uint32),
        ("BatteryFullLifeTime", ctypes.c_uint32),
    ]


def read_system_power_status(kernel32: object | None = None) -> BatteryStatus | None:
    """Read the current battery percentage with GetSystemPowerStatus only."""
    if kernel32 is None:
        if os.name != "nt":
            return None
        try:
            kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        except (AttributeError, OSError):
            return None
    try:
        get_status = getattr(kernel32, "GetSystemPowerStatus")
        get_status.argtypes = (ctypes.POINTER(_SystemPowerStatus),)
        get_status.restype = ctypes.c_int
        status = _SystemPowerStatus()
        if not get_status(ctypes.byref(status)):
            return None
        return BatteryStatus(status.BatteryFlag, status.BatteryLifePercent)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _capture_primary_screen(output_path: Path) -> None:
    """Capture the primary display through Win32/Pillow without a shell."""
    if os.name != "nt":
        raise OSError("Screen capture is available only on Windows")
    user32 = ctypes.WinDLL("user32.dll", use_last_error=True)
    get_system_metrics = user32.GetSystemMetrics
    get_system_metrics.argtypes = (ctypes.c_int,)
    get_system_metrics.restype = ctypes.c_int
    width = int(get_system_metrics(0))  # SM_CXSCREEN
    height = int(get_system_metrics(1))  # SM_CYSCREEN
    if not 0 < width <= 16_384 or not 0 < height <= 16_384:
        raise OSError("Primary display dimensions are unavailable")
    if width * height > 40_000_000:
        raise OSError("Primary display exceeds the screenshot size limit")

    from PIL import ImageGrab

    image = ImageGrab.grab(bbox=(0, 0, width, height))
    try:
        image.save(str(output_path), format="PNG")
    finally:
        image.close()


class SystemController:
    """Безопасные системные действия: скриншот и краткая информация о ПК."""

    def __init__(
        self,
        logger: logging.Logger | None = None,
        capability_summary: Callable[[], str] | None = None,
        *,
        battery_reader: Callable[[], BatteryStatus | None] = read_system_power_status,
        screenshot_capture: Callable[[Path], None] = _capture_primary_screen,
        home: Path | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.home = Path(home) if home is not None else Path.home()
        self.capability_summary = capability_summary
        self.battery_reader = battery_reader
        self.screenshot_capture = screenshot_capture

    def take_screenshot(self) -> SystemActionResult:
        screenshots_dir = self.home / "Pictures" / "AstraScreenshots"
        filename = f"astra_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
        output_path = screenshots_dir / filename
        try:
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            self.screenshot_capture(output_path)
            size = output_path.stat().st_size if output_path.is_file() else 0
            if not 1 <= size <= 256 * 1024 * 1024:
                raise OSError("Screenshot output is missing or outside the size limit")
            self.logger.info("Screenshot saved")
            return SystemActionResult(True, "Скриншот сохранён.")
        except Exception as exc:
            self.logger.warning("Screenshot failed: %s", type(exc).__name__)
            return SystemActionResult(False, "Не удалось сделать скриншот.")

    def system_info(self, target: str) -> SystemActionResult:
        target = (target or "summary").strip().lower()

        if target == "battery":
            return self._battery_info()
        if target == "memory":
            return self._memory_info()
        if target == "disk":
            return self._disk_info()
        if target == "internet":
            return self._internet_info()
        if target == "capabilities":
            return self._capability_info()

        parts = [self._memory_info().message, self._disk_info().message]
        battery = self._battery_info()
        if battery.ok:
            parts.append(battery.message)
        return SystemActionResult(True, " ".join(parts))

    def _capability_info(self) -> SystemActionResult:
        if not callable(self.capability_summary):
            return SystemActionResult(False, "Инвентаризация возможностей недоступна.")
        try:
            message = self.capability_summary()
        except Exception as exc:
            self.logger.warning(
                "Capability inventory failed: %s", type(exc).__name__
            )
            return SystemActionResult(False, "Не удалось проверить возможности этого компьютера.")
        if not isinstance(message, str) or not 1 <= len(message) <= 2000:
            return SystemActionResult(False, "Инвентаризация возможностей вернула некорректный ответ.")
        return SystemActionResult(True, message)

    def _battery_info(self) -> SystemActionResult:
        try:
            status = self.battery_reader()
        except Exception:
            self.logger.exception("Battery status query failed")
            return SystemActionResult(False, "Не удалось узнать заряд батареи.")
        if status is None:
            return SystemActionResult(False, "Не удалось узнать заряд батареи.")
        if status.battery_flag & 0x80:
            return SystemActionResult(False, "Батарея не найдена.")
        if not 0 <= status.battery_life_percent <= 100:
            return SystemActionResult(False, "Уровень заряда батареи недоступен.")
        return SystemActionResult(
            True,
            f"Заряд батареи {status.battery_life_percent} процентов.",
        )

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


    def _internet_info(self) -> SystemActionResult:
        checks = (
            ("1.1.1.1", 53),
            ("8.8.8.8", 53),
        )

        for host, port in checks:
            try:
                with socket.create_connection((host, port), timeout=2.0):
                    return SystemActionResult(True, "Интернет доступен.")
            except OSError:
                continue

        return SystemActionResult(False, "Интернет не отвечает.")

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
