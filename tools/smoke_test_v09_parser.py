from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.command_parser import CommandType, parse_command_text
from src.config_loader import load_apps_config
from src.windows_app_manager import WindowsAppManager
from src.task_router import find_site_url


def assert_cmd(text: str, expected_type: CommandType, expected_target: str = "") -> None:
    parsed = parse_command_text(text)
    assert parsed.type == expected_type, (text, parsed)
    if expected_target:
        assert parsed.target == expected_target, (text, parsed)


def score_for_test(text: str, manager: WindowsAppManager) -> int:
    parsed = parse_command_text(text)
    score = 0
    if parsed.type != CommandType.ASK_LLM:
        score += 100
    if parsed.type in {CommandType.OPEN_APP, CommandType.CLOSE_APP}:
        if manager.find_app(parsed.target) is not None:
            score += 100
    if parsed.type == CommandType.OPEN_URL:
        if find_site_url(parsed.target):
            score += 100
    if "vs code" in text.lower() or "vscode" in text.lower():
        score += 20
    return score


def main() -> None:
    assert_cmd("сколько сейчас время", CommandType.GET_TIME)
    assert_cmd("какое сейчас время", CommandType.GET_TIME)
    assert_cmd("обнови страницу ютуб", CommandType.KEYBOARD_SHORTCUT, "refresh")
    assert_cmd("обнови страница ютуб", CommandType.KEYBOARD_SHORTCUT, "refresh")
    assert_cmd("перезагрузи страница ютуб", CommandType.KEYBOARD_SHORTCUT, "refresh")
    assert_cmd("закройте вкладку", CommandType.KEYBOARD_SHORTCUT, "close_tab")
    assert_cmd("закроет вкладку", CommandType.KEYBOARD_SHORTCUT, "close_tab")
    assert_cmd("закрой последнюю вкладку", CommandType.KEYBOARD_SHORTCUT, "close_tab")
    assert_cmd("диспетчер задач", CommandType.OPEN_APP, "диспетчер задач")
    assert_cmd("найди", CommandType.WEB_SEARCH, "")
    assert_cmd("открой vs кот", CommandType.OPEN_APP, "vs кот")

    apps = load_apps_config()
    manager = WindowsAppManager(apps=apps)
    alternatives = ["Открой vs кот", "Открой vs code", "Открой vs cod"]
    selected = max(alternatives, key=lambda item: score_for_test(item, manager))
    assert selected.lower() == "открой vs code", selected

    print("v0.9 parser smoke tests passed")


if __name__ == "__main__":
    main()
