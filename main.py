from __future__ import annotations

import argparse
import logging
import os
import platform
import sys

from src.ai_client import AIClient
from src.audio_io import VoiceIO
from src.command_parser import CommandType, ParsedCommand, extract_command_after_wake, parse_command_text
from src.config_loader import ConfigError, load_apps_config, load_settings
from src.logger_setup import setup_logging
from src.windows_app_manager import WindowsAppManager


_DIRECT_COMMAND_TYPES = {
    CommandType.OPEN_APP,
    CommandType.CLOSE_APP,
    CommandType.EXIT,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Голосовой ассистент Астра для Windows")
    parser.add_argument(
        "--text",
        action="store_true",
        help="Текстовый режим для теста без микрофона.",
    )
    return parser


def env_bool(name: str, default: bool = False) -> bool:
    """
    Читает boolean-настройку из .env.

    true/1/yes/on/да/вкл -> True
    false/0/no/off/нет/выкл -> False
    """
    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "y", "on", "да", "вкл"}


def ensure_windows(logger: logging.Logger) -> None:
    current_os = platform.system().lower()
    if current_os != "windows":
        logger.warning("Проект рассчитан только на Windows. Текущая ОС: %s", platform.system())
        print("Предупреждение: этот MVP рассчитан только на Windows 10/11.")


def parse_without_wake_if_allowed(
    raw_text: str,
    allow_without_wake: bool,
    logger: logging.Logger | None = None,
) -> ParsedCommand:
    """
    Разрешает команды без имени ассистента только для явных системных команд:
    - открой ...
    - закрой ...
    - стоп / выход

    Обычные вопросы без wake phrase не отправляются в LLM, чтобы ассистент
    случайно не отвечал на любой посторонний разговор.
    """
    if not allow_without_wake:
        return ParsedCommand(CommandType.NO_WAKE, text=raw_text)

    direct_command = parse_command_text(raw_text)

    if direct_command.type in _DIRECT_COMMAND_TYPES:
        if logger is not None:
            logger.info("Команда без wake phrase разрешена: %s", direct_command)
        return direct_command

    return ParsedCommand(CommandType.NO_WAKE, text=raw_text)


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


def run_text_mode(settings, app_manager: WindowsAppManager, ai_client: AIClient, logger: logging.Logger) -> None:
    allow_without_wake = env_bool("ALLOW_COMMANDS_WITHOUT_WAKE", default=False)

    print("Текстовый режим. Пиши команды так же, как сказал бы голосом.")
    print(f"Пример с именем: {settings.assistant_name}, открой блокнот")

    if allow_without_wake:
        print("Режим разработки: команды открыть/закрыть/стоп можно писать без имени.")
        print("Пример без имени: открой блокнот")
    else:
        print(f"Сначала нужно назвать ассистента: {settings.assistant_name}")

    print("Для выхода: Астра, стоп")

    while True:
        try:
            user_text = input("Ты: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nАстра: Завершаю работу.")
            return

        parsed = extract_command_after_wake(user_text, settings.wake_phrases)

        if parsed.type == CommandType.NO_WAKE:
            parsed = parse_without_wake_if_allowed(
                raw_text=user_text,
                allow_without_wake=allow_without_wake,
                logger=logger,
            )

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
    allow_without_wake = env_bool("ALLOW_COMMANDS_WITHOUT_WAKE", default=False)

    voice = VoiceIO(settings=settings, logger=logger)
    voice.speak(f"{settings.assistant_name} запущена. Жду имя.")

    if allow_without_wake:
        logger.info("Режим разработки включён: явные команды можно выполнять без wake phrase.")
        print("Режим разработки: можно говорить 'открой блокнот' без имени ассистента.")

    while True:
        listen_result = voice.listen_once()
        if not listen_result.ok:
            # Частые ошибки типа тишины не озвучиваем постоянно, чтобы ассистент не болтал без конца.
            logger.info("STT: %s", listen_result.error)
            continue

        parsed = extract_command_after_wake(listen_result.text, settings.wake_phrases)

        if parsed.type == CommandType.NO_WAKE:
            parsed = parse_without_wake_if_allowed(
                raw_text=listen_result.text,
                allow_without_wake=allow_without_wake,
                logger=logger,
            )

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
            run_text_mode(settings, app_manager, ai_client, logger)
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