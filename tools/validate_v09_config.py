from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_apps_config, load_settings

BAD_GEMMA = "gemma-4-26b-a4b-it"


def main() -> None:
    settings = load_settings()
    apps = load_apps_config()

    print("Astra v0.9 config validation")
    print(f"assistant_name={settings.assistant_name}")
    print(f"llm_provider={settings.llm_provider}")
    print(f"llm_model={settings.llm_model}")
    print(f"llm_fallback_model={settings.llm_fallback_model}")
    print(f"api_key_configured={bool(settings.llm_api_key)} len={len(settings.llm_api_key)}")
    print(f"apps_count={len(apps)}")
    print(f"browser_preferred={settings.browser_preferred or 'auto'}")
    print(f"stt_command_aware_alternatives={settings.stt_command_aware_alternatives}")
    print(f"stt_mistake_log_path={settings.stt_mistake_log_path}")

    assert settings.llm_model != BAD_GEMMA, "Bad primary model must not be used"
    assert settings.llm_fallback_model != BAD_GEMMA, "Bad fallback model must not be used"
    assert settings.llm_fallback_model, "Fallback model should be configured"
    assert "диспетчер задач" in apps, "Task Manager app must be configured"
    assert "vscode" in apps, "VS Code app must be configured"
    assert hasattr(settings, "browser_preferred")
    assert hasattr(settings, "stt_command_aware_alternatives")

    print("v0.9 config validation passed")


if __name__ == "__main__":
    main()
