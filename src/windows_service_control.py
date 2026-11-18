"""Small, query-first Windows Service Control Manager adapter.

This module talks to the native SCM API directly. It never builds a shell
command from a service name. The default adapter is created lazily by callers,
so importing Astra remains safe in non-Windows test environments.
"""

from __future__ import annotations

import ctypes
import math
import os
import time
from typing import Literal, Protocol


ServiceState = Literal[
    "stopped",
    "startpending",
    "stoppending",
    "running",
    "continuepending",
    "pausepending",
    "paused",
    "unknown",
]


class WindowsServiceError(OSError):
    def __init__(self, error_code: int) -> None:
        super().__init__(error_code, "Windows service control operation failed")
        self.error_code = int(error_code)


class ServiceControl(Protocol):
    def query_status(self, service_name: str) -> ServiceState: ...

    def set_state(
        self,
        service_name: str,
        desired: Literal["running", "stopped"],
        timeout_seconds: float,
    ) -> ServiceState: ...


class _SERVICE_STATUS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", ctypes.c_uint32),
        ("dwCurrentState", ctypes.c_uint32),
        ("dwControlsAccepted", ctypes.c_uint32),
        ("dwWin32ExitCode", ctypes.c_uint32),
        ("dwServiceSpecificExitCode", ctypes.c_uint32),
        ("dwCheckPoint", ctypes.c_uint32),
        ("dwWaitHint", ctypes.c_uint32),
    ]


class _SERVICE_STATUS_PROCESS(ctypes.Structure):
    _fields_ = _SERVICE_STATUS._fields_ + [
        ("dwProcessId", ctypes.c_uint32),
        ("dwServiceFlags", ctypes.c_uint32),
    ]


class WindowsServiceControl:
    """Query and start/stop one exact SCM service using typed Win32 calls."""

    SC_MANAGER_CONNECT = 0x0001
    SERVICE_QUERY_STATUS = 0x0004
    SERVICE_START = 0x0010
    SERVICE_STOP = 0x0020
    SERVICE_PAUSE_CONTINUE = 0x0040
    SERVICE_CONTROL_STOP = 0x0001
    SERVICE_CONTROL_CONTINUE = 0x0003
    SC_STATUS_PROCESS_INFO = 0
    ERROR_ACCESS_DENIED = 5
    ERROR_SERVICE_DOES_NOT_EXIST = 1060
    ERROR_SERVICE_NOT_ACTIVE = 1062
    ERROR_SERVICE_ALREADY_RUNNING = 1056

    _STATE_NAMES: dict[int, ServiceState] = {
        1: "stopped",
        2: "startpending",
        3: "stoppending",
        4: "running",
        5: "continuepending",
        6: "pausepending",
        7: "paused",
    }
    _PENDING_STATES = {
        "startpending",
        "stoppending",
        "continuepending",
        "pausepending",
    }

    def __init__(self, advapi32=None) -> None:
        if advapi32 is None:
            if os.name != "nt":
                raise OSError("Windows Service Control is available only on Windows")
            advapi32 = ctypes.WinDLL("Advapi32", use_last_error=True)
        self._advapi32 = advapi32
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        handle = ctypes.c_void_p
        api = self._advapi32
        api.OpenSCManagerW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        api.OpenSCManagerW.restype = handle
        api.OpenServiceW.argtypes = [handle, ctypes.c_wchar_p, ctypes.c_uint32]
        api.OpenServiceW.restype = handle
        api.CloseServiceHandle.argtypes = [handle]
        api.CloseServiceHandle.restype = ctypes.c_int
        api.QueryServiceStatusEx.argtypes = [
            handle,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        api.QueryServiceStatusEx.restype = ctypes.c_int
        api.StartServiceW.argtypes = [handle, ctypes.c_uint32, ctypes.c_void_p]
        api.StartServiceW.restype = ctypes.c_int
        api.ControlService.argtypes = [handle, ctypes.c_uint32, ctypes.POINTER(_SERVICE_STATUS)]
        api.ControlService.restype = ctypes.c_int

    @staticmethod
    def _validate_name(service_name: str) -> str:
        if not isinstance(service_name, str):
            raise ValueError("service name must be text")
        name = service_name.strip()
        if (not name or len(name) > 256
                or any(ord(char) < 32 or ord(char) == 127 for char in name)):
            raise ValueError("invalid Windows service name")
        return name

    @staticmethod
    def _last_error() -> int:
        getter = getattr(ctypes, "get_last_error", None)
        return int(getter() if getter is not None else 0)

    def _open_service(self, service_name: str, desired_access: int):
        name = self._validate_name(service_name)
        manager = self._advapi32.OpenSCManagerW(
            None, None, self.SC_MANAGER_CONNECT
        )
        if not manager:
            raise WindowsServiceError(self._last_error())
        service = self._advapi32.OpenServiceW(manager, name, desired_access)
        if not service:
            error_code = self._last_error()
            self._advapi32.CloseServiceHandle(manager)
            raise WindowsServiceError(error_code)
        return manager, service

    def _close_handles(self, manager, service) -> None:
        try:
            self._advapi32.CloseServiceHandle(service)
        finally:
            self._advapi32.CloseServiceHandle(manager)

    def _query_handle(self, service) -> ServiceState:
        status = _SERVICE_STATUS_PROCESS()
        returned = ctypes.c_uint32()
        ok = self._advapi32.QueryServiceStatusEx(
            service,
            self.SC_STATUS_PROCESS_INFO,
            ctypes.byref(status),
            ctypes.sizeof(status),
            ctypes.byref(returned),
        )
        if not ok:
            raise WindowsServiceError(self._last_error())
        return self._STATE_NAMES.get(status.dwCurrentState, "unknown")

    def query_status(self, service_name: str) -> ServiceState:
        manager, service = self._open_service(service_name, self.SERVICE_QUERY_STATUS)
        try:
            return self._query_handle(service)
        finally:
            self._close_handles(manager, service)

    def set_state(
        self,
        service_name: str,
        desired: Literal["running", "stopped"],
        timeout_seconds: float,
    ) -> ServiceState:
        if desired not in {"running", "stopped"}:
            raise ValueError("unsupported Windows service target state")
        if (not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0
                or timeout_seconds > 120):
            raise ValueError("service transition timeout must be positive")

        access = self.SERVICE_QUERY_STATUS
        if desired == "running":
            access |= self.SERVICE_START | self.SERVICE_PAUSE_CONTINUE
        else:
            access |= self.SERVICE_STOP
        manager, service = self._open_service(service_name, access)
        try:
            current = self._query_handle(service)
            if current == desired:
                return current

            if current not in self._PENDING_STATES:
                if desired == "running" and current in {"stopped", "paused"}:
                    if current == "paused":
                        status = _SERVICE_STATUS()
                        ok = self._advapi32.ControlService(
                            service, self.SERVICE_CONTROL_CONTINUE, ctypes.byref(status)
                        )
                    else:
                        ok = self._advapi32.StartServiceW(service, 0, None)
                    if not ok:
                        error_code = self._last_error()
                        if error_code != self.ERROR_SERVICE_ALREADY_RUNNING:
                            raise WindowsServiceError(error_code)
                elif desired == "stopped" and current in {"running", "paused"}:
                    status = _SERVICE_STATUS()
                    ok = self._advapi32.ControlService(
                        service, self.SERVICE_CONTROL_STOP, ctypes.byref(status)
                    )
                    if not ok:
                        error_code = self._last_error()
                        if error_code != self.ERROR_SERVICE_NOT_ACTIVE:
                            raise WindowsServiceError(error_code)
                else:
                    return current

            deadline = time.monotonic() + float(timeout_seconds)
            while True:
                current = self._query_handle(service)
                if current == desired or current not in self._PENDING_STATES:
                    return current
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return current
                time.sleep(min(0.3, remaining))
        finally:
            self._close_handles(manager, service)
