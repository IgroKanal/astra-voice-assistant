from __future__ import annotations

import argparse
import logging
import platform
import re
import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.ai_client import AIClient
from src.audio_io import VoiceIO
from src.command_parser import (
    CommandType,
    ParsedCommand,
    AMBIGUOUS_CHAT_TARGET,
    AMBIGUOUS_MUSIC_TARGET,
    MIXED_COMMAND_TARGET,
    UNRESOLVED_CONTEXT_TARGET,
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
from src.routine_controller import RoutineConfigError, RoutineController, RoutineDefinition
from src.system_controller import SystemController
from src.vpn_controller import VpnController
from src.window_controller import WindowController
from src.logger_setup import setup_logging
from src.task_router import (
    ActionType,
    AssistantAction,
    find_site_url,
    google_search_url,
    normalize_url_or_site,
    youtube_search_url,
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
    CommandType.VPN_CONTROL,
    CommandType.WINDOW_CONTROL,
    CommandType.VOICE_FEEDBACK,
    CommandType.ROUTINE,
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
    ActionType.VPN_CONTROL,
    ActionType.WINDOW_CONTROL,
    ActionType.VOICE_FEEDBACK,
    ActionType.ROUTINE,
}

_REQUIRES_WAKE_TARGET = "__requires_wake__"
_PENDING_TTL_SECONDS = 20.0


@dataclass
class TurnState:
    last_router_call_at: float = 0.0
    last_recognized_text: str = ""
    last_assistant_response: str = ""
    pending_kind: str = ""
    pending_created_at: float = 0.0
    last_context_kind: str = ""
    last_context_target: str = ""
    last_context_at: float = 0.0


@dataclass(frozen=True)
class TurnContext:
    settings: Settings
    apps: dict[str, AppConfig]
    app_manager: WindowsAppManager
    keyboard: KeyboardController
    folders: FolderController
    system: SystemController
    vpn: VpnController
    windows: WindowController
    ai_client: AIClient
    logger: logging.Logger
    respond: Callable[[str], None]
    get_follow_up: Callable[[], str]
    allow_conversation_without_wake: bool
    respond_to_unknown: bool
    state: TurnState
    routines: RoutineController | None = None


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
    if parsed.type == CommandType.VPN_CONTROL:
        score += 85
    if parsed.type == CommandType.WINDOW_CONTROL:
        score += 75
    if parsed.type == CommandType.VOICE_FEEDBACK:
        score += 75
    if parsed.type == CommandType.ROUTINE:
        score += 90

    # Мягкий бонус за внятные латинские технические названия.
    for token in ("vs code", "vscode", "youtube", "chatgpt", "telegram", "firefox", "vpn", "впн"):
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

def clear_pending(state: TurnState) -> None:
    state.pending_kind = ""
    state.pending_created_at = 0.0


def set_pending(state: TurnState, kind: str) -> None:
    state.pending_kind = kind
    state.pending_created_at = time.monotonic()


def pending_is_active(state: TurnState) -> bool:
    if not state.pending_kind:
        return False
    return time.monotonic() - state.pending_created_at <= _PENDING_TTL_SECONDS


def remember_context(ctx: TurnContext, kind: str, target: str) -> None:
    clean_target = target.strip()
    if not kind or not clean_target:
        return
    ctx.state.last_context_kind = kind
    ctx.state.last_context_target = clean_target
    ctx.state.last_context_at = time.monotonic()
    ctx.logger.info("context_saved kind=%s target=%r", kind, clean_target)


def clear_context(state: TurnState) -> None:
    state.last_context_kind = ""
    state.last_context_target = ""
    state.last_context_at = 0.0


def context_is_active(ctx: TurnContext) -> bool:
    if not ctx.state.last_context_kind or not ctx.state.last_context_target:
        return False
    ttl = max(0.0, ctx.settings.context_ttl_seconds)
    if ttl <= 0 or time.monotonic() - ctx.state.last_context_at > ttl:
        clear_context(ctx.state)
        return False
    return True


def resolve_context_reference(parsed: ParsedCommand, ctx: TurnContext) -> ParsedCommand:
    """Resolve only narrow pronouns against the last successful local action."""
    pronouns = {"его", "ее", "её", "это", "последнее", "последний"}

    if parsed.type == CommandType.CLOSE_APP and normalize_text(parsed.target) in pronouns:
        if not context_is_active(ctx):
            return ParsedCommand(
                CommandType.CLOSE_APP,
                text=parsed.text,
                target=UNRESOLVED_CONTEXT_TARGET,
            )
        if ctx.state.last_context_kind == "app":
            return ParsedCommand(
                CommandType.CLOSE_APP,
                text=parsed.text,
                target=ctx.state.last_context_target,
            )
        if ctx.state.last_context_kind == "site":
            return ParsedCommand(
                CommandType.KEYBOARD_SHORTCUT,
                text=parsed.text,
                target="close_tab",
            )
        return ParsedCommand(
            CommandType.CLOSE_APP,
            text=parsed.text,
            target=UNRESOLVED_CONTEXT_TARGET,
        )

    if parsed.type == CommandType.WINDOW_CONTROL and parsed.target.startswith("focus:"):
        focus_target = normalize_text(parsed.target.removeprefix("focus:"))
        if focus_target not in pronouns:
            return parsed
        if not context_is_active(ctx):
            return ParsedCommand(
                CommandType.WINDOW_CONTROL,
                text=parsed.text,
                target=f"focus:{UNRESOLVED_CONTEXT_TARGET}",
            )
        targets_by_kind = {
            "app": ctx.state.last_context_target,
            "site": "браузер",
            "folder": "проводник",
            "window": ctx.state.last_context_target,
        }
        target = targets_by_kind.get(ctx.state.last_context_kind, "")
        if target:
            return ParsedCommand(
                CommandType.WINDOW_CONTROL,
                text=parsed.text,
                target=f"focus:{target}",
            )
        return ParsedCommand(
            CommandType.WINDOW_CONTROL,
            text=parsed.text,
            target=f"focus:{UNRESOLVED_CONTEXT_TARGET}",
        )

    return parsed


def _clean_follow_up_target(raw_text: str) -> str:
    value = normalize_text(raw_text)
    for prefix in ("на ", "no ", "в ", "к ", "ко "):
        if value.startswith(prefix):
            return value.removeprefix(prefix).strip()
    return value.strip()


def _strip_wake_prefix_for_follow_up(raw_text: str, settings: Settings) -> str:
    """Возвращает follow-up без имени ассистента, если пользователь повторил wake phrase.

    В wake-only режиме после уточнения пользователь может сказать как "ютуб", так и
    "Астра, ютуб". Pending-follow-up должен понимать оба варианта.
    """
    clean_text = raw_text.strip()
    if not clean_text:
        return ""

    lowered = clean_text.lower().replace("ё", "е")
    wake_phrases = sorted(settings.wake_phrases, key=len, reverse=True)

    for phrase in wake_phrases:
        normalized_phrase = normalize_text(phrase)
        if not normalized_phrase:
            continue
        phrase_pattern = r"\s+".join(re.escape(part) for part in normalized_phrase.split())
        pattern = rf"^\s*{phrase_pattern}(?=\s|[,.:;!?-]|$)"
        match = re.match(pattern, lowered, flags=re.IGNORECASE)
        if match:
            return clean_text[match.end():].strip(" \t\r\n,.!?;:-")

    return clean_text


def resolve_pending_follow_up(raw_text: str, ctx: TurnContext) -> AssistantAction | None:
    """Обрабатывает короткий ответ пользователя после уточнения Астры.

    Примеры:
    - Астра: "Что открыть?" -> пользователь: "ютуб" -> открыть YouTube.
    - Астра: "На какое окно переключиться?" -> "на Firefox" -> focus:firefox.
    - Астра: "Какой чат открыть?" -> "чат gpt" -> открыть ChatGPT.

    Это закрывает часть STT-проблем, когда длинная команда распалась на два
    распознавания и конец фразы пришёл отдельным turn-ом.
    """
    if not pending_is_active(ctx.state):
        clear_pending(ctx.state)
        return None

    follow_up_text = _strip_wake_prefix_for_follow_up(raw_text, ctx.settings)

    direct = parse_command_text(follow_up_text)
    if direct.type == CommandType.EXIT:
        return None

    # Если пользователь сказал полноценную новую локальную команду, она важнее
    # старого уточнения. Bare target вроде "чат gpt" обычно остаётся ASK_LLM.
    if direct.type in _DIRECT_COMMAND_TYPES and direct.type != CommandType.VOICE_FEEDBACK:
        if direct.target and direct.target not in {
            AMBIGUOUS_CHAT_TARGET,
            AMBIGUOUS_MUSIC_TARGET,
            MIXED_COMMAND_TARGET,
            UNSUPPORTED_OPEN_TARGET,
            UNSUPPORTED_CLOSE_TARGET,
        }:
            return None

    target = _clean_follow_up_target(follow_up_text)
    if not target:
        return None

    kind = ctx.state.pending_kind

    if kind == "ambiguous_chat":
        if any(token in target for token in ("gpt", "гпт", "джипити", "чат")):
            parsed = parse_command_text("открой чат gpt")
            return parsed_to_action(parsed, source="pending_followup")
        if any(token in target for token in ("telegram", "телеграм", "телега", "тг")):
            parsed = parse_command_text("открой телеграм")
            return parsed_to_action(parsed, source="pending_followup")

    if kind == "ambiguous_music":
        if any(token in target for token in ("яндекс", "yandex")):
            parsed = parse_command_text("открой яндекс музыку")
            return parsed_to_action(parsed, source="pending_followup")
        if target in {"локальную", "локальная", "скачанную", "скачанные", "файлы"}:
            parsed = parse_command_text("открой музыку")
            return parsed_to_action(parsed, source="pending_followup")

    if kind == "window_focus":
        return AssistantAction(
            type=ActionType.WINDOW_CONTROL,
            text=raw_text,
            target=f"focus:{target}",
            confidence=1.0,
            source="pending_followup",
        )

    if kind == "open":
        parsed = parse_command_text(f"открой {target}")
        if parsed.type in {CommandType.OPEN_APP, CommandType.OPEN_URL, CommandType.OPEN_FOLDER}:
            return parsed_to_action(parsed, source="pending_followup")

    if kind == "close":
        parsed = parse_command_text(f"закрой {target}")
        if parsed.type in {CommandType.CLOSE_APP, CommandType.KEYBOARD_SHORTCUT}:
            return parsed_to_action(parsed, source="pending_followup")

    if kind == "open_url":
        parsed = parse_command_text(f"открой {target}")
        if parsed.type == CommandType.OPEN_URL:
            return parsed_to_action(parsed, source="pending_followup")

    if kind == "search":
        return AssistantAction(
            type=ActionType.WEB_SEARCH,
            text=raw_text,
            query=target,
            confidence=1.0,
            source="pending_followup",
        )

    if kind == "youtube_search":
        return AssistantAction(
            type=ActionType.WEB_SEARCH,
            text=raw_text,
            query=f"youtube:{target}",
            confidence=1.0,
            source="pending_followup",
        )

    return None


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
        CommandType.VPN_CONTROL: ActionType.VPN_CONTROL,
        CommandType.WINDOW_CONTROL: ActionType.WINDOW_CONTROL,
        CommandType.VOICE_FEEDBACK: ActionType.VOICE_FEEDBACK,
        CommandType.ROUTINE: ActionType.ROUTINE,
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

    if command_like and not had_wake and not ctx.settings.allow_commands_without_wake:
        ctx.logger.info(
            "Command-like phrase without wake phrase blocked before LLM-router: %s",
            raw_text,
        )
        return AssistantAction(
            type=ActionType.UNKNOWN,
            text=raw_text,
            confidence=0.0,
            source="wake_required_guard",
            reason="Command-like action requires wake phrase when commands without wake are disabled.",
        )

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


def build_help_text(topic: str = "general") -> str:
    topic = (topic or "general").strip().lower()

    help_by_topic = {
        "general": (
            "Я умею открывать сайты, приложения и папки, управлять вкладками, "
            "VPN, окнами, музыкой, громкостью и рабочим столом. "
            "Также доступен рабочий режим. "
            "Скажи: команды браузера, команды VPN или команды окон."
        ),
        "browser": (
            "Браузер: открой ютуб, закрой вкладку, обнови страницу, "
            "новая вкладка, новое окно браузера, открой загрузки браузера."
        ),
        "vpn": (
            "VPN: статус VPN, включи VPN, выключи VPN. "
            "Я управляю только настроенной службой AmneziaWG."
        ),
        "window": (
            "Окна: какие окна открыты, активное окно, переключись на Firefox, "
            "сверни окно, разверни окно, покажи рабочий стол."
        ),
        "system": (
            "Система: Астра, статус интернета, сколько памяти, сколько места, "
            "сделай скриншот."
        ),
        "voice": (
            "Голос: повтори, что ты услышала, стоп. "
            "Если фраза обрезалась, скажи команду короче или ответь на уточнение."
        ),
    }

    return help_by_topic.get(topic, help_by_topic["general"])


def _open_web_url(url: str, logger: logging.Logger) -> bool:
    try:
        return bool(webbrowser.open(url))
    except Exception:
        logger.exception("Browser open failed: url=%r", url)
        return False


def _execute_routine(routine: RoutineDefinition, ctx: TurnContext) -> tuple[int, int]:
    """Execute only the controller-validated local steps in a routine."""
    succeeded = 0
    for step in routine.steps:
        ok = False
        detail = ""

        if step.action == "open_app":
            app = ctx.app_manager.find_app(step.target)
            if app is None:
                detail = "application is not in whitelist"
            else:
                focused = ctx.windows.focus_target(app.name)
                if focused.ok:
                    ok = True
                    detail = "focused existing window"
                else:
                    result = ctx.app_manager.open_app(step.target)
                    ok = result.ok
                    detail = result.message
                if ok:
                    remember_context(ctx, "app", app.name)

        elif step.action == "open_url":
            url = normalize_url_or_site(step.target)
            if url:
                ok = _open_web_url(url, ctx.logger)
                detail = url if ok else "browser rejected URL"
                if ok:
                    remember_context(ctx, "site", url)
            else:
                detail = "URL is empty"

        elif step.action == "open_folder":
            result = ctx.folders.open_folder(step.target)
            ok = result.ok
            detail = result.message
            if ok:
                remember_context(ctx, "folder", step.target)

        if ok:
            succeeded += 1
        ctx.logger.info(
            "decision_source=routine routine=%s step=%s target=%r ok=%s detail=%r",
            routine.name,
            step.action,
            step.target,
            ok,
            detail,
        )

    return succeeded, len(routine.steps)

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
            set_pending(ctx.state, "open")
            ctx.respond("Что открыть?")
            return True
        if action.target == UNSUPPORTED_OPEN_TARGET:
            ctx.respond("Открытие окна отключено.")
            return True
        if action.target == AMBIGUOUS_CHAT_TARGET:
            set_pending(ctx.state, "ambiguous_chat")
            ctx.respond("Какой чат открыть: ChatGPT или Telegram?")
            return True
        if action.target == AMBIGUOUS_MUSIC_TARGET:
            set_pending(ctx.state, "ambiguous_music")
            ctx.respond("Какую музыку открыть: локальную или Яндекс Музыку?")
            return True
        if action.target == MIXED_COMMAND_TARGET:
            ctx.respond("Смешанные команды отключены.")
            return True
        app = ctx.app_manager.find_app(action.target)
        result = ctx.app_manager.open_app(action.target)
        if result.ok and app is not None:
            remember_context(ctx, "app", app.name)
        ctx.respond(result.message)
        return True

    if action.type == ActionType.CLOSE_APP:
        if not action.target:
            set_pending(ctx.state, "close")
            ctx.respond("Что закрыть?")
            return True
        if action.target == UNSUPPORTED_CLOSE_TARGET:
            ctx.respond("Закрытие окна отключено.")
            return True
        if action.target == UNRESOLVED_CONTEXT_TARGET:
            ctx.respond("Не помню, что нужно закрыть. Назови приложение или вкладку.")
            return True
        if action.target == MIXED_COMMAND_TARGET:
            ctx.respond("Смешанные команды отключены.")
            return True
        result = ctx.app_manager.close_app(action.target)
        if result.ok and context_is_active(ctx) and ctx.state.last_context_kind == "app":
            clear_context(ctx.state)
        ctx.respond(result.message)
        return True

    if action.type == ActionType.OPEN_URL:
        url = normalize_url_or_site(action.url or action.target or action.query)
        if not url:
            set_pending(ctx.state, "open_url")
            ctx.respond("Какой сайт открыть?")
            return True
        if _open_web_url(url, ctx.logger):
            remember_context(ctx, "site", url)
            ctx.respond("Открываю сайт.")
        else:
            ctx.respond("Не удалось открыть сайт.")
        return True

    if action.type == ActionType.OPEN_FOLDER:
        result = ctx.folders.open_folder(action.target or action.query)
        if result.ok:
            remember_context(ctx, "folder", action.target or action.query)
        ctx.respond(result.message)
        return True

    if action.type == ActionType.WEB_SEARCH:
        query = action.query or action.target or action.text
        if not query:
            set_pending(ctx.state, "search")
            ctx.respond("Что найти?")
            return True
        if query.startswith("youtube:"):
            search_query = query.removeprefix("youtube:").strip()
            if not search_query:
                set_pending(ctx.state, "youtube_search")
                ctx.respond("Что найти на YouTube?")
                return True
            url = youtube_search_url(search_query)
        else:
            url = google_search_url(query)
        if _open_web_url(url, ctx.logger):
            remember_context(ctx, "site", url)
            ctx.respond("Ищу.")
        else:
            ctx.respond("Не удалось открыть поиск.")
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


    if action.type == ActionType.VPN_CONTROL:
        vpn_action = action.target or action.query
        if vpn_action == "connect":
            result = ctx.vpn.connect()
        elif vpn_action == "disconnect":
            result = ctx.vpn.disconnect()
        else:
            result = ctx.vpn.status()
        ctx.respond(result.message)
        return True

    if action.type == ActionType.WINDOW_CONTROL:
        window_action = action.target or action.query
        if window_action == "list":
            result = ctx.windows.describe_open_windows()
        elif window_action == "active":
            result = ctx.windows.describe_active_window()
        elif window_action == "minimize":
            result = ctx.windows.minimize_active_window()
        elif window_action == "maximize":
            result = ctx.windows.maximize_active_window()
        elif window_action == "show_desktop":
            result = ctx.windows.show_desktop()
        elif window_action == "previous":
            result = ctx.windows.focus_previous_window()
        elif window_action == "focus:":
            set_pending(ctx.state, "window_focus")
            ctx.respond("На какое окно переключиться?")
            return True
        elif window_action.startswith("focus:"):
            focus_target = window_action.removeprefix("focus:")
            if focus_target == UNRESOLVED_CONTEXT_TARGET:
                ctx.respond("Не помню предыдущее приложение. Назови окно явно.")
                return True
            result = ctx.windows.focus_target(focus_target)
            if result.ok:
                remember_context(ctx, "window", focus_target)
        else:
            result = ctx.windows.describe_open_windows()
        ctx.respond(result.message)
        return True

    if action.type == ActionType.ROUTINE:
        if ctx.routines is None or not ctx.routines.enabled:
            ctx.respond("Режимы отключены в настройках.")
            return True
        routine = ctx.routines.resolve(action.target or action.query)
        if routine is None:
            ctx.respond("Не знаю такой режим.")
            return True
        succeeded, total = _execute_routine(routine, ctx)
        if succeeded == total:
            ctx.respond(routine.response)
        elif succeeded:
            ctx.respond("Режим выполнен частично. Подробности смотри в логах.")
        else:
            ctx.respond("Не удалось запустить режим. Подробности смотри в логах.")
        return True

    if action.type == ActionType.VOICE_FEEDBACK:
        feedback_target = action.target or action.query
        if feedback_target == "repeat_last":
            if ctx.state.last_assistant_response:
                ctx.respond(ctx.state.last_assistant_response)
            else:
                ctx.respond("Пока нечего повторять.")
            return True

        if feedback_target == "last_heard":
            if ctx.state.last_recognized_text:
                ctx.respond(f"Я услышала: {ctx.state.last_recognized_text}.")
            else:
                ctx.respond("Пока ничего не услышала.")
            return True

        ctx.respond("Готово.")
        return True

    if action.type == ActionType.HELP:
        ctx.respond(build_help_text(action.target or action.query or "general"))
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
            if action.source == "wake_required_guard":
                ctx.respond("Назови меня перед этой командой.")
            else:
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

    pending_action = resolve_pending_follow_up(raw_text, ctx)
    if pending_action is not None:
        clear_pending(ctx.state)
        ctx.logger.info(
            "decision_source=%s action=%s confidence=%.2f",
            pending_action.source,
            pending_action.type.value,
            pending_action.confidence,
        )
        should_continue = handle_action(pending_action, ctx)
        if pending_action.type != ActionType.VOICE_FEEDBACK and raw_text:
            ctx.state.last_recognized_text = raw_text
        return should_continue

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

    parsed = resolve_context_reference(parsed, ctx)

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

    clear_pending(ctx.state)
    should_continue = handle_action(action, ctx)

    if action.type != ActionType.VOICE_FEEDBACK and raw_text:
        ctx.state.last_recognized_text = raw_text

    return should_continue



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
    vpn: VpnController,
    windows: WindowController,
    ai_client: AIClient,
    logger: logging.Logger,
    routines: RoutineController | None = None,
) -> None:
    print("Текстовый режим. Пиши команды так же, как сказал бы голосом.")
    print(f"Пример с именем: {settings.assistant_name}, открой блокнот")

    if settings.allow_commands_without_wake:
        print("Режим разработки: явные команды можно писать без имени.")
        print("Пример без имени: открой блокнот")
    else:
        print(f"Сначала нужно назвать ассистента: {settings.assistant_name}")

    if settings.allow_text_conversation_without_wake:
        print("Разговорный режим: обычные вопросы можно писать без имени.")

    if settings.allow_commands_without_wake:
        print("Примеры: открой клод, закрой вкладку, включи VPN, статус VPN, помощь")
    else:
        print(
            "Примеры: Астра, открой клод; Астра, закрой вкладку; "
            "Астра, включи VPN; Астра, статус VPN; Астра, помощь"
        )
    print(f"Для выхода: {settings.assistant_name}, стоп")

    state = TurnState()

    def respond(message: str) -> None:
        state.last_assistant_response = message
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
        vpn=vpn,
        windows=windows,
        ai_client=ai_client,
        logger=logger,
        respond=respond,
        get_follow_up=get_follow_up,
        allow_conversation_without_wake=settings.allow_text_conversation_without_wake,
        respond_to_unknown=True,
        state=state,
        routines=routines,
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


def _wake_only_voice_enabled(settings: Settings) -> bool:
    mode = (settings.voice_runtime_mode or "").strip().lower()
    return settings.wake_only_mode or mode in {"wake_only", "wake", "wake-only"}


def _voice_command_text_with_wake(settings: Settings, command_text: str) -> str:
    return f"{settings.assistant_name}, {command_text.strip()}"


def _listen_pending_voice_follow_up(
    voice: VoiceIO,
    ctx: TurnContext,
    settings: Settings,
    logger: logging.Logger,
) -> bool:
    """Даёт один короткий follow-up turn после уточняющего вопроса Астры.

    Это сохраняет удобный UX в wake-only режиме: после "Астра, открой" и ответа
    "Что открыть?" пользователь может сказать "ютуб" без повторного wake phrase.
    Окно follow-up существует только если предыдущее действие явно выставило pending.
    """
    if not pending_is_active(ctx.state):
        return True

    follow_up = voice.listen_once(
        timeout_seconds=settings.command_listen_timeout_seconds,
        phrase_time_limit_seconds=settings.command_phrase_time_limit_seconds,
        prompt="Слушаю уточнение...",
    )

    if not follow_up.ok:
        logger.info("Pending command session timeout/unknown: %s", follow_up.error)
        clear_pending(ctx.state)
        ctx.respond("Не расслышал, повтори.")
        return True

    logger.info("pending_command_session_text=%r", follow_up.text)
    return process_turn(follow_up.text, ctx)


def run_voice_mode(
    settings: Settings,
    apps: dict[str, AppConfig],
    app_manager: WindowsAppManager,
    keyboard: KeyboardController,
    folders: FolderController,
    system: SystemController,
    vpn: VpnController,
    windows: WindowController,
    ai_client: AIClient,
    logger: logging.Logger,
    routines: RoutineController | None = None,
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

    state = TurnState()

    def respond(message: str) -> None:
        shortened = shorten_voice_response(message, settings)
        if shortened != message:
            logger.info("Voice response shortened. full=%r shortened=%r", message, shortened)
        state.last_assistant_response = shortened
        voice.speak(shortened)

    def get_follow_up() -> str:
        follow_up = voice.listen_once(
            timeout_seconds=settings.command_listen_timeout_seconds,
            phrase_time_limit_seconds=settings.command_phrase_time_limit_seconds,
            prompt="Слушаю команду...",
        )
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
        vpn=vpn,
        windows=windows,
        ai_client=ai_client,
        logger=logger,
        respond=respond,
        get_follow_up=get_follow_up,
        allow_conversation_without_wake=settings.allow_voice_conversation_without_wake,
        respond_to_unknown=False,
        state=state,
        routines=routines,
    )

    if _wake_only_voice_enabled(settings):
        logger.info(
            "Wake-only voice runtime enabled. wake_timeout=%s wake_limit=%s command_timeout=%s command_limit=%s",
            settings.wake_listen_timeout_seconds,
            settings.wake_phrase_time_limit_seconds,
            settings.command_listen_timeout_seconds,
            settings.command_phrase_time_limit_seconds,
        )
        print("Wake-only режим: скажи 'Астра' перед командой.")

        while True:
            wake_result = voice.listen_once(
                timeout_seconds=settings.wake_listen_timeout_seconds,
                phrase_time_limit_seconds=settings.wake_phrase_time_limit_seconds,
                prompt="Жду: Астра...",
            )

            if not wake_result.ok:
                logger.info("Wake STT: %s", wake_result.error)
                continue

            parsed = extract_command_after_wake(
                wake_result.text,
                settings.wake_phrases,
            )

            if parsed.type == CommandType.NO_WAKE:
                logger.info("Wake ignored: no wake phrase in %r", wake_result.text)
                continue

            if parsed.type == CommandType.WAKE_ONLY:
                logger.info("wake_detected: wake_only")
                if settings.wake_response_enabled:
                    respond(settings.wake_response_text)

                command_result = voice.listen_once(
                    timeout_seconds=settings.command_listen_timeout_seconds,
                    phrase_time_limit_seconds=settings.command_phrase_time_limit_seconds,
                    prompt="Слушаю команду...",
                )

                if not command_result.ok:
                    logger.info("Command session timeout/unknown: %s", command_result.error)
                    respond("Не расслышал, повтори.")
                    continue

                logger.info(
                    "command_session_text=%r",
                    command_result.text,
                )
                should_continue = process_turn(
                    _voice_command_text_with_wake(settings, command_result.text),
                    ctx,
                )
                if not should_continue:
                    return

                should_continue = _listen_pending_voice_follow_up(
                    voice=voice,
                    ctx=ctx,
                    settings=settings,
                    logger=logger,
                )
                if not should_continue:
                    return
                continue

            logger.info("wake_detected: direct_command text=%r", wake_result.text)
            if not settings.wake_allow_direct_command:
                logger.info("Direct wake command disabled by WAKE_ALLOW_DIRECT_COMMAND=false")
                if settings.wake_response_enabled:
                    respond(settings.wake_response_text)
                command_result = voice.listen_once(
                    timeout_seconds=settings.command_listen_timeout_seconds,
                    phrase_time_limit_seconds=settings.command_phrase_time_limit_seconds,
                    prompt="Слушаю команду...",
                )
                if not command_result.ok:
                    logger.info("Command session timeout/unknown: %s", command_result.error)
                    respond("Не расслышал, повтори.")
                    continue
                should_continue = process_turn(
                    _voice_command_text_with_wake(settings, command_result.text),
                    ctx,
                )
            else:
                should_continue = process_turn(wake_result.text, ctx)

            if not should_continue:
                return

            should_continue = _listen_pending_voice_follow_up(
                voice=voice,
                ctx=ctx,
                settings=settings,
                logger=logger,
            )
            if not should_continue:
                return

    # Legacy/dev mode: старое поведение. Оставлено только для ручной отладки.
    if settings.allow_commands_without_wake:
        logger.info("Режим разработки: явные команды можно выполнять без wake phrase.")
        print("Режим разработки: можно говорить 'открой блокнот' без имени.")

    if settings.allow_voice_conversation_without_wake:
        logger.info("Разговорный режим без wake phrase включён.")
        print("Разговорный режим: можно говорить обычные фразы без имени.")

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

    routine_path = Path(settings.routines_config_path)
    if not routine_path.is_absolute():
        routine_path = Path(__file__).resolve().parent / routine_path
    try:
        routines = RoutineController(
            config_path=routine_path,
            enabled=settings.routines_enabled,
            logger=logger,
        )
    except RoutineConfigError as exc:
        logger.error("Ошибка конфигурации routines: %s", exc)
        print(f"Ошибка конфигурации routines: {exc}")
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
    vpn = VpnController(settings=settings, logger=logger)
    windows = WindowController(
        logger=logger,
        browser_preferred=settings.browser_preferred,
    )
    ai_client = AIClient(settings=settings, logger=logger)

    try:
        if args.stt_test:
            run_stt_test_mode(settings, apps, app_manager, logger)
        elif args.text:
            run_text_mode(
                settings, apps, app_manager, keyboard, folders, system, vpn,
                windows, ai_client, logger, routines,
            )
        else:
            run_voice_mode(
                settings, apps, app_manager, keyboard, folders, system, vpn,
                windows, ai_client, logger, routines,
            )
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
