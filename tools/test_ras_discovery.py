import ctypes
import unittest
from unittest.mock import patch

from src.ras_discovery import (
    _RasEntryNameW,
    _RasEntryW,
    _RasConnW,
    _create_ras_entry_type_reader,
    _enumerate_native_ras_connections,
    _enumerate_native_ras_entries,
    discover_windows_ras_active_vpn_profile_names,
    discover_windows_ras_vpn_profile_names,
    discover_windows_ras_profile_names,
)


class RasDiscoveryTests(unittest.TestCase):
    def test_rasentry_vpn_type_offset_matches_windows_sdk_layout(self):
        self.assertEqual(_RasEntryW.dwType.offset, 3496)
        self.assertEqual(ctypes.sizeof(_RasEntryW), 6724)

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

    @unittest.skipUnless(ctypes.sizeof(ctypes.c_wchar) == 2, "Windows UTF-16 structure layout")
    def test_active_connection_enumerator_uses_bounded_read_only_calls(self):
        from src import ras_discovery

        class FakeFunction:
            def __init__(self):
                self.argtypes = None
                self.restype = None
                self.calls = 0

            def __call__(self, connections, buffer_bytes, connection_count):
                self.calls += 1
                size = ctypes.cast(
                    buffer_bytes, ctypes.POINTER(ctypes.c_uint32)
                )
                count = ctypes.cast(
                    connection_count, ctypes.POINTER(ctypes.c_uint32)
                )
                if connections is None:
                    size.contents.value = ctypes.sizeof(_RasConnW) * 2
                    count.contents.value = 2
                    return ras_discovery._ERROR_BUFFER_TOO_SMALL
                count.contents.value = 2
                connections[0].szEntryName = "Office VPN"
                connections[0].szPhonebook = r"C:\Users\example\rasphone.pbk"
                connections[1].szEntryName = "Legacy dial-up"
                connections[1].szPhonebook = r"C:\Users\example\rasphone.pbk"
                return ras_discovery._ERROR_SUCCESS

        class FakeLibrary:
            pass

        function = FakeFunction()
        library = FakeLibrary()
        library.RasEnumConnectionsW = function
        with patch.object(ras_discovery, "_rasman_is_running", return_value=True), \
             patch.object(ras_discovery.ctypes, "WinDLL", return_value=library):
            self.assertEqual(
                _enumerate_native_ras_connections(),
                (
                    ("Office VPN", r"C:\Users\example\rasphone.pbk"),
                    ("Legacy dial-up", r"C:\Users\example\rasphone.pbk"),
                ),
            )
        self.assertEqual(function.calls, 2)
        self.assertTrue(function.argtypes)

    def test_vpn_profile_discovery_classifies_type_and_does_not_report_names(self):
        records = (
            ("Office VPN", r"C:\Users\example\rasphone.pbk"),
            ("Legacy dial-up", r"C:\Users\example\rasphone.pbk"),
            ("office vpn", r"C:\Users\example\rasphone.pbk"),
        )
        calls = []

        def read_type(phonebook_path, entry_name):
            calls.append((phonebook_path, entry_name))
            return 2 if entry_name == "Office VPN" else 1

        names = discover_windows_ras_vpn_profile_names(
            entries_enumerator=lambda: records,
            type_reader=read_type,
        )
        self.assertEqual(names, ("Office VPN",))
        self.assertEqual(len(calls), 2)

    def test_vpn_profile_unknown_type_makes_snapshot_unknown(self):
        records = (("Office VPN", r"C:\Users\example\rasphone.pbk"),)
        self.assertIsNone(discover_windows_ras_vpn_profile_names(
            entries_enumerator=lambda: records,
            type_reader=lambda _path, _name: None,
        ))

    def test_active_vpn_discovery_classifies_only_active_profile_records(self):
        phonebook = r"C:\Users\example\rasphone.pbk"
        records = (
            ("Office VPN", phonebook),
            ("Legacy dial-up", phonebook),
            ("office vpn", phonebook),
            (".5550100", ""),
        )
        calls = []

        def read_type(path, name):
            calls.append((path, name))
            return 2 if name.casefold() == "office vpn" else 1

        self.assertEqual(
            discover_windows_ras_active_vpn_profile_names(
                connections_enumerator=lambda: records,
                type_reader=read_type,
            ),
            ("Office VPN",),
        )
        self.assertEqual(calls, [(phonebook, "Office VPN"), (phonebook, "Legacy dial-up")])

    def test_active_vpn_discovery_keeps_empty_and_failed_states_distinct(self):
        self.assertEqual(
            discover_windows_ras_active_vpn_profile_names(
                connections_enumerator=lambda: (),
            ),
            (),
        )
        self.assertIsNone(
            discover_windows_ras_active_vpn_profile_names(
                connections_enumerator=lambda: None,
            )
        )
        self.assertIsNone(
            discover_windows_ras_active_vpn_profile_names(
                connections_enumerator=lambda: (("Office VPN", r"\\server\share\rasphone.pbk"),),
                type_reader=lambda *_args: 2,
            )
        )
        too_many = tuple(
            (f"entry-{index}", r"C:\Users\example\rasphone.pbk")
            for index in range(129)
        )
        self.assertIsNone(
            discover_windows_ras_active_vpn_profile_names(
                connections_enumerator=lambda: too_many,
                type_reader=lambda *_args: 2,
            )
        )

    @unittest.skipUnless(ctypes.sizeof(ctypes.c_wchar) == 2, "Windows UTF-16 structure layout")
    @patch("src.ras_discovery._rasman_is_running", return_value=False)
    @patch("src.ras_discovery.ctypes.WinDLL")
    def test_active_connection_enumerator_does_not_load_ras_api_when_rasman_is_stopped(
        self, load_library, _running
    ):
        self.assertIsNone(_enumerate_native_ras_connections())
        load_library.assert_not_called()

    def test_duplicate_names_in_separate_phonebooks_are_classified_separately(self):
        records = (
            ("Private", r"C:\Users\example\first.pbk"),
            ("Private", r"C:\Users\example\second.pbk"),
        )
        seen_paths = []

        def read_type(phonebook_path, _entry_name):
            seen_paths.append(phonebook_path)
            return 2 if phonebook_path.endswith("second.pbk") else 1

        self.assertEqual(
            discover_windows_ras_vpn_profile_names(
                entries_enumerator=lambda: records,
                type_reader=read_type,
            ),
            ("Private",),
        )
        self.assertEqual(seen_paths, [records[0][1], records[1][1]])

    def test_type_query_limit_and_remote_phonebook_fail_closed(self):
        calls = []
        excessive = tuple(
            (f"entry-{index}", r"C:\Users\example\rasphone.pbk")
            for index in range(129)
        )
        self.assertIsNone(discover_windows_ras_vpn_profile_names(
            entries_enumerator=lambda: excessive,
            type_reader=lambda *_args: calls.append(True) or 2,
        ))
        self.assertEqual(calls, [])

        self.assertIsNone(discover_windows_ras_vpn_profile_names(
            entries_enumerator=lambda: (("remote", r"\\server\share\rasphone.pbk"),),
            type_reader=lambda *_args: calls.append(True) or 2,
        ))
        self.assertEqual(calls, [])

    def test_empty_vpn_profile_inventory_does_not_require_type_reader(self):
        self.assertEqual(discover_windows_ras_vpn_profile_names(
            entries_enumerator=lambda: (),
        ), ())

    def test_rasentry_type_reader_retries_only_bounded_buffer_growth(self):
        from src import ras_discovery

        calls = []

        class FakeFunction:
            argtypes = None
            restype = None

            def __call__(self, phonebook_path, entry_name, entry_pointer,
                         buffer_size_pointer, device_info, device_size):
                calls.append((phonebook_path, entry_name, device_info, device_size))
                buffer_size = ctypes.cast(
                    buffer_size_pointer, ctypes.POINTER(ctypes.c_uint32)
                ).contents
                entry = ctypes.cast(
                    entry_pointer, ctypes.POINTER(ras_discovery._RasEntryW)
                ).contents
                if len(calls) == 1:
                    buffer_size.value = ctypes.sizeof(_RasEntryW) + 128
                    return ras_discovery._ERROR_BUFFER_TOO_SMALL
                entry.dwType = ras_discovery._RASET_VPN
                return ras_discovery._ERROR_SUCCESS

        class FakeLibrary:
            RasGetEntryPropertiesW = FakeFunction()

        real_sizeof = ctypes.sizeof

        def windows_sizeof(value):
            if value is ctypes.c_wchar:
                return 2
            return real_sizeof(value)

        with patch.object(ras_discovery.os, "name", "nt"), \
             patch.object(ras_discovery, "_rasman_is_running", return_value=True), \
             patch.object(ras_discovery.ctypes, "sizeof", side_effect=windows_sizeof), \
             patch.object(ras_discovery.ctypes, "WinDLL", return_value=FakeLibrary(), create=True):
            reader = _create_ras_entry_type_reader()
            self.assertIsNotNone(reader)
            self.assertEqual(
                reader(r"C:\Users\example\rasphone.pbk", "Office VPN"), 2
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0:2], (r"C:\Users\example\rasphone.pbk", "Office VPN"))
        self.assertEqual(calls[0][2:], (None, None))


if __name__ == "__main__":
    unittest.main()
