from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_apps_config, load_settings
from src.routine_controller import ALLOWED_ROUTINE_ACTIONS, RoutineController


def main() -> None:
    settings = load_settings(PROJECT_ROOT / ".env.example")
    apps = load_apps_config(PROJECT_ROOT / "config" / "apps.json")
    routines = RoutineController(PROJECT_ROOT / "config" / "routines.json")

    assert settings.allow_commands_without_wake is False
    assert settings.allow_voice_conversation_without_wake is False
    assert settings.wake_only_mode is True
    assert settings.voice_runtime_mode == "wake_only"
    assert settings.wake_response_text == "Слушаю."
    assert settings.routines_enabled is True
    assert settings.context_ttl_seconds == 120.0
    assert settings.llm_model == "gemma-4-31b-it"
    assert settings.llm_fallback_model == "gemini-3.5-flash"

    lowered_apps = {
        alias.lower()
        for app in apps.values()
        for alias in (app.name, *app.aliases)
    }
    for forbidden in ("cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "wt"):
        assert forbidden not in lowered_apps, forbidden

    routine = routines.resolve("рабочий режим")
    assert routine is not None
    assert 1 <= len(routine.steps) <= 8
    assert all(step.action in ALLOWED_ROUTINE_ACTIONS for step in routine.steps)

    print("Astra v1.1 config validation")
    print(f"routines={routines.routine_count()}")
    print(f"routine_actions={sorted(ALLOWED_ROUTINE_ACTIONS)}")
    print(f"context_ttl_seconds={settings.context_ttl_seconds}")
    print("v1.1 config validation passed")


if __name__ == "__main__":
    main()
