from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_settings


def main() -> None:
    settings = load_settings()

    print("Astra v1.0.1 beta config validation")
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
    print(f"tts_cache_generation_timeout_seconds={settings.tts_cache_generation_timeout_seconds}")
    print(f"voice_runtime_mode={settings.voice_runtime_mode}")
    print(f"wake_only_mode={settings.wake_only_mode}")
    print(f"wake_listen_timeout_seconds={settings.wake_listen_timeout_seconds}")
    print(f"wake_phrase_time_limit_seconds={settings.wake_phrase_time_limit_seconds}")
    print(f"command_listen_timeout_seconds={settings.command_listen_timeout_seconds}")
    print(f"command_phrase_time_limit_seconds={settings.command_phrase_time_limit_seconds}")
    print(f"wake_response_enabled={settings.wake_response_enabled}")
    print(f"wake_response_text={settings.wake_response_text}")
    print(f"wake_allow_direct_command={settings.wake_allow_direct_command}")

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
    assert 0 <= settings.tts_cache_prewarm_max_new_phrases <= 1
    assert 5 <= settings.tts_cache_generation_timeout_seconds <= 10
    assert settings.voice_runtime_mode in {"wake_only", "wake", "wake-only", "legacy"}
    assert settings.wake_listen_timeout_seconds >= 2
    assert settings.wake_phrase_time_limit_seconds >= 2
    assert settings.command_listen_timeout_seconds >= 5
    assert settings.command_phrase_time_limit_seconds >= 8
    assert isinstance(settings.wake_response_enabled, bool)
    assert isinstance(settings.wake_allow_direct_command, bool)
    assert settings.wake_response_text == "Слушаю.", settings.wake_response_text
    assert "астер" in settings.wake_phrases
    assert "астэр" in settings.wake_phrases
    assert "астры" in settings.wake_phrases

    print("v1.0.1 beta config validation passed")


if __name__ == "__main__":
    main()
