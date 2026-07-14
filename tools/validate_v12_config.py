from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_apps_config, load_settings


def main() -> None:
    settings = load_settings(PROJECT_ROOT / ".env.example")
    apps = load_apps_config(PROJECT_ROOT / "config" / "apps.json")

    assert settings.allow_commands_without_wake is False
    assert settings.allow_voice_conversation_without_wake is False
    assert settings.wake_only_mode is True
    assert settings.voice_runtime_mode == "wake_only"
    assert settings.wake_response_text == "Слушаю."
    assert settings.llm_model == "gemma-4-31b-it"
    assert settings.llm_fallback_model == "gemini-3.5-flash"

    app = apps["яндекс музыка"]
    assert app.process_name == "Яндекс Музыка.exe"
    assert "яндекс музыку" in app.aliases
    assert "музыка" not in app.aliases
    assert app.open_command == [
        r"%LOCALAPPDATA%\Programs\YandexMusic\Яндекс Музыка.exe"
    ]

    lowered_apps = {
        alias.lower()
        for configured in apps.values()
        for alias in (configured.name, *configured.aliases)
    }
    for forbidden in ("cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "wt"):
        assert forbidden not in lowered_apps, forbidden

    print("Astra v1.2 config validation")
    print(f"apps={len(apps)}")
    print(f"yandex_music_process={app.process_name}")
    print("v1.2 config validation passed")


if __name__ == "__main__":
    main()
