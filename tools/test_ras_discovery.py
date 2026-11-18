import ctypes
import unittest
from unittest.mock import patch

from src.ras_discovery import (
    _RasEntryNameW,
    _enumerate_native_ras_entries,
    discover_windows_ras_profile_names,
)


class RasDiscoveryTests(unittest.TestCase):
    def test_names_are_bounded_deduplicated_and_not_assumed_to_be_vpns(self):
        names = discover_windows_ras_profile_names(
            enumerator=lambda: (
                " Office VPN ", "office vpn", "Legacy dial-up", "", "bad\nname",
                "x" * 257, None,
            )
        )
        self.assertEqual(names, ("Office VPN", "Legacy dial-up"))

    def test_failure_is_unknown_not_an_empty_inventory(self):
        def fail():
            raise OSError("unavailable")

        self.assertIsNone(discover_windows_ras_profile_names(enumerator=fail))
        self.assertIsNone(discover_windows_ras_profile_names(enumerator=lambda: None))

    def test_unbounded_or_malformed_provider_result_is_rejected(self):
        too_many = tuple("entry" for _ in range(4097))
        self.assertIsNone(discover_windows_ras_profile_names(enumerator=lambda: too_many))
        self.assertIsNone(discover_windows_ras_profile_names(enumerator=lambda: "not a sequence"))

    @patch("src.ras_discovery.os.name", "posix")
    @patch("src.ras_discovery._enumerate_native_ras_entries")
    def test_native_discovery_is_not_attempted_off_windows(self, native):
        self.assertIsNone(discover_windows_ras_profile_names())
        native.assert_not_called()

    def test_rasman_probe_queries_only_status_and_closes_service_handles(self):
        from src import ras_discovery

        calls = []
        closed = []

        class FakeFunction:
            def __init__(self, handler):
                self.handler = handler
                self.argtypes = None
                self.restype = None

            def __call__(self, *args):
                return self.handler(*args)

        class FakeLibrary:
            pass

        def query_status(_service, status_pointer):
            status = ctypes.cast(
                status_pointer, ctypes.POINTER(ras_discovery._ServiceStatus)
            ).contents
            status.dwCurrentState = 4
            calls.append(("query",))
            return 1

        library = FakeLibrary()
        library.OpenSCManagerW = FakeFunction(
            lambda *args: calls.append(("manager",) + args) or 10
        )
        library.OpenServiceW = FakeFunction(
            lambda *args: calls.append(("service",) + args) or 20
        )
        library.QueryServiceStatus = FakeFunction(query_status)
        library.CloseServiceHandle = FakeFunction(
            lambda handle: closed.append(handle) or 1
        )

        with patch.object(ras_discovery.os, "name", "nt"), \
             patch.object(ras_discovery.ctypes, "WinDLL", return_value=library, create=True):
            self.assertTrue(ras_discovery._rasman_is_running())

        self.assertEqual(calls[0], ("manager", None, None, 1))
        self.assertEqual(calls[1], ("service", 10, "RasMan", 4))
        self.assertEqual(closed, [20, 10])

    @unittest.skipUnless(ctypes.sizeof(ctypes.c_wchar) == 2, "Windows UTF-16 structure layout")
    @patch("src.ras_discovery._rasman_is_running", return_value=False)
    @patch("src.ras_discovery.ctypes.WinDLL")
    def test_does_not_load_ras_api_when_rasman_is_stopped(self, load_library, _running):
        from src.ras_discovery import _enumerate_native_ras_entries

        self.assertIsNone(_enumerate_native_ras_entries())
        load_library.assert_not_called()

    @unittest.skipUnless(ctypes.sizeof(ctypes.c_wchar) == 2, "Windows UTF-16 structure layout")
    def test_native_enumerator_uses_two_bounded_read_only_calls(self):
        from src import ras_discovery

        class FakeFunction:
            def __init__(self):
                self.argtypes = None
                self.restype = None
                self.calls = 0

            def __call__(self, reserved, phonebook, entries, buffer_bytes, entry_count):
                self.calls += 1
                self.assert_null_arguments(reserved, phonebook)
                size = ctypes.cast(buffer_bytes, ctypes.POINTER(ctypes.c_uint32))
                count = ctypes.cast(entry_count, ctypes.POINTER(ctypes.c_uint32))
                if entries is None:
                    size.contents.value = ctypes.sizeof(_RasEntryNameW) * 2
                    count.contents.value = 2
                    return 603
                count.contents.value = 2
                entries[0].szEntryName = "Office VPN"
                entries[1].szEntryName = "Legacy dial-up"
                return 0

            @staticmethod
            def assert_null_arguments(reserved, phonebook):
                if reserved is not None or phonebook is not None:
                    raise AssertionError("the default RAS phonebook must be used")

        class FakeLibrary:
            pass

        function = FakeFunction()
        library = FakeLibrary()
        library.RasEnumEntriesW = function
        with patch.object(ras_discovery, "_rasman_is_running", return_value=True), \
             patch.object(ras_discovery.ctypes, "WinDLL", return_value=library):
            self.assertEqual(
                _enumerate_native_ras_entries(),
                ("Office VPN", "Legacy dial-up"),
            )
        self.assertEqual(function.calls, 2)
        self.assertTrue(function.argtypes)


if __name__ == "__main__":
    unittest.main()
