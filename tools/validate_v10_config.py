from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_settings


def main() -> None:
    settings = load_settings()

    print("Astra v0.10 config validation")
    print(f"vpn_enabled={settings.vpn_enabled}")
    print(f"vpn_provider={settings.vpn_provider}")
    print(f"vpn_tunnel_service_name={settings.vpn_tunnel_service_name}")
    print(f"vpn_manager_service_name={settings.vpn_manager_service_name}")
    print(f"vpn_command_timeout_seconds={settings.vpn_command_timeout_seconds}")

    assert hasattr(settings, "vpn_enabled")
    assert hasattr(settings, "vpn_provider")
    assert hasattr(settings, "vpn_tunnel_service_name")
    assert settings.vpn_provider in {"amneziawg"}
    assert settings.vpn_tunnel_service_name, "VPN tunnel service name must not be empty"
    assert settings.vpn_command_timeout_seconds >= 3

    print("v0.10 config validation passed")


if __name__ == "__main__":
    main()
