from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main as astra_main
from main import TurnContext, TurnState, process_turn
from src.command_parser import CommandType, parse_command_text
from src.config_loader import AppConfig, Settings, load_apps_config
from src.folder_controller import FolderActionResult
from src.keyboard_controller import KeyboardActionResult
from src.task_router import find_site_url
from src.window_controller import WindowActionResult, WindowController
from src.windows_app_manager import WindowsAppManager


class FakeAIClient:
    is_available = True

    def __init__(self) -> None:
        self.route_calls = 0
        self.ask_calls = 0

    def route_command(self, text: str, apps=None):
        self.route_calls += 1
        raise AssertionError(f"LLM-router must not be called: {text!r}")

    def ask(self, text: str):
        self.ask_calls += 1
        raise AssertionError(f"Conversation LLM must not be called: {text!r}")


class FakeAppManager:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.app = AppConfig(
            name="яндекс музыка",
            aliases=["яндекс музыка", "яндекс музыку", "yandex music"],
            open_command=[r"%LOCALAPPDATA%\Programs\YandexMusic\Яндекс Музыка.exe"],
            process_name="Яндекс Музыка.exe",
        )

    def find_app(self, target: str):
        if target.lower() in self.app.aliases:
            return self.app
        return None

    def open_app(self, target: str):
        app = self.find_app(target)
        if app is None:
            return types.SimpleNamespace(ok=False, message="Не нашёл такое приложение в списке.")
        self.opened.append(app.name)
        return types.SimpleNamespace(ok=True, message="Открываю.")

    def close_app(self, target: str):
        app = self.find_app(target)
        if app is None:
            return types.SimpleNamespace(ok=False, message="Не нашёл такое приложение в списке.")
        self.closed.append(app.name)
        return types.SimpleNamespace(ok=True, message="Закрываю.")


class FakeKeyboard:
    def send_shortcut(self, name: str) -> KeyboardActionResult:
        raise AssertionError(f"Keyboard action is outside this smoke test: {name!r}")

    def type_text(self, text: str) -> KeyboardActionResult:
        raise AssertionError(f"Typing is outside this smoke test: {text!r}")


class FakeFolders:
    def open_folder(self, target: str) -> FolderActionResult:
        raise AssertionError(f"Folder action is outside this smoke test: {target!r}")


class FakeController:
    pass


class FakeWindows:
    def __init__(self) -> None:
        self.focused: list[str] = []

    def focus_target(self, target: str) -> WindowActionResult:
        self.focused.append(target)
        return WindowActionResult(True, "Переключаюсь на Яндекс Музыка.")


def make_context():
    settings = Settings(
        wake_phrases=["астра", "астер", "астэр", "астры"],
        allow_commands_without_wake=False,
        allow_voice_conversation_without_wake=False,
        llm_enabled=True,
        llm_router_enabled=True,
    )
    apps = FakeAppManager()
    windows = FakeWindows()
    ai = FakeAIClient()
    responses: list[str] = []
    ctx = TurnContext(
        settings=settings,
        apps={apps.app.name: apps.app},
        app_manager=apps,  # type: ignore[arg-type]
        keyboard=FakeKeyboard(),  # type: ignore[arg-type]
        folders=FakeFolders(),  # type: ignore[arg-type]
        system=FakeController(),  # type: ignore[arg-type]
        vpn=FakeController(),  # type: ignore[arg-type]
        windows=windows,  # type: ignore[arg-type]
        ai_client=ai,  # type: ignore[arg-type]
        logger=logging.getLogger("astra-v12-native-music-test"),
        respond=responses.append,
        get_follow_up=lambda: "",
        allow_conversation_without_wake=False,
        respond_to_unknown=True,
        state=TurnState(),
    )
    return ctx, responses, apps, windows, ai


def test_parser_separates_native_app_and_explicit_website() -> None:
    cases = {
        "открой яндекс музыку": (CommandType.OPEN_APP, "яндекс музыка"),
        "запусти yandex music": (CommandType.OPEN_APP, "яндекс музыка"),
        "включи яндекс мьюзик": (CommandType.OPEN_APP, "яндекс музыка"),
        "закрой яндекс музыку": (CommandType.CLOSE_APP, "яндекс музыка"),
        "переключись на яндекс музыку": (
            CommandType.WINDOW_CONTROL,
            "focus:яндекс музыку",
        ),
        "открой сайт яндекс музыки": (CommandType.OPEN_URL, "яндекс музыки"),
        "открой https://music.yandex.ru": (
            CommandType.OPEN_URL,
            "https://music.yandex.ru",
        ),
    }
    for text, expected in cases.items():
        parsed = parse_command_text(text)
        assert (parsed.type, parsed.target) == expected, (text, parsed)

    assert find_site_url("яндекс музыки") == "https://music.yandex.ru"


def test_config_whitelist_is_narrow() -> None:
    apps = load_apps_config(PROJECT_ROOT / "config" / "apps.json")
    app = apps["яндекс музыка"]
    assert "музыка" not in app.aliases
    assert app.process_name == "Яндекс Музыка.exe"
    assert app.open_command == [
        r"%LOCALAPPDATA%\Programs\YandexMusic\Яндекс Музыка.exe"
    ]

    manager = WindowsAppManager(apps)
    for generic in ("музыка", "музыку", "music", "яндекс", "yandex"):
        assert manager.find_app(generic) is None, generic

    all_aliases = {alias for item in apps.values() for alias in item.aliases}
    for forbidden in ("cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "wt"):
        assert forbidden not in all_aliases, forbidden


def test_direct_resolver_and_honest_missing_result() -> None:
    apps = load_apps_config(PROJECT_ROOT / "config" / "apps.json")
    manager = WindowsAppManager(apps)

    with tempfile.TemporaryDirectory() as temp_dir:
        executable = Path(temp_dir) / "Яндекс Музыка.exe"
        executable.touch()
        env = {
            "ASTRA_YANDEX_MUSIC_PATH": str(executable),
            "LOCALAPPDATA": "",
            "ProgramFiles": "",
            "ProgramFiles(x86)": "",
            "APPDATA": "",
            "ProgramData": "",
            "WINDIR": "",
        }
        with patch.dict(os.environ, env, clear=False):
            assert manager._resolve_open_command(apps["яндекс музыка"]) == [str(executable)]
            with patch.object(subprocess, "Popen") as popen:
                result = manager.open_app("яндекс музыку")
        assert result.ok, result
        launched = popen.call_args.args[0]
        assert launched == [str(executable)], launched
        assert "cmd" not in {part.lower() for part in launched}
        assert "powershell" not in {part.lower() for part in launched}

    empty_env = {
        "ASTRA_YANDEX_MUSIC_PATH": "",
        "LOCALAPPDATA": "",
        "ProgramFiles": "",
        "ProgramFiles(x86)": "",
        "APPDATA": "",
        "ProgramData": "",
        "WINDIR": "",
    }
    with patch.dict(os.environ, empty_env, clear=False), patch(
        "src.windows_app_manager.shutil.which", return_value=None
    ), patch.object(subprocess, "Popen") as popen:
        result = manager.open_app("яндекс музыка")
    assert not result.ok, result
    assert "Не нашёл приложение Яндекс Музыка" in result.message, result
    popen.assert_not_called()


def test_standard_path_and_registered_start_app_fallback() -> None:
    apps = load_apps_config(PROJECT_ROOT / "config" / "apps.json")
    manager = WindowsAppManager(apps)
    app = apps["яндекс музыка"]

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        executable = root / "Programs" / "YandexMusic" / "Яндекс Музыка.exe"
        executable.parent.mkdir(parents=True)
        executable.touch()
        env = {
            "ASTRA_YANDEX_MUSIC_PATH": "",
            "LOCALAPPDATA": str(root),
            "ProgramFiles": "",
            "ProgramFiles(x86)": "",
            "APPDATA": "",
            "ProgramData": "",
        }
        with patch.dict(os.environ, env, clear=False):
            assert manager._resolve_open_command(app) == [str(executable)]

    with tempfile.TemporaryDirectory() as temp_dir:
        app_data = Path(temp_dir)
        shortcut = (
            app_data
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Яндекс Музыка.lnk"
        )
        shortcut.parent.mkdir(parents=True)
        shortcut.touch()
        env = {
            "ASTRA_YANDEX_MUSIC_PATH": "",
            "LOCALAPPDATA": "",
            "ProgramFiles": "",
            "ProgramFiles(x86)": "",
            "APPDATA": str(app_data),
            "ProgramData": "",
            "WINDIR": "",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "src.windows_app_manager.shutil.which",
            return_value=r"C:\Windows\explorer.exe",
        ):
            command = manager._resolve_open_command(app)
        assert command == [
            r"C:\Windows\explorer.exe",
            r"shell:AppsFolder\ru.yandex.desktop.music",
        ], command


def test_runtime_is_local_wake_only_and_follow_up_is_bounded() -> None:
    ctx, responses, apps, windows, ai = make_context()
    process_turn("открой яндекс музыку", ctx)
    assert responses == ["Назови меня перед этой командой."], responses
    assert not apps.opened and ai.route_calls == 0 and ai.ask_calls == 0

    process_turn("Астра, открой яндекс музыку", ctx)
    assert apps.opened == ["яндекс музыка"], apps.opened
    assert responses[-1] == "Открываю.", responses
    assert ctx.state.last_context_target == "яндекс музыка"

    follow_ctx, follow_responses, follow_apps, _windows, follow_ai = make_context()
    process_turn("Астра, включи музыку", follow_ctx)
    assert follow_ctx.state.pending_kind == "ambiguous_music"
    process_turn("Яндекс музыку", follow_ctx)
    assert follow_apps.opened == ["яндекс музыка"], follow_apps.opened
    assert follow_responses[-1] == "Открываю.", follow_responses

    process_turn("Астра, закрой яндекс музыку", ctx)
    assert apps.closed == ["яндекс музыка"], apps.closed
    process_turn("Астра, переключись на яндекс музыку", ctx)
    assert windows.focused == ["яндекс музыку"], windows.focused
    assert ai.route_calls == 0 and ai.ask_calls == 0
    assert follow_ai.route_calls == 0 and follow_ai.ask_calls == 0


def test_explicit_website_stays_out_of_app_launcher() -> None:
    ctx, responses, apps, _windows, ai = make_context()
    opened_urls: list[str] = []
    with patch.object(
        astra_main.webbrowser,
        "open",
        side_effect=lambda url: opened_urls.append(url) or True,
    ):
        process_turn("Астра, открой сайт Яндекс Музыки", ctx)

    assert opened_urls == ["https://music.yandex.ru"], opened_urls
    assert not apps.opened
    assert responses[-1] == "Открываю сайт.", responses
    assert ai.route_calls == 0 and ai.ask_calls == 0


def test_window_aliases_match_native_process() -> None:
    controller = WindowController.__new__(WindowController)
    controller.browser_preferred = ""
    aliases = controller._target_aliases("яндекс музыку")
    assert "яндекс музыка" in aliases
    assert controller._display_process_name("Яндекс Музыка") == "Яндекс Музыка"


def main() -> None:
    test_parser_separates_native_app_and_explicit_website()
    test_config_whitelist_is_narrow()
    test_direct_resolver_and_honest_missing_result()
    test_standard_path_and_registered_start_app_fallback()
    test_runtime_is_local_wake_only_and_follow_up_is_bounded()
    test_explicit_website_stays_out_of_app_launcher()
    test_window_aliases_match_native_process()
    print("v1.2 native Yandex Music smoke tests passed")


if __name__ == "__main__":
    main()
