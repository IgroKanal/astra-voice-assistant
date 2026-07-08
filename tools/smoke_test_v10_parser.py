from __future__ import annotations

from pathlib import Path
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.command_parser import CommandType, extract_command_after_wake, parse_command_text


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

    # v0.10.4 voice UX and practical local commands.
    assert_cmd("повтори", CommandType.VOICE_FEEDBACK, "repeat_last")
    assert_cmd("повтори еще раз", CommandType.VOICE_FEEDBACK, "repeat_last")
    assert_cmd("что ты услышала", CommandType.VOICE_FEEDBACK, "last_heard")
    assert_cmd("что я сказал", CommandType.VOICE_FEEDBACK, "last_heard")

    assert_cmd("покажи рабочий стол", CommandType.WINDOW_CONTROL, "show_desktop")
    assert_cmd("сверни все окна", CommandType.WINDOW_CONTROL, "show_desktop")
    assert_cmd("сверни окно", CommandType.WINDOW_CONTROL, "minimize")
    assert_cmd("разверни окно", CommandType.WINDOW_CONTROL, "maximize")

    assert_cmd("открой загрузки браузера", CommandType.KEYBOARD_SHORTCUT, "browser_downloads")
    assert_cmd("история загрузок", CommandType.KEYBOARD_SHORTCUT, "browser_downloads")
    assert_cmd("открой историю браузера", CommandType.KEYBOARD_SHORTCUT, "browser_history")

    assert_cmd("статус интернета", CommandType.SYSTEM_INFO, "internet")

    # v0.10.5 voice UX / parser safety regressions.
    assert_cmd("открой ча", CommandType.OPEN_APP, "__ambiguous_chat__")
    assert_cmd("открой чат", CommandType.OPEN_APP, "__ambiguous_chat__")
    assert_cmd("открой чат gp", CommandType.OPEN_URL, "чат gp")
    assert_cmd("переключись no firefox", CommandType.WINDOW_CONTROL, "focus:firefox")
    assert_cmd("открой и закрой vs code", CommandType.OPEN_APP, "__mixed_command__")
    assert_cmd("новое окно браузера", CommandType.KEYBOARD_SHORTCUT, "browser_new_window")
    assert_cmd("открой приватное окно", CommandType.KEYBOARD_SHORTCUT, "incognito")
    assert_cmd("открой буфер обмена", CommandType.KEYBOARD_SHORTCUT, "clipboard_history")
    assert_cmd("status vpn", CommandType.VPN_CONTROL, "status")
    assert_cmd("status internet", CommandType.SYSTEM_INFO, "internet")


    # v0.10.6 STT clipping / follow-up safety regressions.
    assert_cmd("открой буфер up", CommandType.KEYBOARD_SHORTCUT, "clipboard_history")
    assert_cmd("открой буфер ап", CommandType.KEYBOARD_SHORTCUT, "clipboard_history")
    assert_cmd("закрой последнее ок", CommandType.CLOSE_APP, "__unsupported_close__")
    assert_cmd("статус интер", CommandType.SYSTEM_INFO, "internet")
    assert_cmd("статус inter", CommandType.SYSTEM_INFO, "internet")
    assert_cmd("status inter", CommandType.SYSTEM_INFO, "internet")

    main_py = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "resolve_pending_follow_up" in main_py
    assert "pending_kind" in main_py

    assert (PROJECT_ROOT / "start_astra_hidden.vbs").exists()
    assert (PROJECT_ROOT / "start_astra_debug.bat").exists()
    assert (PROJECT_ROOT / "tools" / "install_autostart.ps1").exists()

    # v0.10.8 beta safety gate regressions.
    assert_cmd("открой youtube.com", CommandType.OPEN_URL, "youtube.com")
    assert_cmd("открой сайт youtube.com", CommandType.OPEN_URL, "youtube.com")
    assert_cmd("открой https://example.com", CommandType.OPEN_URL, "https://example.com")

    # v0.10.8.1: real beta flow uses wake extraction first. It must preserve
    # dots and URL separators, not normalize them into spaces.
    wake_phrases = ["астра", "эй астра", "привет астра"]
    parsed = extract_command_after_wake("Астра, открой youtube.com", wake_phrases)
    assert parsed.type == CommandType.OPEN_URL and parsed.target == "youtube.com", parsed
    parsed = extract_command_after_wake("Астра, открой сайт youtube.com", wake_phrases)
    assert parsed.type == CommandType.OPEN_URL and parsed.target == "youtube.com", parsed
    parsed = extract_command_after_wake("Астра, открой https://example.com", wake_phrases)
    assert parsed.type == CommandType.OPEN_URL and parsed.target == "https://example.com", parsed

    apps_json = json.loads((PROJECT_ROOT / "config" / "apps.json").read_text(encoding="utf-8"))
    apps_text = json.dumps(apps_json, ensure_ascii=False).lower()
    assert "cmd.exe" not in apps_text, "cmd.exe must not be whitelisted in beta config"
    assert "командная строка" not in apps_json.get("apps", {}), "cmd app must be removed"

    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ALLOW_COMMANDS_WITHOUT_WAKE=false" in env_example

    keyboard_controller = (PROJECT_ROOT / "src" / "keyboard_controller.py").read_text(encoding="utf-8")
    assert "_TERMINAL_PROCESS_NAMES" in keyboard_controller
    assert "Enter в терминале отключён" in keyboard_controller
    assert "Ввод текста в терминал отключён" in keyboard_controller
    assert '"code"' in keyboard_controller, "VS Code foreground must be guarded for beta safety"

    main_py = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "wake_required_guard" in main_py
    assert "blocked before LLM-router" in main_py

    config_loader = (PROJECT_ROOT / "src" / "config_loader.py").read_text(encoding="utf-8")
    assert "tts_cache_generation_timeout_seconds" in config_loader
    assert "TTS_CACHE_GENERATION_TIMEOUT_SECONDS" in config_loader


    # v0.11.0 wake-only runtime regressions.
    assert "voice_runtime_mode" in config_loader
    assert "wake_only_mode" in config_loader
    assert "wake_listen_timeout_seconds" in config_loader
    assert "command_listen_timeout_seconds" in config_loader

    assert "def _wake_only_voice_enabled" in main_py
    assert "Wake-only voice runtime enabled" in main_py
    assert "Wake-only режим" in main_py
    assert "VOICE_RUNTIME_MODE=wake_only" in env_example
    assert "WAKE_ONLY_MODE=true" in env_example
    assert (PROJECT_ROOT / "tools" / "apply_v110_wake_env.ps1").exists()

    parsed = extract_command_after_wake("Астра", wake_phrases)
    assert parsed.type == CommandType.WAKE_ONLY, parsed
    parsed = extract_command_after_wake("Астра, статус vpn", wake_phrases)
    assert parsed.type == CommandType.VPN_CONTROL and parsed.target == "status", parsed
    parsed = extract_command_after_wake("Астра, переключись на firefox", wake_phrases)
    assert parsed.type == CommandType.WINDOW_CONTROL and parsed.target == "focus:firefox", parsed
    parsed = extract_command_after_wake("открой youtube.com", wake_phrases)
    assert parsed.type == CommandType.NO_WAKE, parsed

    print("v0.10 VPN/window parser smoke tests passed")


if __name__ == "__main__":
    main()
