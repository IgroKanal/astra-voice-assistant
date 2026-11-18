"""Read-only Windows Core Audio endpoint discovery.

The endpoint ID is treated as opaque and is returned only to the caller so it
can be hashed for a local device preference. No endpoint is activated and no
recording or playback stream is opened.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import os
import uuid
from typing import Callable


_MAX_ENDPOINTS = 512
_MAX_ENDPOINT_ID_CHARS = 1024
_MAX_FRIENDLY_NAME_CHARS = 512
_DEVICE_STATE_ACTIVE = 0x00000001
_E_CAPTURE = 1
_STGM_READ = 0
_CLSCTX_INPROC_SERVER = 0x1
_COINIT_APARTMENTTHREADED = 0x2
_RPC_E_CHANGED_MODE = 0x80010106
_VT_LPWSTR = 31
_WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


@dataclass(frozen=True)
class WindowsAudioEndpoint:
    """Transient endpoint metadata; callers must not persist the raw ID."""

    endpoint_id: str = field(repr=False)
    friendly_name: str = field(repr=False)


class _Guid(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_uint8 * 8),
    ]

    @classmethod
    def parse(cls, value: str) -> "_Guid":
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class _PropertyKey(ctypes.Structure):
    _fields_ = [("fmtid", _Guid), ("pid", ctypes.c_uint32)]


class _PropVariantValue(ctypes.Union):
    _fields_ = [
        ("pwszVal", ctypes.c_void_p),
        ("pointer", ctypes.c_void_p),
        ("unsigned_value", ctypes.c_uint64),
        ("signed_value", ctypes.c_int64),
        # PROPVARIANT reserves 16 bytes for its union on 64-bit Windows.
        # Keep the full native size so PropVariantClear never reads past this
        # Python-owned structure. On 32-bit Windows the union is 8 bytes.
        ("raw_value", ctypes.c_uint8 * (16 if ctypes.sizeof(ctypes.c_void_p) == 8 else 8)),
    ]


class _PropVariant(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_uint16),
        ("wReserved1", ctypes.c_uint16),
        ("wReserved2", ctypes.c_uint16),
        ("wReserved3", ctypes.c_uint16),
        ("value", _PropVariantValue),
    ]


_CLSID_MMDEVICE_ENUMERATOR = _Guid.parse(
    "BCDE0395-E52F-467C-8E3D-C4579291692E"
)
_IID_IMMDEVICE_ENUMERATOR = _Guid.parse(
    "A95664D2-9614-4F35-A746-DE8DB63617E6"
)
_PKEY_DEVICE_FRIENDLY_NAME = _PropertyKey(
    _Guid.parse("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14
)


def _interface_method(
    interface: ctypes.c_void_p,
    index: int,
    result_type: object,
    argument_types: tuple[object, ...],
) -> Callable[..., int]:
    vtable = ctypes.cast(
        interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
    ).contents
    address = vtable[index]
    return _WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)(address)


def _release(interface: ctypes.c_void_p) -> None:
    if interface:
        _interface_method(interface, 2, ctypes.c_uint32, ())(interface)


def _endpoint_id(ole32: ctypes.CDLL, device: ctypes.c_void_p) -> str:
    value = ctypes.c_void_p()
    result = _interface_method(
        device, 5, ctypes.c_int32, (ctypes.POINTER(ctypes.c_void_p),)
    )(device, ctypes.byref(value))
    if result < 0 or not value:
        return ""
    try:
        endpoint_id = ctypes.wstring_at(value.value)
        if (
            not endpoint_id
            or len(endpoint_id) > _MAX_ENDPOINT_ID_CHARS
            or any(ord(character) < 32 for character in endpoint_id)
        ):
            return ""
        return endpoint_id
    finally:
        ole32.CoTaskMemFree(value)


def _friendly_name(ole32: ctypes.CDLL, device: ctypes.c_void_p) -> str:
    property_store = ctypes.c_void_p()
    result = _interface_method(
        device,
        4,
        ctypes.c_int32,
        (ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)),
    )(device, _STGM_READ, ctypes.byref(property_store))
    if result < 0 or not property_store:
        return ""

    variant = _PropVariant()
    try:
        result = _interface_method(
            property_store,
            5,
            ctypes.c_int32,
            (ctypes.POINTER(_PropertyKey), ctypes.POINTER(_PropVariant)),
        )(property_store, ctypes.byref(_PKEY_DEVICE_FRIENDLY_NAME), ctypes.byref(variant))
        if result < 0 or variant.vt != _VT_LPWSTR or not variant.value.pwszVal:
            return ""
        name = ctypes.wstring_at(variant.value.pwszVal)
        if (
            not name
            or len(name) > _MAX_FRIENDLY_NAME_CHARS
            or any(ord(character) < 32 for character in name)
        ):
            return ""
        return name
    finally:
        try:
            ole32.PropVariantClear(ctypes.byref(variant))
        finally:
            _release(property_store)


def _enumerate_native_capture_endpoints() -> tuple[WindowsAudioEndpoint, ...] | None:
    """Enumerate active capture endpoints without activating audio devices."""
    if os.name != "nt":
        return None
    ole32 = None
    enumerator = ctypes.c_void_p()
    collection = ctypes.c_void_p()
    initialized = False
    try:
        ole32 = ctypes.WinDLL("ole32.dll", use_last_error=True)
        ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        ole32.CoInitializeEx.restype = ctypes.c_int32
        ole32.CoCreateInstance.argtypes = (
            ctypes.POINTER(_Guid),
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(_Guid),
            ctypes.POINTER(ctypes.c_void_p),
        )
        ole32.CoCreateInstance.restype = ctypes.c_int32
        ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
        ole32.CoTaskMemFree.restype = None
        ole32.PropVariantClear.argtypes = (ctypes.POINTER(_PropVariant),)
        ole32.PropVariantClear.restype = ctypes.c_int32
        ole32.CoUninitialize.argtypes = ()
        ole32.CoUninitialize.restype = None

        init_result = int(ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED))
        if init_result >= 0:
            initialized = True
        elif (init_result & 0xFFFFFFFF) != _RPC_E_CHANGED_MODE:
            return None

        result = ole32.CoCreateInstance(
            ctypes.byref(_CLSID_MMDEVICE_ENUMERATOR),
            None,
            _CLSCTX_INPROC_SERVER,
            ctypes.byref(_IID_IMMDEVICE_ENUMERATOR),
            ctypes.byref(enumerator),
        )
        if result < 0 or not enumerator:
            return None

        result = _interface_method(
            enumerator,
            3,
            ctypes.c_int32,
            (ctypes.c_int32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)),
        )(
            enumerator,
            _E_CAPTURE,
            _DEVICE_STATE_ACTIVE,
            ctypes.byref(collection),
        )
        if result < 0 or not collection:
            return None

        count = ctypes.c_uint32()
        result = _interface_method(
            collection,
            3,
            ctypes.c_int32,
            (ctypes.POINTER(ctypes.c_uint32),),
        )(collection, ctypes.byref(count))
        if result < 0 or count.value > _MAX_ENDPOINTS:
            return None

        endpoints = []
        for index in range(count.value):
            device = ctypes.c_void_p()
            result = _interface_method(
                collection,
                4,
                ctypes.c_int32,
                (ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)),
            )(collection, index, ctypes.byref(device))
            if result < 0 or not device:
                continue
            try:
                endpoint_id = _endpoint_id(ole32, device)
                friendly_name = _friendly_name(ole32, device)
                if endpoint_id and friendly_name:
                    endpoints.append(WindowsAudioEndpoint(endpoint_id, friendly_name))
            finally:
                _release(device)
        return tuple(endpoints)
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        return None
    finally:
        _release(collection)
        _release(enumerator)
        if initialized and ole32 is not None:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass


def discover_windows_capture_endpoints(
    *, native_reader: Callable[[], object] | None = None,
) -> tuple[WindowsAudioEndpoint, ...] | None:
    """Return bounded active capture endpoint IDs and friendly names.

    ``None`` means Core Audio was unavailable; an empty tuple means the query
    succeeded and found no usable capture endpoints. Raw IDs are transient.
    """
    if native_reader is None:
        if os.name != "nt":
            return None
        native_reader = _enumerate_native_capture_endpoints
    try:
        records = native_reader()
    except Exception:
        return None
    if records is None:
        return None
    if not isinstance(records, (tuple, list)) or len(records) > _MAX_ENDPOINTS:
        return None

    endpoints = []
    seen = set()
    for record in records:
        if not isinstance(record, WindowsAudioEndpoint):
            return None
        endpoint_id = record.endpoint_id
        friendly_name = record.friendly_name
        if (
            not isinstance(endpoint_id, str)
            or not endpoint_id
            or len(endpoint_id) > _MAX_ENDPOINT_ID_CHARS
            or any(ord(character) < 32 for character in endpoint_id)
            or not isinstance(friendly_name, str)
            or not friendly_name
            or len(friendly_name) > _MAX_FRIENDLY_NAME_CHARS
            or any(ord(character) < 32 for character in friendly_name)
        ):
            continue
        if endpoint_id in seen:
            continue
        seen.add(endpoint_id)
        endpoints.append(record)
    return tuple(endpoints)
