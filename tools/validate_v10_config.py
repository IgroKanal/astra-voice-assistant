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
    print(f"listen_timeout_seconds={settings.listen_timeout_seconds}")
    print(f"phrase_time_limit_seconds={settings.phrase_time_limit_seconds}")
    print(f"stt_pause_threshold={settings.stt_pause_threshold}")
    print(f"stt_non_speaking_duration={settings.stt_non_speaking_duration}")
    print(f"tts_cache_prewarm_max_new_phrases={settings.tts_cache_prewarm_max_new_phrases}")

    assert hasattr(settings, "vpn_enabled")
    assert hasattr(settings, "vpn_provider")
    assert hasattr(settings, "vpn_tunnel_service_name")
    assert settings.vpn_provider in {"amneziawg"}
    assert settings.vpn_tunnel_service_name, "VPN tunnel service name must not be empty"
    assert settings.vpn_command_timeout_seconds >= 3
    assert settings.listen_timeout_seconds >= 5
    assert settings.phrase_time_limit_seconds >= 8
    assert settings.stt_pause_threshold >= 0.5
    assert settings.stt_non_speaking_duration >= 0.3
    assert settings.tts_cache_prewarm_max_new_phrases >= 0

    print("v0.10 config validation passed")


if __name__ == "__main__":
    main()
