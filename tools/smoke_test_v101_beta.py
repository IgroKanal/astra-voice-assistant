from __future__ import annotations

import logging
from pathlib import Path
import sys
import tempfile
import types
import zipfile


# Keep this smoke test runnable in lightweight review environments. Production
# still uses the real packages from requirements.txt.
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
from main import TurnContext, TurnState, choose_stt_alternative, process_turn, run_voice_mode
from src.audio_io import ListenResult, VoiceIO
from src.command_parser import CommandType, extract_command_after_wake
from src.config_loader import Settings, load_apps_config
from src.keyboard_controller import KeyboardActionResult, KeyboardController
from src.task_router import normalize_url_or_site
from src.windows_app_manager import WindowsAppManager
from tools.validate_package import validate_zip


WAKE_PHRASES = [
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


class FakeVoiceIO:
    def __init__(self, inputs: list[str]) -> None:
        self.inputs = list(inputs)
        self.spoken: list[str] = []
        self.prompts: list[str] = []
        self.alternative_selector = None

    def set_alternative_selector(self, selector) -> None:
        self.alternative_selector = selector

    def listen_once(self, **kwargs) -> ListenResult:
        self.prompts.append(str(kwargs.get("prompt", "")))
        if not self.inputs:
            raise AssertionError("FakeVoiceIO input queue is empty")
        text = self.inputs.pop(0)
        return ListenResult(True, text=text, alternatives=[text])

    def speak(self, text: str) -> None:
        self.spoken.append(text)


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

    def find_app(self, target: str):
        return None

    def open_app(self, target: str):
        self.opened.append(target)
        return types.SimpleNamespace(message="Открываю.")

    def close_app(self, target: str):
        self.closed.append(target)
        return types.SimpleNamespace(message="Закрываю.")


class FakeKeyboard:
    def __init__(self) -> None:
        self.shortcuts: list[str] = []
        self.typed: list[str] = []

    def send_shortcut(self, name: str) -> KeyboardActionResult:
        self.shortcuts.append(name)
        return KeyboardActionResult(True, "Готово.")

    def type_text(self, text: str) -> KeyboardActionResult:
        self.typed.append(text)
        return KeyboardActionResult(True, "Пишу.")


class FakeController:
    def __getattr__(self, name: str):
        def _method(*args, **kwargs):
            return types.SimpleNamespace(message="Готово.")

        return _method


class FakeVpn:
    def status(self):
        return types.SimpleNamespace(message="VPN включён.")

    def connect(self):
        return types.SimpleNamespace(message="VPN включён.")

    def disconnect(self):
        return types.SimpleNamespace(message="VPN выключен.")


def _settings() -> Settings:
    return Settings(
        wake_phrases=WAKE_PHRASES,
        allow_commands_without_wake=False,
        allow_text_conversation_without_wake=True,
        allow_voice_conversation_without_wake=False,
        voice_runtime_mode="wake_only",
        wake_only_mode=True,
        wake_response_enabled=True,
        wake_response_text="Слушаю.",
        wake_allow_direct_command=True,
    )


def test_full_wake_runtime() -> None:
    fake_voice = FakeVoiceIO(
        [
            "открой блокнот",
            "открой youtube.com",
            "закрой блокнот",
            "нажми enter",
            "стоп",
            "Астра",
            "открой YouTube",
            "Астра, открой YouTube",
            "Астра, открой",
            "ютуб",
            "открой блокнот",
            "Астра, стоп",
        ]
    )
    ai = FakeAIClient()
    apps = FakeAppManager()
    keyboard = FakeKeyboard()
    opened_urls: list[str] = []

    original_voice_io = astra_main.VoiceIO
    original_web_open = astra_main.webbrowser.open
    astra_main.VoiceIO = lambda settings, logger: fake_voice  # type: ignore[assignment]
    astra_main.webbrowser.open = lambda url: opened_urls.append(url) or True

    try:
        run_voice_mode(
            settings=_settings(),
            apps={},
            app_manager=apps,  # type: ignore[arg-type]
            keyboard=keyboard,  # type: ignore[arg-type]
            folders=FakeController(),  # type: ignore[arg-type]
            system=FakeController(),  # type: ignore[arg-type]
            vpn=FakeVpn(),  # type: ignore[arg-type]
            windows=FakeController(),  # type: ignore[arg-type]
            ai_client=ai,  # type: ignore[arg-type]
            logger=logging.getLogger("astra-v101-runtime-test"),
        )
    finally:
        astra_main.VoiceIO = original_voice_io
        astra_main.webbrowser.open = original_web_open

    assert len(opened_urls) == 3, opened_urls
    assert all("youtube" in url.lower() for url in opened_urls), opened_urls
    assert fake_voice.spoken.count("Слушаю.") == 1, fake_voice.spoken
    assert "Что открыть?" in fake_voice.spoken, fake_voice.spoken
    assert fake_voice.spoken[-1] == "Завершаю работу.", fake_voice.spoken
    assert not apps.opened and not apps.closed, (apps.opened, apps.closed)
    assert not keyboard.shortcuts and not keyboard.typed
    assert ai.route_calls == 0 and ai.ask_calls == 0
    assert not fake_voice.inputs, fake_voice.inputs


def test_wake_aliases_alternatives_and_boundaries() -> None:
    for alias in ("Астер", "Астэр", "Астры"):
        parsed = extract_command_after_wake(f"{alias}, стоп", WAKE_PHRASES)
        assert parsed.type == CommandType.EXIT, (alias, parsed)

    for text in ("Австрия стоп", "астериск стоп", "астероид стоп", "контрасты стоп"):
        parsed = extract_command_after_wake(text, WAKE_PHRASES)
        assert parsed.type == CommandType.NO_WAKE, (text, parsed)

    selected = choose_stt_alternative(
        ["Австрия стоп", "Астры стоп", "остры стоп"],
        _settings(),
        FakeAppManager(),  # type: ignore[arg-type]
        logging.getLogger("astra-v101-stt-test"),
    )
    assert selected == "Астры стоп", selected


def test_short_close_fragments_never_become_apps() -> None:
    apps = WindowsAppManager(load_apps_config(PROJECT_ROOT / "config" / "apps.json"))
    for fragment in ("ок", "ак", "аг"):
        parsed = extract_command_after_wake(f"Астра, закрой {fragment}", WAKE_PHRASES)
        assert parsed.type == CommandType.CLOSE_APP, (fragment, parsed)
        assert parsed.target == "__unsupported_close__", (fragment, parsed)
        assert apps.find_app(fragment) is None, fragment


def test_url_paths_and_queries_stay_local() -> None:
    cases = {
        "Астра, открой youtube.com": "https://youtube.com",
        "Астра, открой сайт youtube.com": "https://youtube.com",
        "Астра, открой https://example.com": "https://example.com",
        "Астра, открой https://example.com/path?q=1": "https://example.com/path?q=1",
        "Астра, открой сайт www.youtube.com/watch?v=abc": "https://www.youtube.com/watch?v=abc",
        "Астра, открой https://example.com/CaseSensitive?Token=AbC": (
            "https://example.com/CaseSensitive?Token=AbC"
        ),
        "Астра, открой https://www.youtube.com/watch?v=dQw4w9WgXcQ": (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        ),
        "Астра, открой сайт example.com/%2FPath?next=%2FCaseSensitive": (
            "https://example.com/%2FPath?next=%2FCaseSensitive"
        ),
        "Астра, открой https://example.com/Case!": "https://example.com/Case!",
    }

    for text, expected_url in cases.items():
        parsed = extract_command_after_wake(text, WAKE_PHRASES)
        assert parsed.type == CommandType.OPEN_URL, (text, parsed)
        assert normalize_url_or_site(parsed.target) == expected_url, (text, parsed)

    mixed_case_url = "https://example.com/CaseSensitive?Token=AbC"
    assert normalize_url_or_site(mixed_case_url) == mixed_case_url


def test_incomplete_enter_does_not_press_a_key_or_call_llm() -> None:
    parsed = extract_command_after_wake("Астра, отправь нажми", WAKE_PHRASES)
    assert parsed.type == CommandType.KEYBOARD_SHORTCUT, parsed
    assert parsed.target == "incomplete_key", parsed

    controller = object.__new__(KeyboardController)
    controller.logger = logging.getLogger("astra-v101-key-test")
    result = controller.send_shortcut(parsed.target)
    assert not result.ok, result
    assert "нажми Enter" in result.message, result


def test_shell_apps_are_not_executable_targets() -> None:
    apps = load_apps_config(PROJECT_ROOT / "config" / "apps.json")
    manager = WindowsAppManager(apps)
    ai = FakeAIClient()
    responses: list[str] = []
    ctx = TurnContext(
        settings=_settings(),
        apps=apps,
        app_manager=manager,
        keyboard=FakeKeyboard(),  # type: ignore[arg-type]
        folders=FakeController(),  # type: ignore[arg-type]
        system=FakeController(),  # type: ignore[arg-type]
        vpn=FakeVpn(),  # type: ignore[arg-type]
        windows=FakeController(),  # type: ignore[arg-type]
        ai_client=ai,  # type: ignore[arg-type]
        logger=logging.getLogger("astra-v101-shell-test"),
        respond=responses.append,
        get_follow_up=lambda: "",
        allow_conversation_without_wake=False,
        respond_to_unknown=True,
        state=TurnState(),
    )

    for target in ("cmd", "powershell"):
        assert manager.find_app(target) is None, target
        process_turn(f"Астра, открой {target}", ctx)
        assert responses[-1] == "Не нашёл такое приложение в списке.", responses

    assert ai.route_calls == 0 and ai.ask_calls == 0


def test_terminal_guard_for_typing_and_enter() -> None:
    terminal_processes = (
        "cmd",
        "powershell",
        "pwsh",
        "windowsterminal",
        "wt",
        "conhost",
        "code",
        "cursor",
        "vscodium",
        "code-insiders",
        "code - insiders",
        "powershell_ise",
    )

    for process_name in terminal_processes:
        controller = object.__new__(KeyboardController)
        controller.logger = logging.getLogger("astra-v101-terminal-test")
        controller._foreground_process_name = lambda name=process_name: name  # type: ignore[method-assign]

        type_result = controller.type_text("whoami")
        enter_result = controller.send_shortcut("enter")
        assert not type_result.ok, process_name
        assert not enter_result.ok, process_name
        assert "терминал" in type_result.message.lower(), (process_name, type_result)
        assert "терминал" in enter_result.message.lower(), (process_name, enter_result)


def test_tts_prewarm_caps_failed_attempts() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        settings = Settings(
            tts_cache_prewarm_phrases=["one", "two", "three"],
            tts_cache_prewarm_max_new_phrases=1,
            tts_cache_generation_timeout_seconds=8,
        )
        voice = object.__new__(VoiceIO)
        voice.settings = settings
        voice.logger = logging.getLogger("astra-v101-prewarm-test")
        attempts: list[str] = []

        def cache_path(_self, text: str, voice: str) -> Path:
            return Path(temp_dir) / f"{text}.mp3"

        def fail_generation(_self, text: str, voice: str):
            attempts.append(text)
            return None

        voice._edge_cache_path = types.MethodType(cache_path, voice)  # type: ignore[method-assign]
        voice._ensure_edge_cached_audio = types.MethodType(  # type: ignore[method-assign]
            fail_generation,
            voice,
        )
        voice._prewarm_tts_cache()

        assert attempts == ["one"], attempts
        assert settings.tts_cache_generation_timeout_seconds <= 10


def test_package_validator_rejects_secrets_and_forbidden_files() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        safe_zip = Path(temp_dir) / "safe.zip"
        with zipfile.ZipFile(safe_zip, "w") as archive:
            archive.writestr("main.py", "print('safe')\n")
            archive.writestr("src/config.py", "llm_api_key=_load_api_key()\n")
            archive.writestr(".env.example", "GEMINI_API_KEY=PASTE_YOUR_GEMINI_KEY_HERE\n")
            archive.writestr(".env.sanitized", "GEMINI_API_KEY=REMOVED\n")
        assert validate_zip(safe_zip) == []

        unsafe_zip = Path(temp_dir) / "unsafe.zip"
        with zipfile.ZipFile(unsafe_zip, "w") as archive:
            archive.writestr(".git/", b"")
            archive.writestr(".env", "GEMINI_API_KEY=AIza" + "A" * 35 + "\n")
            archive.writestr("logs/app.log", "secret\n")
            archive.writestr("cache/voice.mp3", b"mp3")
        problems = validate_zip(unsafe_zip)
        assert any("forbidden directory: .git" in item for item in problems), problems
        assert any("forbidden file: .env" in item for item in problems), problems
        assert any("forbidden directory: logs" in item for item in problems), problems
        assert any("forbidden directory: cache" in item for item in problems), problems


def test_current_package_script_markers() -> None:
    review_script = (PROJECT_ROOT / "tools" / "build_review_package.ps1").read_text(
        encoding="utf-8"
    )
    release_script = (PROJECT_ROOT / "tools" / "build_beta_package.ps1").read_text(
        encoding="utf-8"
    )

    for script in (review_script, release_script):
        assert "v1.1" in script
        assert "validate_package.py" in script
        assert "--source-root" in script
        assert "smoke_test_v101_beta.py" in script
        assert '".env"' in script
        assert "roboExit -gt 7" in script
        assert '@"' not in script and "@'" not in script


def main() -> None:
    test_full_wake_runtime()
    test_wake_aliases_alternatives_and_boundaries()
    test_short_close_fragments_never_become_apps()
    test_url_paths_and_queries_stay_local()
    test_incomplete_enter_does_not_press_a_key_or_call_llm()
    test_shell_apps_are_not_executable_targets()
    test_terminal_guard_for_typing_and_enter()
    test_tts_prewarm_caps_failed_attempts()
    test_package_validator_rejects_secrets_and_forbidden_files()
    test_current_package_script_markers()
    print("v1.0.1 beta bugfix/reliability smoke tests passed")


if __name__ == "__main__":
    main()
