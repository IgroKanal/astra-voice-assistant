from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class CommandType(str, Enum):
    NO_WAKE = "no_wake"
    WAKE_ONLY = "wake_only"
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    OPEN_URL = "open_url"
    WEB_SEARCH = "web_search"
    GET_TIME = "get_time"
    GET_DATE = "get_date"
    ASK_LLM = "ask_llm"
    EXIT = "exit"
    EMPTY = "empty"


@dataclass(frozen=True)
class ParsedCommand:
    type: CommandType
    text: str = ""
    target: str = ""


_OPEN_PREFIXES = (
    "открой",
    "открыть",
    "запусти",
    "запустить",
    "включи",
)

_CLOSE_PREFIXES = (
    "закрой",
    "закрыть",
    "выключи",
    "заверши",
    "останови",
)

_SEARCH_PREFIXES = (
    "найди",
    "найти",
    "поищи",
    "поищи в интернете",
    "загугли",
    "загуглить",
)

_EXIT_COMMANDS = (
    "стоп",
    "выход",
    "завершить работу",
    "завершись",
    "закройся",
    "пока",
)

_TIME_COMMANDS = (
    "сколько время",
    "сколько времени",
    "который час",
    "текущее время",
)

_DATE_COMMANDS = (
    "какое сегодня число",
    "какая сегодня дата",
    "сегодняшняя дата",
    "какое число",
    "какая дата",
)

_SITE_NAMES = (
    "ютуб",
    "ютюб",
    "youtube",
    "гугл",
    "google",
    "github",
    "гитхаб",
    "вк",
    "вконтакте",
    "яндекс",
    "yandex",
    "чатгпт",
    "чат гпт",
    "чат джипити",
    "джипити",
    "гпт",
    "chatgpt",
    "chat gpt",
    "openai",
)

_FILLER_WORDS = (
    "пожалуйста",
    "пж",
    "ну",
)


_whitespace_re = re.compile(r"\s+")
_punctuation_re = re.compile(r"[,.!?;:()\[\]{}\"'«»]")


def normalize_text(text: str) -> str:
    """Упрощает текст для сравнения команд."""
    text = text.lower().replace("ё", "е")
    text = _punctuation_re.sub(" ", text)
    text = _whitespace_re.sub(" ", text)
    return text.strip()


def remove_filler_words(text: str) -> str:
    normalized = normalize_text(text)
    words = [word for word in normalized.split() if word not in _FILLER_WORDS]
    return " ".join(words)


def extract_command_after_wake(text: str, wake_phrases: list[str]) -> ParsedCommand:
    """
    Ищет фразу активации и возвращает текст после неё.

    Пример:
    "Астра, открой блокнот" -> "открой блокнот".
    "Астра" -> WAKE_ONLY.
    "открой блокнот" -> NO_WAKE.
    """
    normalized = normalize_text(text)
    if not normalized:
        return ParsedCommand(CommandType.EMPTY)

    wake_phrases_normalized = sorted(
        {normalize_text(phrase) for phrase in wake_phrases if normalize_text(phrase)},
        key=len,
        reverse=True,
    )

    for phrase in wake_phrases_normalized:
        pattern = rf"(^|\s){re.escape(phrase)}(\s|$)"
        match = re.search(pattern, normalized)
        if not match:
            continue

        command_text = normalized[match.end():].strip()
        if not command_text:
            return ParsedCommand(CommandType.WAKE_ONLY)
        return parse_command_text(command_text)

    return ParsedCommand(CommandType.NO_WAKE, text=normalized)


def parse_command_text(text: str) -> ParsedCommand:
    """Определяет тип команды уже без wake phrase."""
    normalized = remove_filler_words(text)
    if not normalized:
        return ParsedCommand(CommandType.EMPTY)

    if normalized in _EXIT_COMMANDS:
        return ParsedCommand(CommandType.EXIT, text=normalized)

    if normalized in _TIME_COMMANDS:
        return ParsedCommand(CommandType.GET_TIME, text=normalized)

    if normalized in _DATE_COMMANDS:
        return ParsedCommand(CommandType.GET_DATE, text=normalized)

    for prefix in _SEARCH_PREFIXES:
        if normalized == prefix:
            return ParsedCommand(CommandType.WEB_SEARCH, text=normalized, target="")
        if normalized.startswith(prefix + " "):
            target = normalized.removeprefix(prefix).strip()
            return ParsedCommand(CommandType.WEB_SEARCH, text=normalized, target=target)

    for prefix in _OPEN_PREFIXES:
        if normalized == prefix:
            return ParsedCommand(CommandType.OPEN_APP, text=normalized, target="")
        if normalized.startswith(prefix + " "):
            target = normalized.removeprefix(prefix).strip()
            if target in _SITE_NAMES or "." in target:
                return ParsedCommand(CommandType.OPEN_URL, text=normalized, target=target)
            return ParsedCommand(CommandType.OPEN_APP, text=normalized, target=target)

    for prefix in _CLOSE_PREFIXES:
        if normalized == prefix:
            return ParsedCommand(CommandType.CLOSE_APP, text=normalized, target="")
        if normalized.startswith(prefix + " "):
            target = normalized.removeprefix(prefix).strip()
            return ParsedCommand(CommandType.CLOSE_APP, text=normalized, target=target)

    return ParsedCommand(CommandType.ASK_LLM, text=normalized)
