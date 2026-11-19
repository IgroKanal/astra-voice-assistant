"""Per-session Windows event for cancelling an active desktop AI response."""
from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from uuid import uuid4


ENVIRONMENT_VARIABLE = "ASTRA_DESKTOP_CANCEL_EVENT"
_EVENT_MODIFY_STATE = 0x0002
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 0x00000102
_NAME_PATTERN = re.compile(r"Local\\AstraCancel-[0-9a-f]{32}\Z")


class DesktopCancellationEvent:
    """Small manual-reset event shared by the Qt process and its own runtime.

    The unpredictable, per-session name is passed only to the child runtime.
    Windows applies the creating process token's default DACL to the object;
    no network listener or user data file is needed.
    """

    def __init__(self, handle, name: str):
        self._handle = handle
        self.name = name

    @classmethod
    def create(cls) -> "DesktopCancellationEvent":
        if os.name != "nt":
            raise OSError("Desktop cancellation events require Windows")
        kernel32 = _kernel32()
        name = f"Local\\AstraCancel-{uuid4().hex}"
        ctypes.set_last_error(0)
        handle = kernel32.CreateEventW(None, True, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            raise OSError("A unique desktop cancellation event could not be created")
        return cls(handle, name)

    @classmethod
    def open(cls, name: str) -> "DesktopCancellationEvent":
        if os.name != "nt":
            raise OSError("Desktop cancellation events require Windows")
        if not isinstance(name, str) or _NAME_PATTERN.fullmatch(name) is None:
            raise ValueError("Invalid desktop cancellation event name")
        handle = _kernel32().OpenEventW(
            _SYNCHRONIZE | _EVENT_MODIFY_STATE,
            False,
            name,
        )
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return cls(handle, name)

    @classmethod
    def open_from_environment(cls) -> "DesktopCancellationEvent | None":
        name = os.environ.get(ENVIRONMENT_VARIABLE, "").strip()
        return cls.open(name) if name else None

    def set(self) -> None:
        self._ensure_open()
        if not _kernel32().SetEvent(self._handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def reset(self) -> None:
        self._ensure_open()
        if not _kernel32().ResetEvent(self._handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def is_set(self) -> bool:
        self._ensure_open()
        result = _kernel32().WaitForSingleObject(self._handle, 0)
        if result == _WAIT_OBJECT_0:
            return True
        if result == _WAIT_TIMEOUT:
            return False
        raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        handle = self._handle
        if handle:
            self._handle = None
            if not _kernel32().CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())

    def _ensure_open(self) -> None:
        if not self._handle:
            raise OSError("Desktop cancellation event is closed")


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateEventW.argtypes = (
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
    kernel32.SetEvent.restype = wintypes.BOOL
    kernel32.ResetEvent.argtypes = (wintypes.HANDLE,)
    kernel32.ResetEvent.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32
