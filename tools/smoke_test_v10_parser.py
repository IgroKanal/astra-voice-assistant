from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.command_parser import CommandType, parse_command_text


def assert_cmd(text: str, expected_type: CommandType, expected_target: str = "") -> None:
    parsed = parse_command_text(text)
    assert parsed.type == expected_type, (text, parsed)
    if expected_target:
        assert parsed.target == expected_target, (text, parsed)


def assert_vpn_is_direct_without_wake() -> None:
    main_py = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    direct_start = main_py.index("_DIRECT_COMMAND_TYPES")
    direct_end = main_py.index("_WAKE_REQUIRED_TYPES")
    direct_block = main_py[direct_start:direct_end]
    assert "CommandType.VPN_CONTROL" in direct_block, direct_block

    blocked_start = main_py.index("_ROUTER_BLOCKED_ACTION_TYPES")
    blocked_end = main_py.index("_REQUIRES_WAKE_TARGET")
    blocked_block = main_py[blocked_start:blocked_end]
    assert "ActionType.VPN_CONTROL" in blocked_block, blocked_block


def assert_window_is_direct_without_wake() -> None:
    main_py = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    direct_start = main_py.index("_DIRECT_COMMAND_TYPES")
    direct_end = main_py.index("_WAKE_REQUIRED_TYPES")
    direct_block = main_py[direct_start:direct_end]
    assert "CommandType.WINDOW_CONTROL" in direct_block, direct_block

    blocked_start = main_py.index("_ROUTER_BLOCKED_ACTION_TYPES")
    blocked_end = main_py.index("_REQUIRES_WAKE_TARGET")
    blocked_block = main_py[blocked_start:blocked_end]
    assert "ActionType.WINDOW_CONTROL" in blocked_block, blocked_block


def main() -> None:
    assert_cmd("включи vpn", CommandType.VPN_CONTROL, "connect")
    assert_cmd("включи впн", CommandType.VPN_CONTROL, "connect")
    assert_cmd("подключи ви пи эн", CommandType.VPN_CONTROL, "connect")
    assert_cmd("запусти амнезия впн", CommandType.VPN_CONTROL, "connect")

    assert_cmd("выключи vpn", CommandType.VPN_CONTROL, "disconnect")
    assert_cmd("отключи впн", CommandType.VPN_CONTROL, "disconnect")
    assert_cmd("останови amneziawg", CommandType.VPN_CONTROL, "disconnect")

    assert_cmd("статус vpn", CommandType.VPN_CONTROL, "status")
    assert_cmd("проверь впн", CommandType.VPN_CONTROL, "status")
    assert_cmd("vpn", CommandType.VPN_CONTROL, "status")

    # Regression v0.10.1: VPN commands must stay local without wake phrase.
    assert_vpn_is_direct_without_wake()

    # Regression: non-VPN phrases should remain old behavior.
    assert_cmd("включи звук", CommandType.ASK_LLM)
    assert_cmd("включи браузер", CommandType.OPEN_APP, "браузер")
    assert_cmd("стоп стоп стоп", CommandType.EXIT)

    # v0.10.2 window awareness commands.
    assert_cmd("какие окна открыты", CommandType.WINDOW_CONTROL, "list")
    assert_cmd("что открыто", CommandType.WINDOW_CONTROL, "list")
    assert_cmd("активное окно", CommandType.WINDOW_CONTROL, "active")
    assert_cmd("какое окно активно", CommandType.WINDOW_CONTROL, "active")
    assert_cmd("переключись на firefox", CommandType.WINDOW_CONTROL, "focus:firefox")
    assert_cmd("переключись на vs code", CommandType.WINDOW_CONTROL, "focus:vs code")
    assert_cmd("перейди в телеграм", CommandType.WINDOW_CONTROL, "focus:телеграм")
    assert_window_is_direct_without_wake()

    print("v0.10 VPN/window parser smoke tests passed")


if __name__ == "__main__":
    main()
