from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.command_parser import CommandType, UNSUPPORTED_CLOSE_TARGET, UNSUPPORTED_OPEN_TARGET, parse_command_text
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


def test_vscode_resolver_avoids_cmd_wrapper() -> None:
    """
    v0.9.3 regression test: раньше code.cmd, найденный через PATH, побеждал
    прямые пути к Code.exe и запускался через ["cmd", "/c", "start", ...],
    что открывало лишнее cmd-окно. Теперь прямые пути важнее, а голый
    code.cmd без соседнего Code.exe вообще не запускается.
    """
    manager = WindowsAppManager(apps={})
    neutral_env = {
        "ASTRA_VSCODE_PATH": "",
        "LOCALAPPDATA": "",
        "ProgramFiles": "",
        "ProgramFiles(x86)": "",
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        code_exe = tmp_path / "Code.exe"
        code_exe.write_text("")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        code_cmd = bin_dir / "code.cmd"
        code_cmd.write_text("")

        # 1. ASTRA_VSCODE_PATH задан явно -> используем его, даже если PATH
        #    тоже "находит" code.cmd.
        with mock.patch.dict(os.environ, {**neutral_env, "ASTRA_VSCODE_PATH": str(code_exe)}):
            with mock.patch("shutil.which", return_value=str(code_cmd)):
                command = manager._resolve_vscode_command()
        assert command == [str(code_exe)], command

        # 2. ASTRA_VSCODE_PATH не задан, ничего не помогло напрямую, но PATH
        #    находит code.cmd рядом с настоящим Code.exe -> должны получить
        #    путь к Code.exe, а не обёртку через cmd/start.
        with mock.patch.dict(os.environ, neutral_env):
            with mock.patch("shutil.which", return_value=str(code_cmd)):
                command = manager._resolve_vscode_command()
        assert command == [str(code_exe)], command

    # 3. Найден только code.cmd, соседнего Code.exe нигде нет -> честный
    #    None, а не запуск .cmd через видимое cmd-окно.
    with tempfile.TemporaryDirectory() as lonely_tmp:
        lonely_bin = Path(lonely_tmp) / "bin"
        lonely_bin.mkdir()
        lonely_cmd = lonely_bin / "code.cmd"
        lonely_cmd.write_text("")

        with mock.patch.dict(os.environ, neutral_env):
            with mock.patch("shutil.which", return_value=str(lonely_cmd)):
                command = manager._resolve_vscode_command()
        assert command is None, command


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

    # v0.9.3: "закрой окно" — это больше не ASK_LLM (и не поход в LLM-router),
    # а прямая локальная команда с sentinel-таргетом.
    assert_cmd("закрой окно", CommandType.CLOSE_APP, UNSUPPORTED_CLOSE_TARGET)
    assert_cmd("закрыть окно", CommandType.CLOSE_APP, UNSUPPORTED_CLOSE_TARGET)
    assert_cmd("закрой активное окно", CommandType.CLOSE_APP, UNSUPPORTED_CLOSE_TARGET)
    assert_cmd("закрой последнее", CommandType.CLOSE_APP, UNSUPPORTED_CLOSE_TARGET)
    assert_cmd("закрой последние", CommandType.CLOSE_APP, UNSUPPORTED_CLOSE_TARGET)
    assert_cmd("закрой последнее окно", CommandType.CLOSE_APP, UNSUPPORTED_CLOSE_TARGET)
    assert_cmd("открой окно", CommandType.OPEN_APP, UNSUPPORTED_OPEN_TARGET)
    assert_cmd("открой последнее окно", CommandType.OPEN_APP, UNSUPPORTED_OPEN_TARGET)
    assert_cmd("открой чат gp", CommandType.OPEN_URL, "чат gp")

    apps = load_apps_config()
    manager = WindowsAppManager(apps=apps)

    preferred_manager = WindowsAppManager(apps=apps, browser_preferred="firefox")
    browser_app = preferred_manager.find_app("браузер")
    assert browser_app is not None and browser_app.name == "firefox", browser_app
    vscode_app = preferred_manager.find_app("vsco")
    assert vscode_app is not None and vscode_app.name == "vscode", vscode_app
    assert preferred_manager.find_app("окно") is None
    assert preferred_manager.find_app("последнее") is None

    alternatives = ["Открой vs кот", "Открой vs code", "Открой vs cod"]
    selected = max(alternatives, key=lambda item: score_for_test(item, manager))
    assert selected.lower() == "открой vs code", selected

    test_vscode_resolver_avoids_cmd_wrapper()

    print("v0.9 parser smoke tests passed")


if __name__ == "__main__":
    main()
