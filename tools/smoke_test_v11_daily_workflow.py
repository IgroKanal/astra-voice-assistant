from __future__ import annotations

import json
import logging
from pathlib import Path
import sys
import tempfile
import time
import types
import zipfile


# Keep the smoke test importable in lightweight review environments.
if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")

    class _OpenAI:
        pass

    class _OpenAIError(Exception):
        pass

    openai_stub.OpenAI = _OpenAI
    openai_stub.APIConnectionError = _OpenAIError
    openai_stub.APIStatusError = _OpenAIError
    openai_stub.APITimeoutError = _OpenAIError
    openai_stub.OpenAIError = _OpenAIError
    sys.modules["openai"] = openai_stub

if "speech_recognition" not in sys.modules:
    sr_stub = types.ModuleType("speech_recognition")

    class _Recognizer:
        def __init__(self) -> None:
            self.dynamic_energy_threshold = True
            self.energy_threshold = 300
            self.pause_threshold = 0.8
            self.non_speaking_duration = 0.5

    class _Microphone:
        pass

    sr_stub.Recognizer = _Recognizer
    sr_stub.Microphone = _Microphone
    sys.modules["speech_recognition"] = sr_stub

if "pyttsx3" not in sys.modules:
    pyttsx3_stub = types.ModuleType("pyttsx3")
    pyttsx3_stub.init = lambda: None
    sys.modules["pyttsx3"] = pyttsx3_stub


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main as astra_main
from main import TurnContext, TurnState, process_turn
from src.command_parser import CommandType, extract_command_after_wake, parse_command_text
from src.config_loader import AppConfig, Settings
from src.keyboard_controller import KeyboardActionResult
from src.routine_controller import RoutineConfigError, RoutineController
from tools.validate_package import validate_zip


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
        self.telegram = AppConfig(
            name="telegram",
            aliases=["телеграм", "telegram"],
            open_command=["Telegram.exe"],
            process_name="Telegram.exe",
        )

    def find_app(self, target: str):
        if target.lower() in {"telegram", "телеграм"}:
            return self.telegram
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
    def __init__(self) -> None:
        self.shortcuts: list[str] = []

    def send_shortcut(self, name: str) -> KeyboardActionResult:
        self.shortcuts.append(name)
        return KeyboardActionResult(True, "Готово.")

    def type_text(self, text: str) -> KeyboardActionResult:
        raise AssertionError(f"Typing is outside this smoke test: {text!r}")


class FakeFolders:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def open_folder(self, target: str):
        self.opened.append(target)
        return types.SimpleNamespace(ok=True, message="Открываю папку.")


class FakeWindows:
    def __init__(self) -> None:
        self.focused: list[str] = []
        self.previous_calls = 0

    def focus_target(self, target: str):
        self.focused.append(target)
        return types.SimpleNamespace(ok=False, message="Не нашёл такое открытое окно.")

    def focus_previous_window(self):
        self.previous_calls += 1
        return types.SimpleNamespace(ok=True, message="Возвращаю предыдущее окно.")

    def __getattr__(self, _name: str):
        return lambda *args, **kwargs: types.SimpleNamespace(ok=True, message="Готово.")


class FakeController:
    def __getattr__(self, _name: str):
        return lambda *args, **kwargs: types.SimpleNamespace(ok=True, message="Готово.")


def make_context() -> tuple[
    TurnContext,
    list[str],
    FakeAIClient,
    FakeAppManager,
    FakeKeyboard,
    FakeFolders,
    FakeWindows,
]:
    responses: list[str] = []
    ai = FakeAIClient()
    apps = FakeAppManager()
    keyboard = FakeKeyboard()
    folders = FakeFolders()
    windows = FakeWindows()
    routines = RoutineController(PROJECT_ROOT / "config" / "routines.json")
    ctx = TurnContext(
        settings=Settings(
            wake_phrases=["астра", "астер", "астэр", "астры"],
            allow_commands_without_wake=False,
            allow_voice_conversation_without_wake=False,
            context_ttl_seconds=120.0,
        ),
        apps={},
        app_manager=apps,  # type: ignore[arg-type]
        keyboard=keyboard,  # type: ignore[arg-type]
        folders=folders,  # type: ignore[arg-type]
        system=FakeController(),  # type: ignore[arg-type]
        vpn=FakeController(),  # type: ignore[arg-type]
        windows=windows,  # type: ignore[arg-type]
        ai_client=ai,  # type: ignore[arg-type]
        logger=logging.getLogger("astra-v11-daily-workflow-test"),
        respond=responses.append,
        get_follow_up=lambda: "",
        allow_conversation_without_wake=False,
        respond_to_unknown=True,
        state=TurnState(),
        routines=routines,
    )
    return ctx, responses, ai, apps, keyboard, folders, windows


def test_parser_and_youtube_query_preservation() -> None:
    cases = {
        "включи рабочий режим": (CommandType.ROUTINE, "рабочий режим"),
        "пауза": (CommandType.KEYBOARD_SHORTCUT, "media_play_pause"),
        "следующий трек": (CommandType.KEYBOARD_SHORTCUT, "media_next"),
        "предыдущий трек": (CommandType.KEYBOARD_SHORTCUT, "media_previous"),
        "останови музыку": (CommandType.KEYBOARD_SHORTCUT, "media_stop"),
        "открой музыку": (CommandType.OPEN_FOLDER, "музыку"),
        "открой яндекс музыку": (CommandType.OPEN_URL, "яндекс музыку"),
        "откроется AMD": (CommandType.OPEN_APP, "amd"),
        "вернись обратно": (CommandType.WINDOW_CONTROL, "previous"),
    }
    for text, expected in cases.items():
        parsed = parse_command_text(text)
        assert (parsed.type, parsed.target) == expected, (text, parsed)

    parsed = parse_command_text("найди на ютубе Python 3.12 C++")
    assert parsed.type == CommandType.WEB_SEARCH, parsed
    assert parsed.target == "youtube:Python 3.12 C++", parsed


def test_no_wake_new_actions_are_isolated() -> None:
    for text in (
        "включи рабочий режим",
        "следующий трек",
        "вернись обратно",
        "откроется AMD",
    ):
        ctx, responses, ai, apps, keyboard, folders, windows = make_context()
        process_turn(text, ctx)
        assert responses == ["Назови меня перед этой командой."], (text, responses)
        assert not apps.opened and not apps.closed
        assert not keyboard.shortcuts and not folders.opened and not windows.previous_calls
        assert ai.route_calls == 0 and ai.ask_calls == 0


def test_routine_execution_is_local_and_bounded() -> None:
    ctx, responses, ai, apps, _keyboard, _folders, windows = make_context()
    opened_urls: list[str] = []
    original_open = astra_main.webbrowser.open
    astra_main.webbrowser.open = lambda url: opened_urls.append(url) or True
    try:
        process_turn("Астра, включи рабочий режим", ctx)
    finally:
        astra_main.webbrowser.open = original_open

    assert opened_urls == ["https://chatgpt.com"], opened_urls
    assert apps.opened == ["telegram"], apps.opened
    assert windows.focused == ["telegram"], windows.focused
    assert responses[-1] == "Рабочий режим готов.", responses
    assert ai.route_calls == 0 and ai.ask_calls == 0


def test_context_pronoun_and_previous_window() -> None:
    ctx, responses, ai, apps, keyboard, _folders, windows = make_context()
    process_turn("Астра, открой телеграм", ctx)
    assert ctx.state.last_context_kind == "app"
    process_turn("Астра, закрой его", ctx)
    assert apps.closed == ["telegram"], apps.closed

    opened_urls: list[str] = []
    original_open = astra_main.webbrowser.open
    astra_main.webbrowser.open = lambda url: opened_urls.append(url) or True
    try:
        process_turn("Астра, открой ютуб", ctx)
        process_turn("Астра, закрой его", ctx)
    finally:
        astra_main.webbrowser.open = original_open
    assert keyboard.shortcuts[-1] == "close_tab", keyboard.shortcuts

    process_turn("Астра, вернись обратно", ctx)
    assert windows.previous_calls == 1

    ctx.state.last_context_kind = "app"
    ctx.state.last_context_target = "telegram"
    ctx.state.last_context_at = (
        time.monotonic() - ctx.settings.context_ttl_seconds - 1.0
    )
    process_turn("Астра, закрой его", ctx)
    assert responses[-1].startswith("Не помню"), responses
    assert apps.closed == ["telegram"], apps.closed
    assert ai.route_calls == 0 and ai.ask_calls == 0


def test_music_follow_up_and_youtube_search() -> None:
    ctx, responses, ai, _apps, _keyboard, folders, _windows = make_context()
    process_turn("Астра, включи музыку", ctx)
    assert ctx.state.pending_kind == "ambiguous_music"
    assert "локальную" in responses[-1]
    process_turn("локальную", ctx)
    assert folders.opened == ["музыку"], folders.opened

    opened_urls: list[str] = []
    original_open = astra_main.webbrowser.open
    astra_main.webbrowser.open = lambda url: opened_urls.append(url) or True
    try:
        yandex_ctx, yandex_responses, yandex_ai, *_ = make_context()
        process_turn("Астра, включи музыку", yandex_ctx)
        process_turn("Яндекс музыку", yandex_ctx)
        assert opened_urls == ["https://music.yandex.ru"], opened_urls
        assert yandex_responses[-1] == "Открываю сайт.", yandex_responses
        assert yandex_ai.route_calls == 0 and yandex_ai.ask_calls == 0

        process_turn("Астра, найди на ютубе Python 3.12 C++", ctx)
    finally:
        astra_main.webbrowser.open = original_open
    assert "youtube.com/results" in opened_urls[-1], opened_urls
    assert "Python+3.12+C%2B%2B" in opened_urls[-1], opened_urls
    assert ai.route_calls == 0 and ai.ask_calls == 0


def test_action_like_stt_substitution_never_reaches_conversation_llm() -> None:
    ctx, responses, ai, apps, *_ = make_context()
    process_turn("Астра, откроется AMD", ctx)
    assert responses[-1] == "Не нашёл такое приложение в списке.", responses
    assert not apps.opened
    assert ai.route_calls == 0 and ai.ask_calls == 0


def test_routine_config_rejects_privilege_expansion() -> None:
    bad_routines = (
        {"action": "keyboard_shortcut", "target": "enter"},
        {"action": "type_text", "target": "whoami"},
        {"action": "open_app", "target": "powershell.exe"},
        {"action": "open_url", "target": "file:///C:/Windows/System32"},
        {"action": "open_url", "target": "javascript:alert(1)"},
        {"action": "open_app", "target": "telegram", "command": "whoami"},
    )
    for step in bad_routines:
        payload = {
            "routines": {
                "unsafe": {
                    "aliases": ["опасный режим"],
                    "response": "Готово.",
                    "steps": [step],
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "routines.json"
            config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            try:
                RoutineController(config_path)
            except RoutineConfigError:
                pass
            else:
                raise AssertionError(f"Unsafe routine step accepted: {step!r}")


def test_wake_aliases_keep_new_actions_local() -> None:
    for alias in ("Астер", "Астэр", "Астры"):
        parsed = extract_command_after_wake(f"{alias}, следующий трек", ["астер", "астэр", "астры"])
        assert parsed.type == CommandType.KEYBOARD_SHORTCUT, (alias, parsed)
        assert parsed.target == "media_next", (alias, parsed)


def test_package_source_match_detects_stale_zip() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "source"
        root.mkdir()
        (root / "main.py").write_text("current\n", encoding="utf-8")
        archive_path = Path(temp_dir) / "package.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("main.py", "stale\n")
        findings = validate_zip(archive_path, source_root=root)
        assert any("content differs" in item for item in findings), findings


def main() -> None:
    test_parser_and_youtube_query_preservation()
    test_no_wake_new_actions_are_isolated()
    test_routine_execution_is_local_and_bounded()
    test_context_pronoun_and_previous_window()
    test_music_follow_up_and_youtube_search()
    test_action_like_stt_substitution_never_reaches_conversation_llm()
    test_routine_config_rejects_privilege_expansion()
    test_wake_aliases_keep_new_actions_local()
    test_package_source_match_detects_stale_zip()
    print("v1.1 daily workflow smoke tests passed")


if __name__ == "__main__":
    main()
