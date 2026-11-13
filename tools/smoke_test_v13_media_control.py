from __future__ import annotations

import dataclasses
import logging
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main as astra_main
from src.command_parser import CommandType, extract_command_after_wake, parse_command_text
from src.config_loader import AppConfig
from src.keyboard_controller import KeyboardController
from src.media_controller import MediaController
from src.windows_app_manager import WindowsAppManager
from tools.smoke_test_v11_daily_workflow import make_context


class FakeKeyboard:
    def __init__(self) -> None:
        self.shortcuts: list[str] = []
        self.media_calls: list[tuple[str, str, int]] = []
        self.fail_media_calls = 0

    def send_shortcut(self, name: str):
        self.shortcuts.append(name)
        return SimpleNamespace(ok=True, message={
            "media_stop": "Останавливаю музыку.",
            "media_next": "Следующий трек.",
            "media_previous": "Предыдущий трек.",
            "media_play_pause": "Переключаю паузу.",
            "media_play": "Включаю воспроизведение.",
        }.get(name, "Готово."))

    def send_media_shortcut(self, name: str, *, target: str = "", repeat: int = 1):
        self.media_calls.append((name, target, repeat))
        if self.fail_media_calls > 0:
            self.fail_media_calls -= 1
            return SimpleNamespace(ok=False, message="Не нашёл открытый выбранный медиаплеер.")
        message = {
            "media_stop": "Останавливаю музыку.",
            "media_next": "Следующий трек.",
            "media_previous": (
                "Переключаю на предыдущий трек."
                if repeat == 2
                else "Начинаю трек заново."
            ),
            "media_play_pause": "Переключаю паузу.",
            "media_play": "Включаю воспроизведение.",
        }.get(name, "Готово.")
        return SimpleNamespace(ok=True, message=message)


class FakeApps:
    def __init__(self, close_ok: bool = True, open_ok: bool = True) -> None:
        self.closed: list[str] = []
        self.opened: list[str] = []
        self.close_ok = close_ok
        self.open_ok = open_ok

    def open_app(self, target: str):
        self.opened.append(target)
        return SimpleNamespace(ok=self.open_ok, message=(
            "Открываю." if self.open_ok else "Не удалось открыть локальный плеер."
        ))

    def close_app(self, target: str):
        self.closed.append(target)
        return SimpleNamespace(ok=self.close_ok, message=(
            "Яндекс Музыка закрыта." if self.close_ok else "Не удалось закрыть Яндекс Музыку."
        ))


def test_parser() -> None:
    cases = {
        "выключи музыку": (CommandType.MEDIA_CONTROL, "shutdown_yandex_music"),
        "закрой музыку": (CommandType.MEDIA_CONTROL, "shutdown_yandex_music"),
        "останови музыку": (CommandType.KEYBOARD_SHORTCUT, "media_stop"),
        "верни предыдущий трек": (CommandType.KEYBOARD_SHORTCUT, "media_previous"),
        "начни трек заново": (CommandType.KEYBOARD_SHORTCUT, "media_restart_current"),
        "следующий трек в локальном плеере": (
            CommandType.MEDIA_CONTROL,
            "next:local",
        ),
        "предыдущий трек в локальном плеере": (
            CommandType.MEDIA_CONTROL,
            "previous:local",
        ),
        "поставь локальный плеер на паузу": (
            CommandType.MEDIA_CONTROL,
            "play_pause:local",
        ),
        "останови локальный плеер": (
            CommandType.MEDIA_CONTROL,
            "stop:local",
        ),
        "следующий трек в яндекс музыке": (
            CommandType.MEDIA_CONTROL,
            "next:yandex",
        ),
        "прибавь громкость": (CommandType.KEYBOARD_SHORTCUT, "volume_up"),
        "убавь громкость": (CommandType.KEYBOARD_SHORTCUT, "volume_down"),
        "открой локальный плеер": (CommandType.OPEN_APP, "локальный плеер"),
        "включи локальную музыку": (CommandType.MEDIA_CONTROL, "open_play_local"),
        "включи локальный плеер": (CommandType.MEDIA_CONTROL, "open_play_local"),
        "продолжи локальный плеер": (CommandType.MEDIA_CONTROL, "play:local"),
        "следующий трек вока": (CommandType.MEDIA_CONTROL, "next:local"),
        "предыдущий трек в вокальном пуэре": (
            CommandType.MEDIA_CONTROL,
            "previous:local",
        ),
    }
    for text, expected in cases.items():
        parsed = parse_command_text(text)
        assert (parsed.type, parsed.target) == expected, (text, parsed)


def test_controller_previous_is_explicit_double_event() -> None:
    keyboard = FakeKeyboard()
    apps = FakeApps()
    controller = MediaController(keyboard, apps, logging.getLogger("v13-test"))

    previous = controller.execute("previous")
    assert previous.ok, previous
    assert keyboard.media_calls == [("media_previous", "", 2)], keyboard.media_calls

    keyboard.media_calls.clear()
    restart = controller.execute("restart_current")
    assert restart.ok, restart
    assert keyboard.media_calls == [("media_previous", "", 1)], keyboard.media_calls

    keyboard.media_calls.clear()
    local_previous = controller.execute("previous:local")
    assert local_previous.ok, local_previous
    assert keyboard.media_calls == [("media_previous", "local", 2)], keyboard.media_calls


def test_controller_shutdown_is_bounded() -> None:
    keyboard = FakeKeyboard()
    apps = FakeApps()
    controller = MediaController(keyboard, apps, logging.getLogger("v13-test"))
    result = controller.execute("shutdown_yandex_music")
    assert result.ok, result
    assert keyboard.media_calls == [("media_stop", "yandex", 1)], keyboard.media_calls
    assert apps.closed == ["яндекс музыка"], apps.closed


def test_no_wake_does_not_execute() -> None:
    ctx, responses, ai, *_ = make_context()
    keyboard = FakeKeyboard()
    apps = FakeApps()
    media = MediaController(keyboard, apps, logging.getLogger("v13-test"))
    ctx = dataclasses.replace(ctx, media=media)

    astra_main.process_turn("выключи музыку", ctx)
    assert keyboard.media_calls == [], keyboard.media_calls
    assert apps.closed == [], apps.closed
    assert ai.route_calls == 0 and ai.ask_calls == 0

    astra_main.process_turn("Астра, выключи музыку", ctx)
    assert keyboard.media_calls == [("media_stop", "yandex", 1)], keyboard.media_calls
    assert apps.closed == ["яндекс музыка"], apps.closed
    assert responses[-1] == "Музыка остановлена. Яндекс Музыка закрыта.", responses


def test_main_routes_previous_and_targeted_local() -> None:
    ctx, responses, ai, *_ = make_context()
    keyboard = FakeKeyboard()
    media = MediaController(keyboard, FakeApps(), logging.getLogger("v13-test"))
    ctx = dataclasses.replace(ctx, media=media)

    astra_main.process_turn("Астра, верни предыдущий трек", ctx)
    assert keyboard.media_calls[-1] == ("media_previous", "", 2)
    assert responses[-1] == "Переключаю на предыдущий трек."

    astra_main.process_turn("Астра, следующий трек в локальном плеере", ctx)
    assert keyboard.media_calls[-1] == ("media_next", "local", 1)
    assert ai.route_calls == 0 and ai.ask_calls == 0


def test_open_play_local_is_bounded(monkeypatch=None) -> None:
    keyboard = FakeKeyboard()
    keyboard.fail_media_calls = 2
    apps = FakeApps()
    controller = MediaController(keyboard, apps, logging.getLogger("v13-test"))

    original_sleep = astra_main.time.sleep
    import src.media_controller as media_module
    media_original_sleep = media_module.time.sleep
    media_module.time.sleep = lambda _seconds: None
    try:
        result = controller.execute("open_play_local")
    finally:
        media_module.time.sleep = media_original_sleep

    assert result.ok, result
    assert apps.opened == ["медиаплеер"], apps.opened
    assert keyboard.media_calls == [
        ("media_play", "local", 1),
        ("media_play", "local", 1),
        ("media_play", "local", 1),
    ], keyboard.media_calls


def test_stt_repairs_and_pending_local_source() -> None:
    settings = astra_main.Settings(
        wake_phrases=["астра"],
        allow_commands_without_wake=False,
    )
    fake_app = AppConfig(
        name="медиаплеер",
        aliases=["локальный плеер"],
        open_command=["explorer.exe", "mswindowsmusic:"],
        process_name="Music.UI.exe",
    )
    manager = WindowsAppManager({"медиаплеер": fake_app})
    selected = astra_main.choose_stt_alternative(
        [
            "Астра следующий трек вока",
            "Астра следующий трек в лака",
        ],
        settings,
        manager,
        logging.getLogger("v13-test"),
    )
    assert selected == "астра следующий трек в локальном плеере", selected

    selected = astra_main.choose_stt_alternative(
        ["вока", "Локо", "лака"],
        settings,
        manager,
        logging.getLogger("v13-test"),
    )
    assert selected == "локальную", selected

    ctx, responses, ai, *_ = make_context()
    keyboard = FakeKeyboard()
    apps = FakeApps()
    media = MediaController(keyboard, apps, logging.getLogger("v13-test"))
    ctx = dataclasses.replace(ctx, media=media)
    astra_main.set_pending(ctx.state, "ambiguous_music")
    original_sleep = __import__("src.media_controller", fromlist=["time"]).time.sleep
    media_module = __import__("src.media_controller", fromlist=["time"])
    media_module.time.sleep = lambda _seconds: None
    try:
        astra_main.process_turn("вока", ctx)
    finally:
        media_module.time.sleep = original_sleep
    assert apps.opened == ["медиаплеер"], apps.opened
    assert keyboard.media_calls[-1] == ("media_play", "local", 1)
    assert ai.route_calls == 0 and ai.ask_calls == 0


def test_local_player_resolver_uses_only_fixed_or_env_path() -> None:
    app = AppConfig(
        name="медиаплеер",
        aliases=["локальный плеер", "медиаплеер"],
        open_command=["explorer.exe", "mswindowsmusic:"],
        process_name="Microsoft.Media.Player.exe",
    )
    manager = WindowsAppManager({"медиаплеер": app})

    with tempfile.TemporaryDirectory() as tmp:
        executable = Path(tmp) / "MySafePlayer.exe"
        executable.write_bytes(b"MZ")
        previous = os.environ.get("ASTRA_LOCAL_MEDIA_PLAYER_PATH")
        os.environ["ASTRA_LOCAL_MEDIA_PLAYER_PATH"] = str(executable)
        try:
            command = manager._resolve_open_command(app)
            assert command == [str(executable)], command
            configured_processes = KeyboardController._configured_local_media_process_names()
            assert "mysafeplayer" in configured_processes, configured_processes
        finally:
            if previous is None:
                os.environ.pop("ASTRA_LOCAL_MEDIA_PLAYER_PATH", None)
            else:
                os.environ["ASTRA_LOCAL_MEDIA_PLAYER_PATH"] = previous

    assert manager.find_app("локальный плеер") is app
    assert manager.find_app("медиаплеер") is app


def test_groove_protocol_is_preferred_over_legacy_wmp() -> None:
    app = AppConfig(
        name="медиаплеер",
        aliases=["локальный плеер", "музыка groove"],
        open_command=["explorer.exe", "mswindowsmusic:"],
        process_name="Music.UI.exe",
    )
    manager = WindowsAppManager({"медиаплеер": app})
    original_protocol = manager._windows_protocol_registered
    original_which = __import__("src.windows_app_manager", fromlist=["shutil"]).shutil.which
    module = __import__("src.windows_app_manager", fromlist=["shutil"])
    manager._windows_protocol_registered = lambda protocol: protocol == "mswindowsmusic"  # type: ignore[method-assign]
    module.shutil.which = lambda name: r"C:\Windows\explorer.exe" if name == "explorer.exe" else None
    previous = os.environ.pop("ASTRA_LOCAL_MEDIA_PLAYER_PATH", None)
    try:
        command = manager._resolve_open_command(app)
    finally:
        manager._windows_protocol_registered = original_protocol  # type: ignore[method-assign]
        module.shutil.which = original_which
        if previous is not None:
            os.environ["ASTRA_LOCAL_MEDIA_PLAYER_PATH"] = previous
    assert command == [r"C:\Windows\explorer.exe", "mswindowsmusic:"], command


def test_wake_extraction() -> None:
    parsed = extract_command_after_wake("Астра, выключи музыку", ["астра"])
    assert parsed.type == CommandType.MEDIA_CONTROL
    assert parsed.target == "shutdown_yandex_music"


def main() -> None:
    test_parser()
    test_controller_previous_is_explicit_double_event()
    test_controller_shutdown_is_bounded()
    test_no_wake_does_not_execute()
    test_main_routes_previous_and_targeted_local()
    test_open_play_local_is_bounded()
    test_stt_repairs_and_pending_local_source()
    test_local_player_resolver_uses_only_fixed_or_env_path()
    test_groove_protocol_is_preferred_over_legacy_wmp()
    test_wake_extraction()
    print("v1.3 media/local-player smoke tests passed")


if __name__ == "__main__":
    main()
