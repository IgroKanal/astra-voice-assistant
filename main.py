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
    UNSUPPORTED_CLOSE_TARGET,
    UNSUPPORTED_OPEN_TARGET,
    extract_command_after_wake,
    is_command_like_text,
    normalize_text,
    parse_command_text,
)
from src.config_loader import AppConfig, ConfigError, Settings, load_apps_config, load_settings
from src.folder_controller import FolderController
from src.keyboard_controller import KeyboardController
from src.system_controller import SystemController
from src.logger_setup import setup_logging
from src.task_router import (
    ActionType,
    AssistantAction,
    find_site_url,
    google_search_url,
    normalize_url_or_site,
)
from src.windows_app_manager import WindowsAppManager


_DIRECT_COMMAND_TYPES = {
    CommandType.OPEN_APP,
    CommandType.CLOSE_APP,
    CommandType.OPEN_URL,
    CommandType.OPEN_FOLDER,
    CommandType.WEB_SEARCH,
    CommandType.GET_TIME,
    CommandType.GET_DATE,
    CommandType.KEYBOARD_SHORTCUT,
    CommandType.HELP,
    CommandType.EXIT,
}

_WAKE_REQUIRED_TYPES = {
    CommandType.TYPE_TEXT,
    CommandType.SCREENSHOT,
    CommandType.SYSTEM_INFO,
}

_ROUTER_BLOCKED_ACTION_TYPES = {
    ActionType.KEYBOARD_SHORTCUT,
    ActionType.TYPE_TEXT,
    ActionType.SCREENSHOT,
    ActionType.SYSTEM_INFO,
}

_REQUIRES_WAKE_TARGET = "__requires_wake__"


@dataclass
class TurnState:
    last_router_call_at: float = 0.0


@dataclass(frozen=True)
class TurnContext:
    settings: Settings
    apps: dict[str, AppConfig]
    app_manager: WindowsAppManager
    keyboard: KeyboardController
    folders: FolderController
    system: SystemController
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
    parser.add_argument(
        "--stt-test",
        action="store_true",
        help="Безопасная диагностика распознавания речи без выполнения команд.",
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



def _parsed_for_scoring(text: str, settings: Settings) -> tuple[ParsedCommand, bool]:
    parsed = extract_command_after_wake(text, settings.wake_phrases)
    had_wake = parsed.type != CommandType.NO_WAKE
    if parsed.type == CommandType.NO_WAKE:
        parsed = parse_command_text(text)
    return parsed, had_wake


def score_stt_alternative(
    text: str,
    settings: Settings,
    app_manager: WindowsAppManager,
) -> int:
    parsed, had_wake = _parsed_for_scoring(text, settings)
    normalized = normalize_text(text)
    score = 0

    if had_wake:
        score += 15

    local_types = _DIRECT_COMMAND_TYPES | _WAKE_REQUIRED_TYPES
    if parsed.type in local_types:
        score += 120
    elif parsed.type == CommandType.ASK_LLM:
        score += 20 if is_command_like_text(text) else 5
    elif parsed.type in {CommandType.NO_WAKE, CommandType.EMPTY}:
        score -= 50

    if parsed.type in {CommandType.OPEN_APP, CommandType.CLOSE_APP}:
        if parsed.target and app_manager.find_app(parsed.target) is not None:
            score += 90
        elif parsed.target:
            score += 10
        else:
            score -= 60

    if parsed.type == CommandType.OPEN_URL:
        if find_site_url(parsed.target):
            score += 90
        elif parsed.target:
            score += 10
        else:
            score -= 60

    if parsed.type == CommandType.WEB_SEARCH:
        if parsed.target:
            score += 35
        else:
            score -= 40

    if parsed.type == CommandType.KEYBOARD_SHORTCUT:
        score += 80
    if parsed.type in {CommandType.GET_TIME, CommandType.GET_DATE, CommandType.HELP}:
        score += 70
    if parsed.type in {CommandType.SCREENSHOT, CommandType.SYSTEM_INFO, CommandType.TYPE_TEXT}:
        score += 60

    # Мягкий бонус за внятные латинские технические названия.
    for token in ("vs code", "vscode", "youtube", "chatgpt", "telegram", "firefox"):
        if token in normalized:
            score += 12

    return score


def choose_stt_alternative(
    alternatives: list[str],
    settings: Settings,
    app_manager: WindowsAppManager,
    logger: logging.Logger,
) -> str:
    if not alternatives:
        return ""

    scored = [
        (score_stt_alternative(item, settings, app_manager), index, item.strip())
        for index, item in enumerate(alternatives)
        if item.strip()
    ]
    if not scored:
        return ""

    scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    selected = scored[0][2]

    if selected != alternatives[0].strip():
        logger.info("STT command-aware selected: %r from scored=%s", selected, scored)

    return selected


def shorten_voice_response(message: str, settings: Settings) -> str:
    if not settings.voice_short_responses:
        return message

    limit = max(80, settings.voice_max_speak_chars)
    clean = " ".join(message.strip().split())
    if len(clean) <= limit:
        return clean

    sentence_end_positions = [
        clean.find(marker) for marker in (". ", "! ", "? ") if clean.find(marker) != -1
    ]
    if sentence_end_positions:
        end = min(sentence_end_positions) + 1
        if 30 <= end <= limit:
            return clean[:end] + " Подробности смотри в логах."

    return clean[:limit].rstrip() + "... Подробности смотри в логах."

def parsed_to_action(parsed: ParsedCommand, source: str = "local") -> AssistantAction:
    mapping = {
        CommandType.OPEN_APP: ActionType.OPEN_APP,
        CommandType.CLOSE_APP: ActionType.CLOSE_APP,
        CommandType.OPEN_URL: ActionType.OPEN_URL,
        CommandType.OPEN_FOLDER: ActionType.OPEN_FOLDER,
        CommandType.WEB_SEARCH: ActionType.WEB_SEARCH,
        CommandType.GET_TIME: ActionType.GET_TIME,
        CommandType.GET_DATE: ActionType.GET_DATE,
        CommandType.KEYBOARD_SHORTCUT: ActionType.KEYBOARD_SHORTCUT,
        CommandType.TYPE_TEXT: ActionType.TYPE_TEXT,
        CommandType.SCREENSHOT: ActionType.SCREENSHOT,
        CommandType.SYSTEM_INFO: ActionType.SYSTEM_INFO,
        CommandType.HELP: ActionType.HELP,
        CommandType.ASK_LLM: ActionType.ASK_LLM,
        CommandType.EXIT: ActionType.EXIT,
        CommandType.EMPTY: ActionType.EMPTY,
    }

    # Для локальных команд нельзя подставлять полный текст в query,
    # иначе "найди" без запроса превращается в поиск слова "найди".
    query = parsed.target
    if parsed.type == CommandType.ASK_LLM:
        query = parsed.target or parsed.text

    return AssistantAction(
        type=mapping.get(parsed.type, ActionType.UNKNOWN),
        text=parsed.text,
        target=parsed.target,
        query=query,
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

    if direct_command.type in _WAKE_REQUIRED_TYPES:
        if logger is not None:
            logger.info(
                "Команда требует wake phrase и пропущена без имени: %s",
                direct_command,
            )
        return ParsedCommand(
            CommandType.NO_WAKE,
            text=raw_text,
            target=_REQUIRES_WAKE_TARGET,
        )

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

    router_returned_unknown = False

    if can_use_router:
        ctx.state.last_router_call_at = time.monotonic()
        route = ctx.ai_client.route_command(raw_text, ctx.apps)

        if route.ok:
            action = route.action
            ctx.logger.info("LLM-router: %s", action)

            if action.type in _ROUTER_BLOCKED_ACTION_TYPES:
                ctx.logger.warning(
                    "LLM-router вернул локальное действие, заблокировано в v0.8.3: %s",
                    action.type.value,
                )
                router_returned_unknown = True
            elif (
                action.confidence >= ctx.settings.llm_router_min_confidence
                and action.type != ActionType.UNKNOWN
            ):
                return action
            else:
                ctx.logger.info(
                    "LLM-router confidence too low or unknown: %s < %s",
                    action.confidence,
                    ctx.settings.llm_router_min_confidence,
                )
                if action.type == ActionType.UNKNOWN:
                    router_returned_unknown = True

    elif command_like and router_cooldown_active(ctx.settings, ctx.state):
        ctx.logger.info("LLM-router пропущен: активен cooldown.")

    if router_returned_unknown and command_like:
        return AssistantAction(
            type=ActionType.UNKNOWN,
            text=raw_text,
            confidence=0.0,
            source="router_unknown_guard",
            reason="Command-like phrase was rejected by router.",
        )

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


def build_help_text() -> str:
    return (
        "Я умею открывать сайты, приложения и папки, управлять вкладками, "
        "искать в интернете, делать скриншот и говорить статус системы. "
        "Примеры: открой ютуб, закрой вкладку, Астра, сделай скриншот. "
        "Текст пишу только в активное окно после имени."
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
        if action.target == UNSUPPORTED_OPEN_TARGET:
            ctx.respond("Открытие окна отключено. Скажи: открой Firefox или открой VS Code.")
            return True
        result = ctx.app_manager.open_app(action.target)
        ctx.respond(result.message)
        return True

    if action.type == ActionType.CLOSE_APP:
        if not action.target:
            ctx.respond("Что закрыть?")
            return True
        if action.target == UNSUPPORTED_CLOSE_TARGET:
            ctx.respond(
                "Закрытие окна отключено. "
                "Скажи: закрой Firefox или закрой VS Code."
            )
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

    if action.type == ActionType.OPEN_FOLDER:
        result = ctx.folders.open_folder(action.target or action.query)
        ctx.respond(result.message)
        return True

    if action.type == ActionType.WEB_SEARCH:
        query = action.query or action.target or action.text
        if not query:
            ctx.respond("Что найти?")
            return True
        webbrowser.open(google_search_url(query))
        ctx.respond("Ищу.")
        return True

    if action.type == ActionType.KEYBOARD_SHORTCUT:
        result = ctx.keyboard.send_shortcut(action.target or action.query)
        ctx.respond(result.message)
        return True

    if action.type == ActionType.TYPE_TEXT:
        text_to_type = action.target or action.query

        if text_to_type.startswith("app=") and ";text=" in text_to_type:
            app_part, text_part = text_to_type.split(";text=", 1)
            app_name = app_part.removeprefix("app=").strip()
            text_to_type = text_part.strip()

            ctx.logger.info(
                "Targeted typing is disabled in v0.8.3: app=%s text_len=%s",
                app_name,
                len(text_to_type),
            )
            ctx.respond(
                "Пока я пишу только в активное окно. "
                f"Кликни в {app_name} и скажи: Астра, напиши {text_to_type}"
            )
            return True

        result = ctx.keyboard.type_text(text_to_type)
        ctx.respond(result.message)
        return True

    if action.type == ActionType.SCREENSHOT:
        result = ctx.system.take_screenshot()
        ctx.respond(result.message)
        return True

    if action.type == ActionType.SYSTEM_INFO:
        result = ctx.system.system_info(action.target or action.query)
        ctx.respond(result.message)
        return True

    if action.type == ActionType.HELP:
        ctx.respond(build_help_text())
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

        if parsed.target == _REQUIRES_WAKE_TARGET:
            if ctx.respond_to_unknown:
                ctx.respond("Назови меня перед этой командой.")
            return True

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



def run_stt_test_mode(
    settings: Settings,
    apps: dict[str, AppConfig],
    app_manager: WindowsAppManager,
    logger: logging.Logger,
) -> None:
    print("STT test mode. Команды НЕ выполняются. Ctrl+C для выхода.")
    voice = VoiceIO(settings=settings, logger=logger)
    voice.set_alternative_selector(
        lambda alternatives: choose_stt_alternative(
            alternatives,
            settings,
            app_manager,
            logger,
        )
    )

    while True:
        result = voice.listen_once()
        if not result.ok:
            print(f"STT: {result.error}")
            continue

        parsed, had_wake = _parsed_for_scoring(result.text, settings)
        print("-" * 60)
        print(f"Выбрано: {result.text}")
        print(f"Wake: {had_wake}")
        print(f"Parser: {parsed.type.value} target={parsed.target!r}")
        if result.alternatives:
            print("Варианты:")
            for index, item in enumerate(result.alternatives, start=1):
                score = score_stt_alternative(item, settings, app_manager)
                print(f"  {index}. [{score}] {item}")

def run_text_mode(
    settings: Settings,
    apps: dict[str, AppConfig],
    app_manager: WindowsAppManager,
    keyboard: KeyboardController,
    folders: FolderController,
    system: SystemController,
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

    print("Примеры: открой клод, закрой вкладку, Астра, напиши привет, помощь")
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
        keyboard=keyboard,
        folders=folders,
        system=system,
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
    keyboard: KeyboardController,
    folders: FolderController,
    system: SystemController,
    ai_client: AIClient,
    logger: logging.Logger,
) -> None:
    voice = VoiceIO(settings=settings, logger=logger)
    voice.set_alternative_selector(
        lambda alternatives: choose_stt_alternative(
            alternatives,
            settings,
            app_manager,
            logger,
        )
    )
    voice.speak(f"{settings.assistant_name} запущена.")

    if settings.allow_commands_without_wake:
        logger.info("Режим разработки: явные команды можно выполнять без wake phrase.")
        print("Режим разработки: можно говорить 'открой блокнот' без имени.")

    if settings.allow_voice_conversation_without_wake:
        logger.info("Разговорный режим без wake phrase включён.")
        print("Разговорный режим: можно говорить обычные фразы без имени.")

    state = TurnState()

    def respond(message: str) -> None:
        shortened = shorten_voice_response(message, settings)
        if shortened != message:
            logger.info("Voice response shortened. full=%r shortened=%r", message, shortened)
        voice.speak(shortened)

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
        keyboard=keyboard,
        folders=folders,
        system=system,
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

    app_manager = WindowsAppManager(
        apps=apps,
        logger=logger,
        browser_preferred=settings.browser_preferred,
    )
    keyboard = KeyboardController(
        logger=logger,
        browser_preferred=settings.browser_preferred,
        browser_focus_missing_timeout_seconds=settings.browser_focus_missing_timeout_seconds,
    )
    folders = FolderController(logger=logger)
    system = SystemController(logger=logger)
    ai_client = AIClient(settings=settings, logger=logger)

    try:
        if args.stt_test:
            run_stt_test_mode(settings, apps, app_manager, logger)
        elif args.text:
            run_text_mode(settings, apps, app_manager, keyboard, folders, system, ai_client, logger)
        else:
            run_voice_mode(settings, apps, app_manager, keyboard, folders, system, ai_client, logger)
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
