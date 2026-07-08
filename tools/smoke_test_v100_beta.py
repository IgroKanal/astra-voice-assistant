from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.command_parser import (
    CommandType,
    UNSUPPORTED_CLOSE_TARGET,
    extract_command_after_wake,
)
from src.config_loader import load_settings


def test_mojibake_wake_response_is_repaired() -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write("WAKE_RESPONSE_TEXT=РЎР»СѓС€Р°СЋ.\n")
        path = handle.name

    try:
        settings = load_settings(path)
        assert settings.wake_response_text == "Слушаю.", settings.wake_response_text
    finally:
        Path(path).unlink(missing_ok=True)


def test_beta_wake_phrase_variants() -> None:
    wake_phrases = [
        "астра",
        "эй астра",
        "привет астра",
        "астро",
        "остра",
        "а стра",
        "астер",
        "астэр",
        "астры",
    ]

    for text in ("Астер стоп", "астэр стоп", "Астры стоп", "Астра стоп"):
        parsed = extract_command_after_wake(text, wake_phrases)
        assert parsed.type == CommandType.EXIT, (text, parsed)


def test_close_window_stt_short_fragments_are_guarded() -> None:
    wake_phrases = ["астра"]
    for text in ("Астра закрой ок", "Астра закрой ак", "Астра закрой аг", "Астра Закрой окно"):
        parsed = extract_command_after_wake(text, wake_phrases)
        assert parsed.type == CommandType.CLOSE_APP, (text, parsed)
        assert parsed.target == UNSUPPORTED_CLOSE_TARGET, (text, parsed)


def test_send_enter_phrase_stays_local_keyboard_action() -> None:
    wake_phrases = ["астра"]
    for text in ("Астра Отправь нажми Enter", "Астра отправь энтер", "Астра отправь enter"):
        parsed = extract_command_after_wake(text, wake_phrases)
        assert parsed.type == CommandType.KEYBOARD_SHORTCUT, (text, parsed)
        assert parsed.target == "enter", (text, parsed)


def test_shell_apps_not_whitelisted() -> None:
    apps_path = PROJECT_ROOT / "config" / "apps.json"
    data = json.loads(apps_path.read_text(encoding="utf-8"))
    apps = data.get("apps", {})

    forbidden = {
        "cmd",
        "cmd.exe",
        "командная строка",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "windowsterminal",
        "windowsterminal.exe",
    }

    names_and_aliases: set[str] = set()
    for name, app in apps.items():
        names_and_aliases.add(str(name).lower())
        for alias in app.get("aliases", []):
            names_and_aliases.add(str(alias).lower())

    assert not (forbidden & names_and_aliases), forbidden & names_and_aliases


def main() -> None:
    test_mojibake_wake_response_is_repaired()
    test_beta_wake_phrase_variants()
    test_close_window_stt_short_fragments_are_guarded()
    test_send_enter_phrase_stays_local_keyboard_action()
    test_shell_apps_not_whitelisted()
    print("v1.0 beta smoke tests passed")


if __name__ == "__main__":
    main()
