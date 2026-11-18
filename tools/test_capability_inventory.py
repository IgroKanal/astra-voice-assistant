import unittest
from unittest.mock import patch

from src.audio_device_discovery import AudioInputDevice
from src.capability_inventory import CapabilityInventory, discover_capability_inventory
from src.command_parser import CommandType, parse_command_text
from src.config_loader import AppConfig
from src.system_controller import SystemController
from src.system_discovery import BrowserDiscovery, RegisteredApplication
from src.network_adapter_discovery import NetworkAdapterInventory
from main import _WAKE_REQUIRED_TYPES


class CapabilityInventoryTests(unittest.TestCase):
    def test_inventory_counts_live_adapters_without_exposing_local_names(self):
        browser = AppConfig("browser_orbit", ["orbit"], [r"C:\Apps\orbit.exe"], "orbit.exe")
        installed = (RegisteredApplication("Private editor", r"C:\Apps\private.exe"),)
        devices = (AudioInputDevice(0, "a" * 64), AudioInputDevice(1, "b" * 64))
        with patch("src.capability_inventory.discover_registered_applications", return_value=installed), \
             patch("src.capability_inventory.discover_windows_browsers", return_value=BrowserDiscovery({"browser_orbit": browser}, "browser_orbit")), \
             patch("src.capability_inventory.discover_audio_inputs", return_value=devices), \
             patch("src.capability_inventory.discover_audio_outputs", return_value=(object(), object(), object())), \
             patch("src.capability_inventory.discover_network_adapter_inventory", return_value=NetworkAdapterInventory(4, 2)), \
             patch("src.capability_inventory.discover_vpn_tunnel_services", return_value=("WireGuardTunnel$private",)):
            inventory = discover_capability_inventory()

        self.assertEqual(inventory, CapabilityInventory(1, 1, True, 2, 3, 4, 2, 1))
        summary = inventory.describe()
        self.assertIn("приложений для запуска обнаружено: 1", summary)
        self.assertIn("входных аудиоустройств обнаружено: 2", summary)
        self.assertIn("выходных аудиоустройств обнаружено: 3", summary)
        self.assertIn("виртуальных адаптеров: 2", summary)
        self.assertIn("конкретный клиент не определён", summary)
        self.assertIn("системный браузер по умолчанию найден", summary)
        self.assertNotIn("Private editor", summary)
        self.assertNotIn("private.exe", summary)
        self.assertNotIn("WireGuardTunnel$private", summary)
        self.assertIn("не выдаёт разрешений", summary)

    def test_failed_discovery_source_is_reported_as_unknown_not_as_empty(self):
        with patch("src.capability_inventory.discover_registered_applications", side_effect=OSError), \
             patch("src.capability_inventory.discover_windows_browsers", side_effect=OSError), \
             patch("src.capability_inventory.discover_audio_inputs", return_value=()), \
             patch("src.capability_inventory.discover_audio_outputs", side_effect=OSError), \
             patch("src.capability_inventory.discover_network_adapter_inventory", return_value=None), \
             patch("src.capability_inventory.discover_vpn_tunnel_services", return_value=()):
            inventory = discover_capability_inventory()

        self.assertIsNone(inventory.registered_applications)
        self.assertIsNone(inventory.browsers)
        self.assertIsNone(inventory.system_default_browser)
        self.assertEqual(inventory.audio_inputs, 0)
        self.assertIsNone(inventory.audio_outputs)
        self.assertIn("устройств вывода звука прочитать не удалось", inventory.describe())
        self.assertIsNone(inventory.network_adapters)
        self.assertIsNone(inventory.virtual_network_adapters)
        self.assertEqual(inventory.supported_vpn_tunnels, 0)
        self.assertIn("список браузеров прочитать не удалось", inventory.describe())

    def test_inventory_query_is_a_system_info_command(self):
        for phrase in (
            "что доступно на этом компьютере",
            "что доступно на компьютере",
            "какие возможности доступны",
            "какие устройства обнаружены",
        ):
            parsed = parse_command_text(phrase)
            self.assertEqual(parsed.type, CommandType.SYSTEM_INFO)
            self.assertEqual(parsed.target, "capabilities")
            self.assertIn(parsed.type, _WAKE_REQUIRED_TYPES)

    def test_system_controller_runs_snapshot_only_when_asked(self):
        calls = []
        controller = SystemController(
            capability_summary=lambda: calls.append(True) or "snapshot"
        )
        result = controller.system_info("capabilities")
        self.assertTrue(result.ok)
        self.assertEqual(result.message, "snapshot")
        self.assertEqual(calls, [True])

    def test_unavailable_snapshot_does_not_break_other_system_queries(self):
        controller = SystemController()
        result = controller.system_info("capabilities")
        self.assertFalse(result.ok)
        self.assertIn("недоступна", result.message)


if __name__ == "__main__":
    unittest.main()
