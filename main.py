from __future__ import annotations

import argparse
import logging
import platform
import sys

from src.ai_client import AIClient
from src.audio_io import VoiceIO
from src.command_parser import CommandType, ParsedCommand, extract_command_after_wake, parse_command_text
from src.config_loader import ConfigError, load_apps_config, load_settings
from src.logger_setup import setup_logging
from src.windows_app_manager import WindowsAppManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Голосовой ассистент Астра для Windows")
    parser.add_argument(
        "--text",
        action="store_true",
        help="Текстовый режим для теста без микрофона.",
    )
    return parser


def ensure_windows(logger: logging.Logger) -> None:
    current_os = platform.system().lower()
    if current_os != "windows":
        logger.warning("Проект рассчитан только на Windows. Текущая ОС: %s", platform.system())
        print("Предупреждение: этот MVP рассчитан только на Windows 10/11.")


def handle_command(
    command: ParsedCommand,
    app_manager: WindowsAppManager,
    ai_client: AIClient,
    voice: VoiceIO | None,
) -> bool:
    """
    Выполняет команду.

    Возвращает False, если нужно завершить приложение.
    """

    def say(message: str) -> None:
        if voice is not None:
            voice.speak(message)
        else:
            print(f"Астра: {message}")

    if command.type == CommandType.EXIT:
        say("Завершаю работу.")
        return False

    if command.type == CommandType.OPEN_APP:
        if not command.target:
            say("Что открыть?")
            return True
        result = app_manager.open_app(command.target)
        say(result.message)
        return True

    if command.type == CommandType.CLOSE_APP:
        if not command.target:
            say("Что закрыть?")
            return True
        result = app_manager.close_app(command.target)
        say(result.message)
        return True

    if command.type == CommandType.ASK_LLM:
        result = ai_client.ask(command.text)
        say(result.message)
        return True

    if command.type == CommandType.EMPTY:
        say("Команда пустая.")
        return True

    return True


def run_text_mode(settings, app_manager: WindowsAppManager, ai_client: AIClient) -> None:
    print("Текстовый режим. Пиши команды так же, как сказал бы голосом.")
    print(f"Пример: {settings.assistant_name}, открой блокнот")
    print("Для выхода: Астра, стоп")

    while True:
        try:
            user_text = input("Ты: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nАстра: Завершаю работу.")
            return

        parsed = extract_command_after_wake(user_text, settings.wake_phrases)
        if parsed.type == CommandType.NO_WAKE:
            print(f"Астра: Сначала назови меня: {settings.assistant_name}.")
            continue

        if parsed.type == CommandType.WAKE_ONLY:
            follow_up = input("Астра: Слушаю.\nТы: ").strip()
            parsed = parse_command_text(follow_up)

        should_continue = handle_command(parsed, app_manager, ai_client, voice=None)
        if not should_continue:
            return


def run_voice_mode(settings, app_manager: WindowsAppManager, ai_client: AIClient, logger: logging.Logger) -> None:
    voice = VoiceIO(settings=settings, logger=logger)
    voice.speak(f"{settings.assistant_name} запущена. Жду имя.")

    while True:
        listen_result = voice.listen_once()
        if not listen_result.ok:
            # Частые ошибки типа тишины не озвучиваем постоянно, чтобы ассистент не болтал без конца.
            logger.info("STT: %s", listen_result.error)
            continue

        parsed = extract_command_after_wake(listen_result.text, settings.wake_phrases)
        if parsed.type == CommandType.NO_WAKE:
            continue

        if parsed.type == CommandType.WAKE_ONLY:
            voice.speak("Слушаю.")
            follow_up = voice.listen_once()
            if not follow_up.ok:
                voice.speak(follow_up.error)
                continue
            parsed = parse_command_text(follow_up.text)

        should_continue = handle_command(parsed, app_manager, ai_client, voice=voice)
        if not should_continue:
            return


def main() -> int:
    args = build_parser().parse_args()
    logger = setup_logging()
    logger.info("Запуск ассистента")

    ensure_windows(logger)

    try:
        settings = load_settings()
        apps = load_apps_config()
    except ConfigError as exc:
        logger.error("Ошибка конфигурации: %s", exc)
        print(f"Ошибка конфигурации: {exc}")
        return 1

    app_manager = WindowsAppManager(apps=apps, logger=logger)
    ai_client = AIClient(settings=settings, logger=logger)

    try:
        if args.text:
            run_text_mode(settings, app_manager, ai_client)
        else:
            run_voice_mode(settings, app_manager, ai_client, logger)
    except KeyboardInterrupt:
        print("\nАстра: Завершаю работу.")
        logger.info("Остановка по Ctrl+C")
        return 0
    except Exception:
        logger.exception("Критическая непредвиденная ошибка")
        print("Произошла критическая ошибка. Подробности смотри в logs/app.log")
        return 1

    logger.info("Ассистент завершил работу")
    return 0


if __name__ == "__main__":
    sys.exit(main())
