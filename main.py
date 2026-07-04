from __future__ import annotations

import argparse
import logging
import platform
import sys
import webbrowser
from datetime import datetime

from src.ai_client import AIClient
from src.audio_io import VoiceIO
from src.command_parser import (
    CommandType,
    ParsedCommand,
    extract_command_after_wake,
    parse_command_text,
)
from src.config_loader import AppConfig, ConfigError, Settings, load_apps_config, load_settings
from src.logger_setup import setup_logging
from src.task_router import (
    ActionType,
    AssistantAction,
    google_search_url,
    normalize_url_or_site,
)
from src.windows_app_manager import WindowsAppManager


_DIRECT_COMMAND_TYPES = {
    CommandType.OPEN_APP,
    CommandType.CLOSE_APP,
    CommandType.OPEN_URL,
    CommandType.WEB_SEARCH,
    CommandType.GET_TIME,
    CommandType.GET_DATE,
    CommandType.EXIT,
}

_ROUTER_HINT_WORDS = (
    "открой",
    "открыть",
    "запусти",
    "запустить",
    "включи",
    "закрой",
    "закрыть",
    "выключи",
    "заверши",
    "найди",
    "найти",
    "поищи",
    "загугли",
    "открой сайт",
    "зайди",
    "перейди",
    "сколько время",
    "сколько времени",
    "который час",
    "какое число",
    "какая дата",
)


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
        logger.warning(
            "Проект рассчитан только на Windows. Текущая ОС: %s",
            platform.system(),
        )
        print("Предупреждение: этот MVP рассчитан только на Windows 10/11.")


def looks_like_command(text: str) -> bool:
    normalized = text.strip().lower().replace("ё", "е")
    return any(word in normalized for word in _ROUTER_HINT_WORDS)


def parsed_to_action(parsed: ParsedCommand, source: str = "local") -> AssistantAction:
    mapping = {
        CommandType.OPEN_APP: ActionType.OPEN_APP,
        CommandType.CLOSE_APP: ActionType.CLOSE_APP,
        CommandType.OPEN_URL: ActionType.OPEN_URL,
        CommandType.WEB_SEARCH: ActionType.WEB_SEARCH,
        CommandType.GET_TIME: ActionType.GET_TIME,
        CommandType.GET_DATE: ActionType.GET_DATE,
        CommandType.ASK_LLM: ActionType.ASK_LLM,
        CommandType.EXIT: ActionType.EXIT,
        CommandType.EMPTY: ActionType.EMPTY,
    }

    return AssistantAction(
        type=mapping.get(parsed.type, ActionType.UNKNOWN),
        text=parsed.text,
        target=parsed.target,
        query=parsed.target or parsed.text,
        url=parsed.target,
        confidence=1.0,
        source=source,
    )


def parse_without_wake_if_allowed(
    raw_text: str,
    allow_without_wake: bool,
    logger: logging.Logger | None = None,
) -> ParsedCommand:
    """
    Разрешает команды без имени ассистента только для явных системных команд.

    Обычные разговорные фразы не считаются командами на этом этапе.
    Они позже уйдут в обычный LLM-диалог, если включён
    ALLOW_CONVERSATION_WITHOUT_WAKE.
    """
    if not allow_without_wake:
        return ParsedCommand(CommandType.NO_WAKE, text=raw_text)

    direct_command = parse_command_text(raw_text)

    if direct_command.type in _DIRECT_COMMAND_TYPES:
        if logger is not None:
            logger.info("Команда без wake phrase разрешена: %s", direct_command)
        return direct_command

    return ParsedCommand(CommandType.NO_WAKE, text=raw_text)


def resolve_action(
    raw_text: str,
    parsed: ParsedCommand,
    had_wake: bool,
    apps: dict[str, AppConfig],
    ai_client: AIClient,
    settings: Settings,
    logger: logging.Logger,
) -> AssistantAction:
    """
    Решает, что делать с фразой.

    Правило v0.5.4:
    - явные команды выполняются как команды;
    - обычные вопросы/фразы идут в разговор с LLM;
    - Gemini-router используется только для командоподобных фраз.
    """
    if parsed.type not in {CommandType.ASK_LLM, CommandType.NO_WAKE}:
        return parsed_to_action(parsed, source="local_parser")

    if parsed.type == CommandType.ASK_LLM:
        return parsed_to_action(parsed, source="local_question")

    can_use_router = (
        settings.llm_router_enabled
        and settings.llm_enabled
        and ai_client.is_available
        and looks_like_command(raw_text)
    )

    if can_use_router:
        route = ai_client.route_command(raw_text, apps)
        if route.ok:
            action = route.action
            logger.info("LLM-router: %s", action)

            if (
                action.confidence >= settings.llm_router_min_confidence
                and action.type != ActionType.UNKNOWN
            ):
                return action

            logger.info(
                "LLM-router confidence too low or unknown: %s < %s",
                action.confidence,
                settings.llm_router_min_confidence,
            )

    if settings.allow_conversation_without_wake or had_wake:
        return AssistantAction(
            type=ActionType.ASK_LLM,
            text=raw_text,
            query=raw_text,
            confidence=1.0,
            source="conversation_fallback",
        )

    return AssistantAction(
        type=ActionType.UNKNOWN,
        text=raw_text,
        confidence=0.0,
        source="fallback",
    )


def handle_action(
    action: AssistantAction,
    app_manager: WindowsAppManager,
    ai_client: AIClient,
    voice: VoiceIO | None,
) -> bool:
    """
    Выполняет безопасное действие.

    Возвращает False, если нужно завершить приложение.
    """

    def say(message: str) -> None:
        if voice is not None:
            voice.speak(message)
        else:
            print(f"Астра: {message}")

    if action.type == ActionType.EXIT:
        say("Завершаю работу.")
        return False

    if action.type == ActionType.OPEN_APP:
        if not action.target:
            say("Что открыть?")
            return True
        result = app_manager.open_app(action.target)
        say(result.message)
        return True

    if action.type == ActionType.CLOSE_APP:
        if not action.target:
            say("Что закрыть?")
            return True
        result = app_manager.close_app(action.target)
        say(result.message)
        return True

    if action.type == ActionType.OPEN_URL:
        url = normalize_url_or_site(action.url or action.target or action.query)
        if not url:
            say("Какой сайт открыть?")
            return True
        webbrowser.open(url)
        say("Открываю сайт.")
        return True

    if action.type == ActionType.WEB_SEARCH:
        query = action.query or action.target or action.text
        if not query:
            say("Что найти?")
            return True
        webbrowser.open(google_search_url(query))
        say("Ищу.")
        return True

    if action.type == ActionType.GET_TIME:
        now = datetime.now().strftime("%H:%M")
        say(f"Сейчас {now}.")
        return True

    if action.type == ActionType.GET_DATE:
        now = datetime.now()
        say(f"Сегодня {now.day:02d}.{now.month:02d}.{now.year}.")
        return True

    if action.type == ActionType.ASK_LLM:
        question = action.query or action.text
        result = ai_client.ask(question)
        say(result.message)
        return True

    if action.type == ActionType.EMPTY:
        say("Команда пустая.")
        return True

    if action.type == ActionType.UNKNOWN:
        if voice is None:
            say("Не понял команду.")
        return True

    return True


def run_text_mode(
    settings: Settings,
    apps: dict[str, AppConfig],
    app_manager: WindowsAppManager,
    ai_client: AIClient,
    logger: logging.Logger,
) -> None:
    print("Текстовый режим. Пиши команды так же, как сказал бы голосом.")
    print(f"Пример с именем: {settings.assistant_name}, открой блокнот")

    if settings.allow_commands_without_wake:
        print("Режим разработки: явные команды можно писать без имени.")
        print("Пример без имени: открой блокнот")
    else:
        print(f"Сначала нужно назвать ассистента: {settings.assistant_name}")

    if settings.allow_conversation_without_wake:
        print("Разговорный режим: обычные фразы можно писать без имени.")

    print("Примеры: найди Python, открой ютуб, сколько времени")
    print("Для выхода: Астра, стоп")

    while True:
        try:
            user_text = input("Ты: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nАстра: Завершаю работу.")
            return

        parsed = extract_command_after_wake(user_text, settings.wake_phrases)
        had_wake = parsed.type != CommandType.NO_WAKE

        if parsed.type == CommandType.NO_WAKE:
            parsed = parse_without_wake_if_allowed(
                raw_text=user_text,
                allow_without_wake=settings.allow_commands_without_wake,
                logger=logger,
            )

            if (
                parsed.type == CommandType.NO_WAKE
                and not settings.llm_router_enabled
                and not settings.allow_conversation_without_wake
            ):
                print(f"Астра: Сначала назови меня: {settings.assistant_name}.")
                continue

        if parsed.type == CommandType.WAKE_ONLY:
            follow_up = input("Астра: Слушаю.\nТы: ").strip()
            parsed = parse_command_text(follow_up)
            user_text = follow_up
            had_wake = True

        action = resolve_action(
            raw_text=user_text,
            parsed=parsed,
            had_wake=had_wake,
            apps=apps,
            ai_client=ai_client,
            settings=settings,
            logger=logger,
        )

        should_continue = handle_action(action, app_manager, ai_client, voice=None)
        if not should_continue:
            return


def run_voice_mode(
    settings: Settings,
    apps: dict[str, AppConfig],
    app_manager: WindowsAppManager,
    ai_client: AIClient,
    logger: logging.Logger,
) -> None:
    voice = VoiceIO(settings=settings, logger=logger)
    voice.speak(f"{settings.assistant_name} запущена.")

    if settings.allow_commands_without_wake:
        logger.info("Режим разработки: явные команды можно выполнять без wake phrase.")
        print("Режим разработки: можно говорить 'открой блокнот' без имени.")

    if settings.allow_conversation_without_wake:
        logger.info("Разговорный режим без wake phrase включён.")
        print("Разговорный режим: можно говорить обычные фразы без имени.")

    while True:
        listen_result = voice.listen_once()
        if not listen_result.ok:
            logger.info("STT: %s", listen_result.error)
            continue

        parsed = extract_command_after_wake(listen_result.text, settings.wake_phrases)
        had_wake = parsed.type != CommandType.NO_WAKE

        if parsed.type == CommandType.NO_WAKE:
            parsed = parse_without_wake_if_allowed(
                raw_text=listen_result.text,
                allow_without_wake=settings.allow_commands_without_wake,
                logger=logger,
            )

            if (
                parsed.type == CommandType.NO_WAKE
                and not settings.llm_router_enabled
                and not settings.allow_conversation_without_wake
            ):
                continue

        if parsed.type == CommandType.WAKE_ONLY:
            voice.speak("Слушаю.")
            follow_up = voice.listen_once()
            if not follow_up.ok:
                voice.speak(follow_up.error)
                continue
            parsed = parse_command_text(follow_up.text)
            listen_text = follow_up.text
            had_wake = True
        else:
            listen_text = listen_result.text

        action = resolve_action(
            raw_text=listen_text,
            parsed=parsed,
            had_wake=had_wake,
            apps=apps,
            ai_client=ai_client,
            settings=settings,
            logger=logger,
        )

        should_continue = handle_action(action, app_manager, ai_client, voice=voice)
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
            run_text_mode(settings, apps, app_manager, ai_client, logger)
        else:
            run_voice_mode(settings, apps, app_manager, ai_client, logger)
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
