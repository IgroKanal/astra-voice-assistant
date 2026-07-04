from __future__ import annotations

import argparse
import logging
import platform
import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from src.ai_client import AIClient
from src.audio_io import VoiceIO
from src.command_parser import (
    CommandType,
    ParsedCommand,
    extract_command_after_wake,
    is_command_like_text,
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


@dataclass
class TurnState:
    last_router_call_at: float = 0.0


@dataclass(frozen=True)
class TurnContext:
    settings: Settings
    apps: dict[str, AppConfig]
    app_manager: WindowsAppManager
    ai_client: AIClient
    logger: logging.Logger
    respond: Callable[[str], None]
    get_follow_up: Callable[[], str]
    allow_conversation_without_wake: bool
    respond_to_unknown: bool
    state: TurnState


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
    Разрешает команды без имени ассистента только для явных локальных команд.

    Обычные разговорные фразы не считаются командами на этом этапе.
    """
    if not allow_without_wake:
        return ParsedCommand(CommandType.NO_WAKE, text=raw_text)

    direct_command = parse_command_text(raw_text)

    if direct_command.type in _DIRECT_COMMAND_TYPES:
        if logger is not None:
            logger.info("Команда без wake phrase разрешена: %s", direct_command)
        return direct_command

    return ParsedCommand(CommandType.NO_WAKE, text=raw_text)


def router_cooldown_active(settings: Settings, state: TurnState) -> bool:
    cooldown = max(0.0, settings.router_cooldown_seconds)
    if cooldown <= 0:
        return False

    return time.monotonic() - state.last_router_call_at < cooldown


def resolve_action(
    raw_text: str,
    parsed: ParsedCommand,
    had_wake: bool,
    ctx: TurnContext,
) -> AssistantAction:
    """
    Порядок обработки строго фиксирован:
    1. Локальный parser.
    2. Router только для command-like фраз.
    3. Conversation fallback, если он разрешён для текущего режима.
    """
    if parsed.type not in {CommandType.ASK_LLM, CommandType.NO_WAKE}:
        return parsed_to_action(parsed, source="local_parser")

    command_like = is_command_like_text(raw_text)

    can_use_router = (
        ctx.settings.llm_router_enabled
        and ctx.settings.llm_enabled
        and ctx.ai_client.is_available
        and command_like
        and not router_cooldown_active(ctx.settings, ctx.state)
    )

    if can_use_router:
        ctx.state.last_router_call_at = time.monotonic()
        route = ctx.ai_client.route_command(raw_text, ctx.apps)

        if route.ok:
            action = route.action
            ctx.logger.info("LLM-router: %s", action)

            if (
                action.confidence >= ctx.settings.llm_router_min_confidence
                and action.type != ActionType.UNKNOWN
            ):
                return action

            ctx.logger.info(
                "LLM-router confidence too low or unknown: %s < %s",
                action.confidence,
                ctx.settings.llm_router_min_confidence,
            )

    elif command_like and router_cooldown_active(ctx.settings, ctx.state):
        ctx.logger.info("LLM-router пропущен: активен cooldown.")

    if ctx.allow_conversation_without_wake or had_wake:
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


def handle_action(action: AssistantAction, ctx: TurnContext) -> bool:
    """
    Выполняет безопасное действие.

    Возвращает False, если нужно завершить приложение.
    """
    if action.type == ActionType.EXIT:
        ctx.respond("Завершаю работу.")
        return False

    if action.type == ActionType.OPEN_APP:
        if not action.target:
            ctx.respond("Что открыть?")
            return True
        result = ctx.app_manager.open_app(action.target)
        ctx.respond(result.message)
        return True

    if action.type == ActionType.CLOSE_APP:
        if not action.target:
            ctx.respond("Что закрыть?")
            return True
        result = ctx.app_manager.close_app(action.target)
        ctx.respond(result.message)
        return True

    if action.type == ActionType.OPEN_URL:
        url = normalize_url_or_site(action.url or action.target or action.query)
        if not url:
            ctx.respond("Какой сайт открыть?")
            return True
        webbrowser.open(url)
        ctx.respond("Открываю сайт.")
        return True

    if action.type == ActionType.WEB_SEARCH:
        query = action.query or action.target or action.text
        if not query:
            ctx.respond("Что найти?")
            return True
        webbrowser.open(google_search_url(query))
        ctx.respond("Ищу.")
        return True

    if action.type == ActionType.GET_TIME:
        now = datetime.now().strftime("%H:%M")
        ctx.respond(f"Сейчас {now}.")
        return True

    if action.type == ActionType.GET_DATE:
        now = datetime.now()
        ctx.respond(f"Сегодня {now.day:02d}.{now.month:02d}.{now.year}.")
        return True

    if action.type == ActionType.ASK_LLM:
        question = action.query or action.text
        result = ctx.ai_client.ask(question)
        ctx.respond(result.message)
        return True

    if action.type == ActionType.EMPTY:
        ctx.respond("Команда пустая.")
        return True

    if action.type == ActionType.UNKNOWN:
        if ctx.respond_to_unknown:
            ctx.respond("Не понял команду.")
        return True

    return True


def process_turn(raw_text: str, ctx: TurnContext) -> bool:
    """
    Обрабатывает один пользовательский turn.

    Функция не знает, откуда пришёл текст: из консоли или из микрофона.
    Разница режимов передаётся через callbacks и флаги TurnContext.
    """
    raw_text = raw_text.strip()
    if not raw_text:
        ctx.respond("Не расслышал, повтори.")
        return True

    parsed = extract_command_after_wake(raw_text, ctx.settings.wake_phrases)
    had_wake = parsed.type != CommandType.NO_WAKE

    if parsed.type == CommandType.NO_WAKE:
        parsed = parse_without_wake_if_allowed(
            raw_text=raw_text,
            allow_without_wake=ctx.settings.allow_commands_without_wake,
            logger=ctx.logger,
        )

    if parsed.type == CommandType.WAKE_ONLY:
        ctx.respond("Слушаю.")
        follow_up = ctx.get_follow_up().strip()

        if not follow_up:
            ctx.respond("Не расслышал, повтори.")
            return True

        parsed = parse_command_text(follow_up)
        raw_text = follow_up
        had_wake = True

    action = resolve_action(
        raw_text=raw_text,
        parsed=parsed,
        had_wake=had_wake,
        ctx=ctx,
    )

    ctx.logger.info(
        "decision_source=%s action=%s confidence=%.2f",
        action.source,
        action.type.value,
        action.confidence,
    )

    return handle_action(action, ctx)


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

    if settings.allow_text_conversation_without_wake:
        print("Разговорный режим: обычные фразы можно писать без имени.")

    print("Примеры: найди Python, открой ютуб, сколько времени")
    print("Для выхода: Астра, стоп")

    state = TurnState()

    def respond(message: str) -> None:
        print(f"Астра: {message}")

    def get_follow_up() -> str:
        try:
            return input("Ты: ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    ctx = TurnContext(
        settings=settings,
        apps=apps,
        app_manager=app_manager,
        ai_client=ai_client,
        logger=logger,
        respond=respond,
        get_follow_up=get_follow_up,
        allow_conversation_without_wake=settings.allow_text_conversation_without_wake,
        respond_to_unknown=True,
        state=state,
    )

    while True:
        try:
            user_text = input("Ты: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nАстра: Завершаю работу.")
            return

        should_continue = process_turn(user_text, ctx)
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

    if settings.allow_voice_conversation_without_wake:
        logger.info("Разговорный режим без wake phrase включён.")
        print("Разговорный режим: можно говорить обычные фразы без имени.")

    state = TurnState()

    def respond(message: str) -> None:
        voice.speak(message)

    def get_follow_up() -> str:
        follow_up = voice.listen_once()
        if not follow_up.ok:
            logger.info("STT follow-up: %s", follow_up.error)
            return ""
        return follow_up.text

    ctx = TurnContext(
        settings=settings,
        apps=apps,
        app_manager=app_manager,
        ai_client=ai_client,
        logger=logger,
        respond=respond,
        get_follow_up=get_follow_up,
        allow_conversation_without_wake=settings.allow_voice_conversation_without_wake,
        respond_to_unknown=False,
        state=state,
    )

    while True:
        listen_result = voice.listen_once()
        if not listen_result.ok:
            logger.info("STT: %s", listen_result.error)
            continue

        should_continue = process_turn(listen_result.text, ctx)
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
