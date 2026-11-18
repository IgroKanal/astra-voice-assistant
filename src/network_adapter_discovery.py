"""Read-only counts of Windows network adapters from their class registry keys."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID


_NETWORK_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4D36E972-E325-11CE-BFC1-08002BE10318}"
# NDIS defines NCF_VIRTUAL as bit 0x1 in a network component's characteristics.
_NCF_VIRTUAL = 0x1
_MAX_ADAPTERS = 1024
_ADAPTER_KEY_RE = re.compile(r"^\d{4}$")


@dataclass(frozen=True)
class NetworkAdapterInventory:
    adapter_count: int
    virtual_adapter_count: int


def _close(registry: Any, key: Any) -> None:
    try:
        registry.CloseKey(key)
    except (AttributeError, OSError):
        pass


def discover_network_adapter_inventory(
    *, registry: Any | None = None
) -> NetworkAdapterInventory | None:
    """Count current network-class entries and NCF_VIRTUAL adapters.

    Only a bounded registry walk is used. Names, interface GUIDs and driver
    details never leave this function. A virtual adapter can belong to VPN,
    virtualization, containers or other software, so it is only a discovery
    hint and does not identify or authorize a client.
    """
    if registry is None:
        if os.name != "nt":
            return None
        try:
            import winreg as registry
        except ImportError:
            return None

    root = getattr(registry, "HKEY_LOCAL_MACHINE", None)
    if root is None:
        return None
    try:
        class_key = registry.OpenKey(root, _NETWORK_CLASS)
    except OSError:
        return None

    total = 0
    virtual = 0
    try:
        for index in range(_MAX_ADAPTERS + 1):
            try:
                subkey = registry.EnumKey(class_key, index)
            except OSError:
                break
            if index >= _MAX_ADAPTERS:
                return None
            if not isinstance(subkey, str) or not _ADAPTER_KEY_RE.fullmatch(subkey):
                continue
            try:
                adapter_key = registry.OpenKey(class_key, subkey)
            except OSError:
                return None
            try:
                try:
                    instance_id = registry.QueryValueEx(adapter_key, "NetCfgInstanceId")[0]
                except OSError:
                    continue
                if not isinstance(instance_id, str):
                    continue
                try:
                    UUID(instance_id.strip("{}"))
                except (ValueError, AttributeError):
                    continue
                try:
                    characteristics = registry.QueryValueEx(adapter_key, "Characteristics")[0]
                except OSError:
                    return None
                if type(characteristics) is not int or not 0 <= characteristics <= 0xFFFFFFFF:
                    return None
                total += 1
                if characteristics & _NCF_VIRTUAL:
                    virtual += 1
            finally:
                _close(registry, adapter_key)
    finally:
        _close(registry, class_key)
    return NetworkAdapterInventory(total, virtual)
