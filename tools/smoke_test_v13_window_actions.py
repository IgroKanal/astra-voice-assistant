from __future__ import annotations

import dataclasses
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main as astra_main
from src.command_parser import CommandType, parse_command_text
from src.window_controller import SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE, WindowController, WindowInfo
from tools.smoke_test_v11_daily_workflow import make_context


class RecordingWindows:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def minimize_active_window(self):
        self.calls.append(("minimize", ""))
        return SimpleNamespace(ok=True, message="Сворачиваю окно.")

    def maximize_active_window(self):
        self.calls.append(("maximize", ""))
        return SimpleNamespace(ok=True, message="Разворачиваю окно.")

    def restore_active_window(self):
        self.calls.append(("restore", ""))
        return SimpleNamespace(ok=True, message="Возвращаю обычный размер окна.")

    def minimize_target(self, target: str):
        self.calls.append(("minimize", target))
        return SimpleNamespace(ok=True, message=f"Сворачиваю {target}.")

    def maximize_target(self, target: str):
        self.calls.append(("maximize", target))
        return SimpleNamespace(ok=True, message=f"Разворачиваю {target}.")

    def restore_target(self, target: str):
        self.calls.append(("restore", target))
        return SimpleNamespace(ok=True, message=f"Восстанавливаю {target}.")

    def __getattr__(self, _name: str):
        return lambda *args, **kwargs: SimpleNamespace(ok=True, message="Готово.")


class FakeUser32:
    def __init__(self) -> None:
        self.valid = True
        self.iconic = False
        self.zoomed = False
        self.commands: list[int] = []

    def GetForegroundWindow(self):
        return 222

    def IsWindow(self, _hwnd):
        return int(self.valid)

    def ShowWindow(self, _hwnd, command):
        self.commands.append(command)
        if command == SW_MINIMIZE:
            self.iconic = True
            self.zoomed = False
        elif command == SW_MAXIMIZE:
            self.iconic = False
            self.zoomed = True
        elif command == SW_RESTORE:
            self.iconic = False
            self.zoomed = False
        return 1

    def IsIconic(self, _hwnd):
        return int(self.iconic)

    def IsZoomed(self, _hwnd):
        return int(self.zoomed)

    def BringWindowToTop(self, _hwnd):
        return 1

    def SetForegroundWindow(self, _hwnd):
        return 1


def test_parser() -> None:
    cases = {
        "сверни окно": (CommandType.WINDOW_CONTROL, "minimize"),
        "разверни окно на весь экран": (CommandType.WINDOW_CONTROL, "maximize"),
        "верни обычный размер окна": (CommandType.WINDOW_CONTROL, "restore"),
        "верни на обычный размер": (CommandType.WINDOW_CONTROL, "restore"),
        "сверни телеграм": (CommandType.WINDOW_CONTROL, "minimize:телеграм"),
        "разверни яндекс музыку": (
            CommandType.WINDOW_CONTROL,
            "maximize:яндекс музыку",
        ),
        "восстанови локальный плеер": (
            CommandType.WINDOW_CONTROL,
            "restore:локальный плеер",
        ),
        "верни обычный размер firefox": (
            CommandType.WINDOW_CONTROL,
            "restore:firefox",
        ),
        "сверни все окна": (CommandType.WINDOW_CONTROL, "show_desktop"),
    }
    for text, expected in cases.items():
        parsed = parse_command_text(text)
        assert (parsed.type, parsed.target) == expected, (text, parsed)


def test_main_dispatch_and_wake_gate() -> None:
    ctx, responses, ai, *_ = make_context()
    windows = RecordingWindows()
    ctx = dataclasses.replace(ctx, windows=windows)

    astra_main.process_turn("сверни телеграм", ctx)
    assert windows.calls == [], windows.calls
    assert ai.route_calls == 0 and ai.ask_calls == 0

    commands = [
        ("Астра, сверни окно", ("minimize", "")),
        ("Астра, разверни окно на весь экран", ("maximize", "")),
        ("Астра, верни обычный размер окна", ("restore", "")),
        ("Астра, сверни телеграм", ("minimize", "телеграм")),
        ("Астра, разверни Яндекс Музыку", ("maximize", "яндекс музыку")),
        ("Астра, восстанови локальный плеер", ("restore", "локальный плеер")),
    ]
    for phrase, expected_call in commands:
        astra_main.process_turn(phrase, ctx)
        assert windows.calls[-1] == expected_call, (phrase, windows.calls)

    assert responses, responses
    assert ai.route_calls == 0 and ai.ask_calls == 0


def test_window_controller_uses_showwindow_states() -> None:
    controller = object.__new__(WindowController)
    controller.logger = logging.getLogger("v13-window-test")
    controller.user32 = FakeUser32()
    info = WindowInfo(
        hwnd=123,
        title="Telegram",
        pid=10,
        process_name="telegram",
    )
    controller.find_window = lambda target: info if target == "телеграм" else None  # type: ignore[method-assign]

    minimized = controller.minimize_target("телеграм")
    assert minimized.ok, minimized
    assert controller.user32.commands[-1] == SW_MINIMIZE

    maximized = controller.maximize_target("телеграм")
    assert maximized.ok, maximized
    assert controller.user32.commands[-1] == SW_MAXIMIZE

    restored = controller.restore_target("телеграм")
    assert restored.ok, restored
    assert controller.user32.commands[-1] == SW_RESTORE

    missing = controller.maximize_target("неизвестное окно")
    assert not missing.ok, missing



def test_generic_window_state_reuses_recent_minimized_window() -> None:
    controller = object.__new__(WindowController)
    controller.logger = logging.getLogger("v13-window-test")
    controller.user32 = FakeUser32()
    controller._last_state_hwnd = 111
    controller._last_state_at = __import__("time").monotonic()
    controller._state_context_ttl_seconds = 45.0
    controller.user32.iconic = True

    selected = controller._generic_state_target("maximize")
    assert selected == 111, selected

    controller.user32.iconic = False
    controller.user32.zoomed = True
    selected = controller._generic_state_target("restore")
    assert selected == 111, selected


def test_configured_local_player_is_window_alias() -> None:
    controller = object.__new__(WindowController)
    previous = os.environ.get("ASTRA_LOCAL_MEDIA_PLAYER_PATH")
    os.environ["ASTRA_LOCAL_MEDIA_PLAYER_PATH"] = r"C:\Players\MySafePlayer.exe"
    try:
        aliases = controller._target_aliases("локальный плеер")
        assert "mysafeplayer" in aliases, aliases
    finally:
        if previous is None:
            os.environ.pop("ASTRA_LOCAL_MEDIA_PLAYER_PATH", None)
        else:
            os.environ["ASTRA_LOCAL_MEDIA_PLAYER_PATH"] = previous


def main() -> None:
    test_parser()
    test_main_dispatch_and_wake_gate()
    test_window_controller_uses_showwindow_states()
    test_generic_window_state_reuses_recent_minimized_window()
    test_configured_local_player_is_window_alias()
    print("v1.3 safe window-action smoke tests passed")


if __name__ == "__main__":
    main()
