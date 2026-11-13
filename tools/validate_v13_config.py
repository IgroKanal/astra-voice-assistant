from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.command_parser import CommandType, parse_command_text
from src.config_loader import load_apps_config


def main() -> None:
    required = [
        ROOT / "src" / "media_controller.py",
        ROOT / "tools" / "smoke_test_v13_media_control.py",
        ROOT / "tools" / "smoke_test_v13_window_actions.py",
        ROOT / "tools" / "apply_v13_beta_env.ps1",
        ROOT / "RELEASE_NOTES_v1.3.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    assert not missing, f"Missing v1.3 files: {missing}"

    cases = {
        "выключи музыку": (CommandType.MEDIA_CONTROL, "shutdown_yandex_music"),
        "верни предыдущий трек": (CommandType.KEYBOARD_SHORTCUT, "media_previous"),
        "начни трек заново": (CommandType.KEYBOARD_SHORTCUT, "media_restart_current"),
        "предыдущий трек в локальном плеере": (
            CommandType.MEDIA_CONTROL,
            "previous:local",
        ),
        "сверни телеграм": (CommandType.WINDOW_CONTROL, "minimize:телеграм"),
        "разверни окно на весь экран": (CommandType.WINDOW_CONTROL, "maximize"),
        "верни обычный размер окна": (CommandType.WINDOW_CONTROL, "restore"),
        "верни на обычный размер": (CommandType.WINDOW_CONTROL, "restore"),
        "следующий трек вока": (CommandType.MEDIA_CONTROL, "next:local"),
        "включи локальную музыку": (CommandType.MEDIA_CONTROL, "open_play_local"),
        "включи локальный плеер": (CommandType.MEDIA_CONTROL, "open_play_local"),
        "продолжи локальный плеер": (CommandType.MEDIA_CONTROL, "play:local"),
    }
    for text, expected in cases.items():
        parsed = parse_command_text(text)
        assert (parsed.type, parsed.target) == expected, (text, parsed)

    apps = load_apps_config(ROOT / "config" / "apps.json")
    player = apps["медиаплеер"]
    assert "локальный плеер" in player.aliases
    assert "плеер" in player.aliases
    assert player.process_name == "Music.UI.exe"
    assert "музыка groove" in player.aliases
    assert "музыка грув" in player.aliases

    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ASTRA_LOCAL_MEDIA_PLAYER_PATH=" in env_example
    print("v1.3 config validation passed")


if __name__ == "__main__":
    main()
