from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config_loader import ConfigError, load_apps_config, load_settings
from src.command_parser import CommandType, parse_command_text
from src.task_router import normalize_url_or_site


BAD_MODELS = {"gemma-4-26b-a4b-it"}


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    try:
        env_path = ROOT / ".env"
        if not env_path.exists():
            env_path = ROOT / ".env.example"
        settings = load_settings(env_path)
        apps_path = ROOT / "config" / "apps.json"
        if apps_path.exists():
            apps = load_apps_config(apps_path)
        else:
            apps = load_apps_config(ROOT / "config" / "apps.v0.8.example.json")
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1

    print("Astra v0.8 config validation")
    print(f"assistant_name={settings.assistant_name}")
    print(f"llm_provider={settings.llm_provider}")
    print(f"llm_model={settings.llm_model}")
    print(f"llm_fallback_model={settings.llm_fallback_model or '<empty>'}")
    api_key_configured = bool(settings.llm_api_key) and not settings.llm_api_key.startswith("PASTE_") and not settings.llm_api_key.startswith("your_")
    print(f"api_key_configured={api_key_configured} len={len(settings.llm_api_key)}")
    print(f"apps_count={len(apps)}")

    check(settings.llm_model not in BAD_MODELS, "Primary model must not be unstable gemma-4-26b-a4b-it")
    check(settings.llm_fallback_model not in BAD_MODELS, "Fallback model must not be unstable gemma-4-26b-a4b-it")
    if settings.llm_model != "gemma-4-31b-it":
        print("WARNING: recommended primary model for v0.8 is gemma-4-31b-it")
    check(settings.llm_fallback_model, "Fallback model should be configured")

    parser_cases = {
        "открой сайт кло": CommandType.OPEN_URL,
        "открой чатт gpt": CommandType.OPEN_URL,
        "закрой ютуб": CommandType.KEYBOARD_SHORTCUT,
        "напиши тест": CommandType.TYPE_TEXT,
        "сделай скриншот": CommandType.SCREENSHOT,
        "сколько памяти": CommandType.SYSTEM_INFO,
        "переключи звук": CommandType.KEYBOARD_SHORTCUT,
        "что ты умеешь": CommandType.HELP,
    }
    for text, expected in parser_cases.items():
        parsed = parse_command_text(text)
        check(parsed.type == expected, f"{text!r}: expected {expected}, got {parsed}")

    check(normalize_url_or_site("сайт кло") == "https://claude.ai", "site alias 'сайт кло' failed")
    print("v0.8 config validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
