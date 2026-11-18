import ctypes
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.system_controller import (
    BatteryStatus,
    SystemController,
    _SystemPowerStatus,
    read_system_power_status,
)


class _FakeFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class SystemControllerTests(unittest.TestCase):
    def test_battery_reader_uses_win32_status_without_a_shell(self):
        def fill_status(pointer):
            status = ctypes.cast(pointer, ctypes.POINTER(_SystemPowerStatus)).contents
            status.BatteryFlag = 8
            status.BatteryLifePercent = 73
            return 1

        kernel32 = SimpleNamespace(GetSystemPowerStatus=_FakeFunction(fill_status))
        self.assertEqual(
            read_system_power_status(kernel32),
            BatteryStatus(battery_flag=8, battery_life_percent=73),
        )
        self.assertEqual(
            SystemController(battery_reader=lambda: BatteryStatus(0, 73))._battery_info().message,
            "Заряд батареи 73 процентов.",
        )

    def test_battery_reader_reports_absent_and_unknown_batteries_honestly(self):
        no_battery = SystemController(
            battery_reader=lambda: BatteryStatus(0x80, 255)
        )._battery_info()
        unknown = SystemController(
            battery_reader=lambda: BatteryStatus(0, 255)
        )._battery_info()
        failed = SystemController(battery_reader=lambda: None)._battery_info()
        self.assertFalse(no_battery.ok)
        self.assertEqual(no_battery.message, "Батарея не найдена.")
        self.assertFalse(unknown.ok)
        self.assertEqual(unknown.message, "Уровень заряда батареи недоступен.")
        self.assertFalse(failed.ok)

    def test_screenshot_uses_injected_capture_and_checks_saved_file_size(self):
        capture = Mock()
        controller = SystemController(
            screenshot_capture=capture,
            home=Path("system-controller-test-home"),
        )
        with patch.object(Path, "mkdir"), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "stat", return_value=SimpleNamespace(st_size=1024)):
            result = controller.take_screenshot()

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "Скриншот сохранён.")
        capture.assert_called_once()
        self.assertEqual(
            capture.call_args.args[0].parent.name,
            "AstraScreenshots",
        )

    def test_screenshot_failure_never_claims_success(self):
        capture = Mock(side_effect=OSError("capture unavailable"))
        controller = SystemController(
            screenshot_capture=capture,
            home=Path("system-controller-failure-test-home"),
        )
        with patch.object(Path, "mkdir"):
            result = controller.take_screenshot()
        self.assertFalse(result.ok)
        self.assertEqual(result.message, "Не удалось сделать скриншот.")


if __name__ == "__main__":
    unittest.main()
