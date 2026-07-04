from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import quote_plus


class ActionType(str, Enum):
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    OPEN_URL = "open_url"
    WEB_SEARCH = "web_search"
    GET_TIME = "get_time"
    GET_DATE = "get_date"
    ASK_LLM = "ask_llm"
    EXIT = "exit"
    EMPTY = "empty"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AssistantAction:
    type: ActionType
    text: str = ""
    target: str = ""
    query: str = ""
    url: str = ""
    confidence: float = 1.0
    source: str = "local"
    reason: str = ""


_SITE_ALIASES = {
    "ютуб": "https://www.youtube.com",
    "ютюб": "https://www.youtube.com",
    "youtube": "https://www.youtube.com",
    "гугл": "https://www.google.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
    "гитхаб": "https://github.com",
    "вк": "https://vk.com",
    "вконтакте": "https://vk.com",
    "яндекс": "https://ya.ru",
    "yandex": "https://ya.ru",
    "чатгпт": "https://chatgpt.com",
    "чат гпт": "https://chatgpt.com",
    "chatgpt": "https://chatgpt.com",
    "openai": "https://openai.com",
}

_DOMAIN_RE = re.compile(r"^[a-z0-9а-яё.-]+\.[a-zа-яё]{2,}(/.*)?$", re.IGNORECASE)


def known_site_aliases() -> list[str]:
    """Возвращает известные названия сайтов для подсказки роутеру."""
    return sorted(_SITE_ALIASES)


def normalize_url_or_site(value: str) -> str:
    """Преобразует название сайта или домен в URL."""
    clean = value.strip().lower()
    if not clean:
        return ""

    if clean in _SITE_ALIASES:
        return _SITE_ALIASES[clean]

    if clean.startswith(("http://", "https://")):
        return clean

    if _DOMAIN_RE.match(clean):
        return f"https://{clean}"

    return f"https://www.google.com/search?q={quote_plus(value)}"


def google_search_url(query: str) -> str:
    """Возвращает URL поиска Google."""
    return f"https://www.google.com/search?q={quote_plus(query.strip())}"


def short_confirmation(action: AssistantAction) -> str:
    """Короткие ответы уменьшают задержку TTS."""
    if action.type == ActionType.OPEN_APP:
        return "Открываю."
    if action.type == ActionType.CLOSE_APP:
        return "Закрываю."
    if action.type == ActionType.OPEN_URL:
        return "Открываю сайт."
    if action.type == ActionType.WEB_SEARCH:
        return "Ищу."
    if action.type == ActionType.GET_TIME:
        return "Сейчас скажу."
    if action.type == ActionType.GET_DATE:
        return "Сейчас скажу."
    if action.type == ActionType.EXIT:
        return "Завершаю работу."
    return "Готово."
