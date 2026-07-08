from __future__ import annotations

from pathlib import Path
import logging
import sys
import types

# This smoke test imports main.py, which imports src.ai_client. The actual
# Windows project environment has the openai package installed, but this test
# must also be runnable in lightweight review sandboxes where network/LLM
# dependencies are absent. We stub only the names needed during import; the
# fake AI client below ensures no LLM path is executed.
if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")

    class _OpenAI:  # pragma: no cover - import stub only
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

    class _Recognizer:  # pragma: no cover - import stub only
        def __init__(self) -> None:
            self.dynamic_energy_threshold = True
            self.energy_threshold = 300
            self.pause_threshold = 0.8
            self.non_speaking_duration = 0.5

    class _Microphone:  # pragma: no cover - import stub only
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
from src.config_loader import Settings
from src.command_parser import CommandType, extract_command_after_wake
from src.keyboard_controller import KeyboardActionResult
from src.task_router import AssistantAction, ActionType


class FakeAIClient:
    def __init__(self) -> None:
        self.route_called = False
        self.ask_called = False

    def route_command(self, text: str, apps=None) -> AssistantAction:
        self.route_called = True
        raise AssertionError(f"Router must not be called for this test: {text!r}")

    def ask(self, text: str):
        self.ask_called = True
        raise AssertionError(f"LLM ask must not be called for this test: {text!r}")


class FakeAppManager:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.closed: list[str] = []

    def find_app(self, target: str):
        return None

    def open_app(self, target: str):
        self.opened.append(target)
        return type("Result", (), {"message": "Открываю."})()

    def close_app(self, target: str):
        self.closed.append(target)
        return type("Result", (), {"message": "Закрываю."})()


class FakeKeyboard:
    def send_shortcut(self, name: str) -> KeyboardActionResult:
        return KeyboardActionResult(True, "Готово.")

    def type_text(self, text: str) -> KeyboardActionResult:
        return KeyboardActionResult(True, "Пишу.")


class FakeController:
    def __getattr__(self, name: str):
        def _method(*args, **kwargs):
            return type("Result", (), {"message": "Готово."})()
        return _method


class FakeVpn:
    def status(self):
        return type("Result", (), {"message": "VPN включён."})()

    def connect(self):
        return type("Result", (), {"message": "VPN включён."})()

    def disconnect(self):
        return type("Result", (), {"message": "VPN выключен."})()


def make_context() -> tuple[TurnContext, list[str], FakeAIClient, FakeAppManager]:
    settings = Settings(
        allow_commands_without_wake=False,
        allow_text_conversation_without_wake=True,
        allow_voice_conversation_without_wake=False,
        voice_runtime_mode="wake_only",
        wake_only_mode=True,
    )
    responses: list[str] = []
    ai = FakeAIClient()
    app_manager = FakeAppManager()

    ctx = TurnContext(
        settings=settings,
        apps={},
        app_manager=app_manager,  # type: ignore[arg-type]
        keyboard=FakeKeyboard(),  # type: ignore[arg-type]
        folders=FakeController(),  # type: ignore[arg-type]
        system=FakeController(),  # type: ignore[arg-type]
        vpn=FakeVpn(),  # type: ignore[arg-type]
        windows=FakeController(),  # type: ignore[arg-type]
        ai_client=ai,  # type: ignore[arg-type]
        logger=logging.getLogger("astra-test"),
        respond=responses.append,
        get_follow_up=lambda: "",
        allow_conversation_without_wake=False,
        respond_to_unknown=True,
        state=TurnState(),
    )
    return ctx, responses, ai, app_manager


def test_no_wake_command_like_blocks_before_router() -> None:
    for text in ("открой блокнот", "закрой блокнот", "открой youtube.com", "нажми enter"):
        ctx, responses, ai, app_manager = make_context()
        process_turn(text, ctx)
        assert responses == ["Назови меня перед этой командой."], (text, responses)
        assert not ai.route_called, text
        assert not ai.ask_called, text
        assert not app_manager.opened, text
        assert not app_manager.closed, text


def test_wake_extraction_core_cases() -> None:
    wake_phrases = ["астра", "эй астра", "привет астра"]
    parsed = extract_command_after_wake("открой YouTube", wake_phrases)
    assert parsed.type == CommandType.NO_WAKE, parsed

    parsed = extract_command_after_wake("Астра", wake_phrases)
    assert parsed.type == CommandType.WAKE_ONLY, parsed

    parsed = extract_command_after_wake("Астра, открой YouTube", wake_phrases)
    assert parsed.type == CommandType.OPEN_URL and parsed.target == "youtube", parsed

    parsed = extract_command_after_wake("Астра, статус VPN", wake_phrases)
    assert parsed.type == CommandType.VPN_CONTROL and parsed.target == "status", parsed


def test_pending_followup_accepts_bare_and_wake_prefixed_answer() -> None:
    opened_urls: list[str] = []
    original_open = astra_main.webbrowser.open
    astra_main.webbrowser.open = lambda url: opened_urls.append(url) or True
    try:
        ctx, responses, ai, _app_manager = make_context()
        process_turn("Астра, открой", ctx)
        assert responses[-1] == "Что открыть?", responses
        assert ctx.state.pending_kind == "open"
        process_turn("ютуб", ctx)
        assert opened_urls and "youtube" in opened_urls[-1].lower(), opened_urls
        assert responses[-1] == "Открываю сайт.", responses
        assert not ai.route_called

        opened_urls.clear()
        ctx, responses, ai, _app_manager = make_context()
        process_turn("Астра, открой", ctx)
        process_turn("Астра, ютуб", ctx)
        assert opened_urls and "youtube" in opened_urls[-1].lower(), opened_urls
        assert responses[-1] == "Открываю сайт.", responses
        assert not ai.route_called
    finally:
        astra_main.webbrowser.open = original_open


def test_wake_only_runtime_markers_present() -> None:
    main_py = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "def _listen_pending_voice_follow_up" in main_py
    assert "Слушаю уточнение" in main_py
    assert "wake_allow_direct_command" in main_py
    assert "Wake-only voice runtime enabled" in main_py


def main() -> None:
    test_no_wake_command_like_blocks_before_router()
    test_wake_extraction_core_cases()
    test_pending_followup_accepts_bare_and_wake_prefixed_answer()
    test_wake_only_runtime_markers_present()
    print("v0.11 wake runtime smoke tests passed")


if __name__ == "__main__":
    main()
