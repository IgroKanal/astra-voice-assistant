"""Read-only discovery of native Windows Remote Access Service profiles.

RAS phonebook entries can describe VPN or dial-up connections. This module
enumerates names only; it does not read credentials or change connection state.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import ntpath
import os
from typing import Callable


_ERROR_SUCCESS = 0
_ERROR_BUFFER_TOO_SMALL = 603
_MAX_RAS_ENTRY_NAME = 256
_MAX_RAS_ENTRIES = 4096
_MAX_RAS_TYPE_QUERIES = 128
_MAX_RAS_BUFFER = 4 * 1024 * 1024
_RASET_VPN = 2
_MAX_RAS_CONNECTIONS = 128


class _RasEntryNameW(ctypes.Structure):
    """RASENTRYNAMEW layout from the Windows RAS API."""

    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("szEntryName", ctypes.c_wchar * (_MAX_RAS_ENTRY_NAME + 1)),
        ("dwFlags", ctypes.c_uint32),
        ("szPhonebookPath", ctypes.c_wchar * 261),
    ]


class _RasIpAddress(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint8) for name in ("a", "b", "c", "d")]


class _Guid(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_uint8 * 8),
    ]


class _Luid(ctypes.Structure):
    _fields_ = [("low_part", ctypes.c_uint32), ("high_part", ctypes.c_int32)]


class _RasConnW(ctypes.Structure):
    """RASCONNW layout; discovery consumes only the entry and phonebook names."""

    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("hrasconn", ctypes.c_void_p),
        ("szEntryName", ctypes.c_wchar * (_MAX_RAS_ENTRY_NAME + 1)),
        ("szDeviceType", ctypes.c_wchar * 17),
        ("szDeviceName", ctypes.c_wchar * 129),
        ("szPhonebook", ctypes.c_wchar * 261),
        ("dwSubEntry", ctypes.c_uint32),
        ("guidEntry", _Guid),
        ("dwFlags", ctypes.c_uint32),
        ("luid", _Luid),
        ("guidCorrelationId", _Guid),
    ]


class _RasEntryW(ctypes.Structure):
    """Current RASENTRYW ABI, mirroring the Windows SDK's ras.h layout.

    WCHAR is explicitly UTF-16 here so the structure layout can be checked on
    non-Windows test hosts too. Only ``dwType`` is consumed; the other fields
    exist solely to pass the documented structure size to RasGetEntryPropertiesW.
    """

    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("dwfOptions", ctypes.c_uint32),
        ("dwCountryID", ctypes.c_uint32),
        ("dwCountryCode", ctypes.c_uint32),
        ("szAreaCode", ctypes.c_uint16 * 11),
        ("szLocalPhoneNumber", ctypes.c_uint16 * 129),
        ("dwAlternateOffset", ctypes.c_uint32),
        ("ipaddr", _RasIpAddress),
        ("ipaddrDns", _RasIpAddress),
        ("ipaddrDnsAlt", _RasIpAddress),
        ("ipaddrWins", _RasIpAddress),
        ("ipaddrWinsAlt", _RasIpAddress),
        ("dwFrameSize", ctypes.c_uint32),
        ("dwfNetProtocols", ctypes.c_uint32),
        ("dwFramingProtocol", ctypes.c_uint32),
        ("szScript", ctypes.c_uint16 * 260),
        ("szAutodialDll", ctypes.c_uint16 * 260),
        ("szAutodialFunc", ctypes.c_uint16 * 260),
        ("szDeviceType", ctypes.c_uint16 * 17),
        ("szDeviceName", ctypes.c_uint16 * 129),
        ("szX25PadType", ctypes.c_uint16 * 33),
        ("szX25Address", ctypes.c_uint16 * 201),
        ("szX25Facilities", ctypes.c_uint16 * 201),
        ("szX25UserData", ctypes.c_uint16 * 201),
        ("dwChannels", ctypes.c_uint32),
        ("dwReserved1", ctypes.c_uint32),
        ("dwReserved2", ctypes.c_uint32),
        ("dwSubEntries", ctypes.c_uint32),
        ("dwDialMode", ctypes.c_uint32),
        ("dwDialExtraPercent", ctypes.c_uint32),
        ("dwDialExtraSampleSeconds", ctypes.c_uint32),
        ("dwHangUpExtraPercent", ctypes.c_uint32),
        ("dwHangUpExtraSampleSeconds", ctypes.c_uint32),
        ("dwIdleDisconnectSeconds", ctypes.c_uint32),
        ("dwType", ctypes.c_uint32),
        ("dwEncryptionType", ctypes.c_uint32),
        ("dwCustomAuthKey", ctypes.c_uint32),
        ("guidId", _Guid),
        ("szCustomDialDll", ctypes.c_uint16 * 260),
        ("dwVpnStrategy", ctypes.c_uint32),
        ("dwfOptions2", ctypes.c_uint32),
        ("dwfOptions3", ctypes.c_uint32),
        ("szDnsSuffix", ctypes.c_uint16 * 256),
        ("dwTcpWindowSize", ctypes.c_uint32),
        ("szPrerequisitePbk", ctypes.c_uint16 * 260),
        ("szPrerequisiteEntry", ctypes.c_uint16 * 257),
        ("dwRedialCount", ctypes.c_uint32),
        ("dwRedialPause", ctypes.c_uint32),
        ("ipv6addrDns", ctypes.c_uint8 * 16),
        ("ipv6addrDnsAlt", ctypes.c_uint8 * 16),
        ("dwIPv4InterfaceMetric", ctypes.c_uint32),
        ("dwIPv6InterfaceMetric", ctypes.c_uint32),
        ("ipv6addr", ctypes.c_uint8 * 16),
        ("dwIPv6PrefixLength", ctypes.c_uint32),
        ("dwNetworkOutageTime", ctypes.c_uint32),
        ("szIDi", ctypes.c_uint16 * 257),
        ("szIDr", ctypes.c_uint16 * 257),
        ("fIsImsConfig", ctypes.c_int32),
        ("IdiType", ctypes.c_uint32),
        ("IdrType", ctypes.c_uint32),
        ("fDisableIKEv2Fragmentation", ctypes.c_int32),
    ]


class _ServiceStatus(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
    ]


def _rasman_is_running() -> bool:
    """Check service state without starting RasMan or loading rasapi32.dll."""
    if os.name != "nt":
        return False
    manager = None
    service = None
    try:
        advapi = ctypes.WinDLL("advapi32.dll", use_last_error=True)
        open_manager = advapi.OpenSCManagerW
        open_manager.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
        open_manager.restype = wintypes.HANDLE
        open_service = advapi.OpenServiceW
        open_service.argtypes = (wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD)
        open_service.restype = wintypes.HANDLE
        query_status = advapi.QueryServiceStatus
        query_status.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ServiceStatus))
        query_status.restype = wintypes.BOOL
        close_handle = advapi.CloseServiceHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        manager = open_manager(None, None, 0x0001)  # SC_MANAGER_CONNECT
        if not manager:
            return False
        service = open_service(manager, "RasMan", 0x0004)  # SERVICE_QUERY_STATUS
        if not service:
            return False
        status = _ServiceStatus()
        return bool(query_status(service, ctypes.byref(status)) and status.dwCurrentState == 4)
    except (AttributeError, OSError, TypeError, ValueError):
        return False
    finally:
        try:
            if service:
                advapi.CloseServiceHandle(service)
        except Exception:
            pass
        try:
            if manager:
                advapi.CloseServiceHandle(manager)
        except Exception:
            pass


def _enumerate_native_ras_entry_records() -> tuple[tuple[str, str], ...] | None:
    """Call RasEnumEntriesW and retain only each entry name and PBK path."""
    if ctypes.sizeof(ctypes.c_wchar) != 2:
        return None
    # Loading rasapi32.dll can start Remote Access Connection Manager. Query
    # the service first and leave discovery unknown when it is not already up.
    if not _rasman_is_running():
        return None
    try:
        rasapi = ctypes.WinDLL("rasapi32.dll")
        enumerate_entries = rasapi.RasEnumEntriesW
        enumerate_entries.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.POINTER(_RasEntryNameW),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        enumerate_entries.restype = ctypes.c_uint32

        buffer_bytes = ctypes.c_uint32(0)
        entry_count = ctypes.c_uint32(0)
        result = enumerate_entries(
            None, None, None, ctypes.byref(buffer_bytes), ctypes.byref(entry_count)
        )
        if result == _ERROR_SUCCESS:
            return () if entry_count.value == 0 else None
        if result != _ERROR_BUFFER_TOO_SMALL:
            return None

        structure_size = ctypes.sizeof(_RasEntryNameW)
        required = buffer_bytes.value
        if (
            required < structure_size
            or required > _MAX_RAS_BUFFER
            or required % structure_size
        ):
            return None
        capacity = required // structure_size
        if not 1 <= capacity <= _MAX_RAS_ENTRIES:
            return None

        entries = (_RasEntryNameW * capacity)()
        entries[0].dwSize = structure_size
        buffer_bytes = ctypes.c_uint32(required)
        entry_count = ctypes.c_uint32(0)
        result = enumerate_entries(
            None, None, entries, ctypes.byref(buffer_bytes), ctypes.byref(entry_count)
        )
        if result != _ERROR_SUCCESS or entry_count.value > capacity:
            return None
        return tuple(
            (entries[index].szEntryName, entries[index].szPhonebookPath)
            for index in range(entry_count.value)
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _enumerate_native_ras_entries() -> tuple[str, ...] | None:
    """Compatibility wrapper for callers that only need profile names."""
    records = _enumerate_native_ras_entry_records()
    return None if records is None else tuple(name for name, _path in records)


def _enumerate_native_ras_connections() -> tuple[tuple[str, str], ...] | None:
    """Return active RAS entry names and phonebook paths without changing state."""
    if ctypes.sizeof(ctypes.c_wchar) != 2 or not _rasman_is_running():
        return None
    try:
        rasapi = ctypes.WinDLL("rasapi32.dll")
        enumerate_connections = rasapi.RasEnumConnectionsW
        enumerate_connections.argtypes = (
            ctypes.POINTER(_RasConnW),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        enumerate_connections.restype = ctypes.c_uint32

        buffer_bytes = ctypes.c_uint32(0)
        connection_count = ctypes.c_uint32(0)
        result = enumerate_connections(
            None, ctypes.byref(buffer_bytes), ctypes.byref(connection_count)
        )
        if result == _ERROR_SUCCESS:
            return () if connection_count.value == 0 else None
        if result != _ERROR_BUFFER_TOO_SMALL:
            return None

        structure_size = ctypes.sizeof(_RasConnW)
        required = int(buffer_bytes.value)
        if (
            required < structure_size
            or required > structure_size * _MAX_RAS_CONNECTIONS
            or required % structure_size
        ):
            return None
        capacity = required // structure_size
        if not 1 <= capacity <= _MAX_RAS_CONNECTIONS:
            return None

        connections = (_RasConnW * capacity)()
        connections[0].dwSize = structure_size
        buffer_bytes = ctypes.c_uint32(required)
        connection_count = ctypes.c_uint32(0)
        result = enumerate_connections(
            connections, ctypes.byref(buffer_bytes), ctypes.byref(connection_count)
        )
        if result != _ERROR_SUCCESS or connection_count.value > capacity:
            return None
        return tuple(
            (connections[index].szEntryName, connections[index].szPhonebook)
            for index in range(connection_count.value)
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def discover_windows_ras_profile_names(
    *, enumerator: Callable[[], object] | None = None,
) -> tuple[str, ...] | None:
    """Return bounded native RAS profile names, or ``None`` if unavailable.

    An injected enumerator supports deterministic tests. Names are not logged
    or included in the user-facing capability summary; only their count is.
    """
    if enumerator is None:
        if os.name != "nt":
            return None
        enumerator = _enumerate_native_ras_entries
    try:
        values = enumerator()
    except Exception:
        return None
    if values is None:
        return None
    if not isinstance(values, (tuple, list)) or len(values) > _MAX_RAS_ENTRIES:
        return None

    names: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or len(value) > _MAX_RAS_ENTRY_NAME:
            continue
        name = value.strip()
        if not name or any(ord(character) < 32 for character in name):
            continue
        folded = name.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        names.append(name)
    return tuple(names)


def _create_ras_entry_type_reader() -> Callable[[str, str], int | None] | None:
    """Create a read-only RASENTRY type reader while RasMan is already up."""
    if os.name != "nt" or ctypes.sizeof(ctypes.c_wchar) != 2:
        return None
    if not _rasman_is_running():
        return None
    try:
        rasapi = ctypes.WinDLL("rasapi32.dll")
        get_entry = rasapi.RasGetEntryPropertiesW
        get_entry.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        )
        get_entry.restype = ctypes.c_uint32
    except (AttributeError, OSError, TypeError, ValueError):
        return None

    def read_entry_type(phonebook_path: str, entry_name: str) -> int | None:
        if (
            not isinstance(entry_name, str)
            or not entry_name
            or len(entry_name) > _MAX_RAS_ENTRY_NAME
            or any(ord(character) < 32 for character in entry_name)
            or not isinstance(phonebook_path, str)
            or len(phonebook_path) > 32767
            or any(ord(character) < 32 for character in phonebook_path)
        ):
            return None

        size = ctypes.sizeof(_RasEntryW)
        for attempt in range(2):
            buffer = ctypes.create_string_buffer(size)
            entry = ctypes.cast(buffer, ctypes.POINTER(_RasEntryW)).contents
            entry.dwSize = ctypes.sizeof(_RasEntryW)
            buffer_size = ctypes.c_uint32(size)
            result = get_entry(
                phonebook_path or None,
                entry_name,
                ctypes.cast(buffer, ctypes.c_void_p),
                ctypes.byref(buffer_size),
                None,
                None,
            )
            if result == _ERROR_SUCCESS:
                return int(entry.dwType)
            required = int(buffer_size.value)
            if (
                result != _ERROR_BUFFER_TOO_SMALL
                or attempt != 0
                or required <= size
                or required > _MAX_RAS_BUFFER
            ):
                return None
            size = required
        return None

    return read_entry_type


def discover_windows_ras_vpn_profile_names(
    *,
    entries_enumerator: Callable[[], object] | None = None,
    type_reader: Callable[[str, str], int | None] | None = None,
) -> tuple[str, ...] | None:
    """Return only profiles whose native RAS entry type is VPN.

    ``None`` means that discovery or classification was incomplete; an empty
    tuple means the source was read and no VPN profile was present. Names stay
    transient and are never logged or included in the spoken inventory.
    """
    if entries_enumerator is None:
        if os.name != "nt":
            return None
        entries_enumerator = _enumerate_native_ras_entry_records
    try:
        records = entries_enumerator()
    except Exception:
        return None
    if records is None:
        return None
    if not isinstance(records, (tuple, list)) or len(records) > _MAX_RAS_ENTRIES:
        return None
    if not records:
        return ()
    if len(records) > _MAX_RAS_TYPE_QUERIES:
        return None
    if type_reader is None:
        type_reader = _create_ras_entry_type_reader()
    if type_reader is None:
        return None

    vpn_names: list[str] = []
    seen: set[str] = set()
    for record in records:
        if (
            not isinstance(record, (tuple, list))
            or len(record) != 2
            or not isinstance(record[0], str)
            or not isinstance(record[1], str)
        ):
            return None
        name, phonebook_path = record
        name = name.strip()
        phonebook_path = phonebook_path.strip()
        if (
            not name
            or len(name) > _MAX_RAS_ENTRY_NAME
            or any(ord(character) < 32 for character in name)
            or len(phonebook_path) > 32767
            or any(ord(character) < 32 for character in phonebook_path)
        ):
            return None
        drive, _tail = ntpath.splitdrive(phonebook_path)
        if phonebook_path and (
            not ntpath.isabs(phonebook_path) or drive.startswith("\\\\")
        ):
            return None
        key = (phonebook_path.casefold(), name.casefold())
        if key in seen:
            continue
        seen.add(key)
        try:
            entry_type = type_reader(phonebook_path, name)
        except Exception:
            return None
        if entry_type is None:
            return None
        if entry_type == _RASET_VPN:
            vpn_names.append(name)
    return tuple(vpn_names)


def discover_windows_ras_active_vpn_profile_names(
    *,
    connections_enumerator: Callable[[], object] | None = None,
    type_reader: Callable[[str, str], int | None] | None = None,
) -> tuple[str, ...] | None:
    """Return names for active RAS connections whose entry type is VPN.

    Names and phonebook paths stay transient and are never logged or included
    in the spoken inventory. ``None`` means the active snapshot could not be
    completely classified; an empty tuple means no active RAS VPN was found.
    """
    if connections_enumerator is None:
        if os.name != "nt":
            return None
        connections_enumerator = _enumerate_native_ras_connections
    try:
        records = connections_enumerator()
    except Exception:
        return None
    if records is None:
        return None
    if not isinstance(records, (tuple, list)) or len(records) > _MAX_RAS_CONNECTIONS:
        return None
    if not records:
        return ()
    if type_reader is None:
        type_reader = _create_ras_entry_type_reader()
    if type_reader is None:
        return None

    active_vpn_names: list[str] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        if (
            not isinstance(record, (tuple, list))
            or len(record) != 2
            or not isinstance(record[0], str)
            or not isinstance(record[1], str)
        ):
            return None
        name, phonebook_path = (item.strip() for item in record)
        if (
            not name
            or len(name) > _MAX_RAS_ENTRY_NAME
            or any(ord(character) < 32 for character in name)
            or len(phonebook_path) > 32767
            or any(ord(character) < 32 for character in phonebook_path)
        ):
            return None
        # RAS can report a connection created without a phonebook entry as
        # a dot followed by its number. It cannot be safely matched to a VPN
        # profile, so do not guess its type.
        if name.startswith("."):
            continue
        drive, _tail = ntpath.splitdrive(phonebook_path)
        if phonebook_path and (
            not ntpath.isabs(phonebook_path) or drive.startswith("\\\\")
        ):
            return None
        key = (phonebook_path.casefold(), name.casefold())
        if key in seen:
            continue
        seen.add(key)
        try:
            entry_type = type_reader(phonebook_path, name)
        except Exception:
            return None
        if entry_type is None:
            return None
        if entry_type == _RASET_VPN:
            active_vpn_names.append(name)
    return tuple(active_vpn_names)
