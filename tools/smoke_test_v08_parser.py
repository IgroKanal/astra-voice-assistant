from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.command_parser import CommandType, is_command_like_text, parse_command_text
from src.config_loader import AppConfig
from src.task_router import normalize_url_or_site
from src.windows_app_manager import WindowsAppManager


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    cases = {
        "открой кло": CommandType.OPEN_URL,
        "открой клод": CommandType.OPEN_URL,
        "открой чатт gpt": CommandType.OPEN_URL,
        "открой чат кпт": CommandType.OPEN_URL,
        "открой телеграм веб": CommandType.OPEN_URL,
        "запусти телеграм": CommandType.OPEN_APP,
        "закрой ютуб": CommandType.KEYBOARD_SHORTCUT,
        "закрой вкладку": CommandType.KEYBOARD_SHORTCUT,
        "новая вкладка": CommandType.KEYBOARD_SHORTCUT,
        "верни закрытую вкладку": CommandType.KEYBOARD_SHORTCUT,
        "следующая вкладка": CommandType.KEYBOARD_SHORTCUT,
        "адресная строка": CommandType.KEYBOARD_SHORTCUT,
        "обнови страницу": CommandType.KEYBOARD_SHORTCUT,
        "обнови страницу ютуб": CommandType.KEYBOARD_SHORTCUT,
        "обнови страница ютуб": CommandType.KEYBOARD_SHORTCUT,
        "перезагрузи страница ютуб": CommandType.KEYBOARD_SHORTCUT,
        "в блокнот напиши привет": CommandType.TYPE_TEXT,
        "напиши в блокнот привет": CommandType.TYPE_TEXT,
        "громче": CommandType.KEYBOARD_SHORTCUT,
        "переключи звук": CommandType.KEYBOARD_SHORTCUT,
        "напиши привет": CommandType.TYPE_TEXT,
        "открой загрузки": CommandType.OPEN_FOLDER,
        "открой папку проекта": CommandType.OPEN_FOLDER,
        "сделай скриншот": CommandType.SCREENSHOT,
        "сколько памяти": CommandType.SYSTEM_INFO,
        "заряд батареи": CommandType.SYSTEM_INFO,
        "помощь": CommandType.HELP,
        "что ты умеешь": CommandType.HELP,
        "открой сайт кло": CommandType.OPEN_URL,
        "открой grow": CommandType.OPEN_URL,
    }

    for text, expected in cases.items():
        parsed = parse_command_text(text)
        check(parsed.type == expected, f"{text!r}: expected {expected}, got {parsed}")

    check(normalize_url_or_site("кло") == "https://claude.ai", "кло -> Claude failed")
    check(normalize_url_or_site("чатт gpt") == "https://chatgpt.com", "чатт gpt -> ChatGPT failed")
    check(normalize_url_or_site("джемини") == "https://gemini.google.com", "джемини -> Gemini failed")
    check(normalize_url_or_site("сайт кло") == "https://claude.ai", "сайт кло -> Claude failed")
    check(normalize_url_or_site("grow") == "https://claude.ai", "grow -> Claude failed")

    targeted = parse_command_text("в блокнот напиши привет")
    check(targeted.target == "app=блокнот;text=привет", f"targeted type failed: {targeted}")

    refresh_with_target = parse_command_text("обнови страницу ютуб")
    check(refresh_with_target.target == "refresh", f"refresh target failed: {refresh_with_target}")

    refresh_stt_case = parse_command_text("обнови страница ютуб")
    check(refresh_stt_case.target == "refresh", f"refresh STT case failed: {refresh_stt_case}")
    check(is_command_like_text("обнови страница ютуб"), "refresh STT case must be command-like")

    check(not is_command_like_text("приоткрой окно"), "приоткрой must not trigger command-like gate")

    apps = {
        "блокнот": AppConfig(
            name="блокнот",
            aliases=["блокнот", "бло", "блок", "блакнот"],
            open_command=["notepad.exe"],
            process_name="notepad.exe",
        )
    }
    manager = WindowsAppManager(apps)
    check(manager.find_app("бло") is not None, "fuzzy app бло -> блокнот failed")
    check(manager.find_app("блакнот") is not None, "fuzzy app блакнот -> блокнот failed")

    safety_cases = {
        "закрой окно": CommandType.ASK_LLM,
        "очисти поле": CommandType.ASK_LLM,
        "вырежи": CommandType.ASK_LLM,
        "печать": CommandType.ASK_LLM,
        "включи звук": CommandType.ASK_LLM,
        "выключи звук": CommandType.ASK_LLM,
    }
    for text, expected in safety_cases.items():
        parsed = parse_command_text(text)
        check(parsed.type == expected, f"unsafe {text!r}: expected {expected}, got {parsed}")

    print("v0.8 smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
