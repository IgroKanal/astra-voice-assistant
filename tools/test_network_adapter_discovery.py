import unittest

from src.network_adapter_discovery import (
    NetworkAdapterInventory,
    discover_network_adapter_inventory,
)


_BASE = r"SYSTEM\CurrentControlSet\Control\Class\{4D36E972-E325-11CE-BFC1-08002BE10318}"


class FakeRegistry:
    HKEY_LOCAL_MACHINE = "HKLM"

    def __init__(self, entries):
        self.entries = entries
        self.closed = 0

    def OpenKey(self, root, path):
        if root == self.HKEY_LOCAL_MACHINE and path == _BASE:
            return "class-root"
        if root == "class-root" and path in self.entries:
            return path
        raise OSError("missing registry key")

    def EnumKey(self, key, index):
        if key != "class-root" or index >= len(self.entries):
            raise OSError("no more registry keys")
        return tuple(self.entries)[index]

    def QueryValueEx(self, key, name):
        try:
            return self.entries[key][name], 0
        except KeyError:
            raise OSError("missing registry value") from None

    def CloseKey(self, key):
        self.closed += 1


class NetworkAdapterDiscoveryTests(unittest.TestCase):
    def test_counts_network_and_virtual_adapters_without_exposing_guids(self):
        registry = FakeRegistry(
            {
                "0000": {"NetCfgInstanceId": "{11111111-1111-1111-1111-111111111111}", "Characteristics": 0x84},
                "0001": {"NetCfgInstanceId": "{22222222-2222-2222-2222-222222222222}", "Characteristics": 0x21},
                "0002": {"Description": "not an adapter instance"},
            }
        )

        inventory = discover_network_adapter_inventory(registry=registry)

        self.assertEqual(inventory, NetworkAdapterInventory(2, 1))
        self.assertNotIn("11111111", repr(inventory))
        self.assertEqual(registry.closed, 4)

    def test_missing_registry_is_unavailable_not_an_empty_computer(self):
        class MissingRegistry(FakeRegistry):
            def OpenKey(self, root, path):
                raise OSError("access denied")

        self.assertIsNone(discover_network_adapter_inventory(registry=MissingRegistry({})))

    def test_invalid_characteristics_fail_closed(self):
        registry = FakeRegistry(
            {
                "0000": {
                    "NetCfgInstanceId": "{11111111-1111-1111-1111-111111111111}",
                    "Characteristics": "1",
                }
            }
        )

        self.assertIsNone(discover_network_adapter_inventory(registry=registry))


if __name__ == "__main__":
    unittest.main()
