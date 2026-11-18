"""Read-only discovery of native Windows Remote Access Service profiles.

RAS phonebook entries can describe VPN or dial-up connections. This module
enumerates names only; it does not read credentials or change connection state.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from typing import Callable


_ERROR_SUCCESS = 0
_ERROR_BUFFER_TOO_SMALL = 603
_MAX_RAS_ENTRY_NAME = 256
_MAX_RAS_ENTRIES = 4096
_MAX_RAS_BUFFER = 4 * 1024 * 1024


class _RasEntryNameW(ctypes.Structure):
    """RASENTRYNAMEW layout from the Windows RAS API."""

    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("szEntryName", ctypes.c_wchar * (_MAX_RAS_ENTRY_NAME + 1)),
        ("dwFlags", ctypes.c_uint32),
        ("szPhonebookPath", ctypes.c_wchar * 261),
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


def _enumerate_native_ras_entries() -> tuple[str, ...] | None:
    """Call RasEnumEntriesW with a bounded buffer and no connection changes."""
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
        return tuple(entries[index].szEntryName for index in range(entry_count.value))
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
