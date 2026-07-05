from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import quote_plus


class ActionType(str, Enum):
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    OPEN_URL = "open_url"
    OPEN_FOLDER = "open_folder"
    WEB_SEARCH = "web_search"
    GET_TIME = "get_time"
    GET_DATE = "get_date"
    KEYBOARD_SHORTCUT = "keyboard_shortcut"
    TYPE_TEXT = "type_text"
    SCREENSHOT = "screenshot"
    SYSTEM_INFO = "system_info"
    HELP = "help"
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
    # AI
    "чатгпт": "https://chatgpt.com",
    "чат гпт": "https://chatgpt.com",
    "чат джипити": "https://chatgpt.com",
    "чат gpt": "https://chatgpt.com",
    "чатт gpt": "https://chatgpt.com",
    "чат кпт": "https://chatgpt.com",
    "джипити": "https://chatgpt.com",
    "гпт": "https://chatgpt.com",
    "gpt": "https://chatgpt.com",
    "chatgpt": "https://chatgpt.com",
    "chat gpt": "https://chatgpt.com",
    "openai": "https://openai.com",
    "опен ai": "https://openai.com",
    "опенэйай": "https://openai.com",
    "claude": "https://claude.ai",
    "клоуд": "https://claude.ai",
    "клауд": "https://claude.ai",
    "клод": "https://claude.ai",
    "клодт": "https://claude.ai",
    "клот": "https://claude.ai",
    "кло": "https://claude.ai",
    "anthropic": "https://www.anthropic.com",
    "антропик": "https://www.anthropic.com",
    "gemini": "https://gemini.google.com",
    "джемини": "https://gemini.google.com",
    "гемини": "https://gemini.google.com",
    "perplexity": "https://www.perplexity.ai",
    "перплексити": "https://www.perplexity.ai",
    "copilot": "https://copilot.microsoft.com",
    "копайлот": "https://copilot.microsoft.com",
    "huggingface": "https://huggingface.co",
    "hugging face": "https://huggingface.co",
    "хаггинг фейс": "https://huggingface.co",

    # Dev
    "github": "https://github.com",
    "гитхаб": "https://github.com",
    "gitlab": "https://gitlab.com",
    "гитлаб": "https://gitlab.com",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "стак оверфлоу": "https://stackoverflow.com",
    "pypi": "https://pypi.org",
    "пайпи": "https://pypi.org",
    "npm": "https://www.npmjs.com",
    "нпм": "https://www.npmjs.com",
    "mdn": "https://developer.mozilla.org",
    "docker hub": "https://hub.docker.com",
    "докер хаб": "https://hub.docker.com",

    # Search / common
    "ютуб": "https://www.youtube.com",
    "ютюб": "https://www.youtube.com",
    "youtube": "https://www.youtube.com",
    "гугл": "https://www.google.com",
    "google": "https://www.google.com",
    "яндекс": "https://ya.ru",
    "yandex": "https://ya.ru",
    "вк": "https://vk.com",
    "вконтакте": "https://vk.com",
    "telegram web": "https://web.telegram.org",
    "телеграм веб": "https://web.telegram.org",
    "телега веб": "https://web.telegram.org",
    "gmail": "https://mail.google.com",
    "гмейл": "https://mail.google.com",
    "почта gmail": "https://mail.google.com",
    "drive": "https://drive.google.com",
    "google drive": "https://drive.google.com",
    "гугл диск": "https://drive.google.com",
    "docs": "https://docs.google.com",
    "google docs": "https://docs.google.com",
    "гугл документы": "https://docs.google.com",
    "sheets": "https://sheets.google.com",
    "google sheets": "https://sheets.google.com",
    "гугл таблицы": "https://sheets.google.com",
    "calendar": "https://calendar.google.com",
    "google calendar": "https://calendar.google.com",
    "гугл календарь": "https://calendar.google.com",
    "переводчик": "https://translate.google.com",
    "google translate": "https://translate.google.com",
    "гугл переводчик": "https://translate.google.com",
    "translate": "https://translate.google.com",
    "wikipedia": "https://www.wikipedia.org",
    "википедия": "https://www.wikipedia.org",
    "reddit": "https://www.reddit.com",
    "реддит": "https://www.reddit.com",
    "twitch": "https://www.twitch.tv",
    "твич": "https://www.twitch.tv",
    "discord": "https://discord.com/app",
    "дискорд": "https://discord.com/app",
    "spotify": "https://open.spotify.com",
    "спотифай": "https://open.spotify.com",
    "figma": "https://www.figma.com",
    "фигма": "https://www.figma.com",
    "notion": "https://www.notion.so",
    "ноушен": "https://www.notion.so",
    "whatsapp": "https://web.whatsapp.com",
    "ватсап": "https://web.whatsapp.com",
    "ozon": "https://www.ozon.ru",
    "озон": "https://www.ozon.ru",
    "wildberries": "https://www.wildberries.ru",
    "вайлдберриз": "https://www.wildberries.ru",
    "market": "https://market.yandex.ru",
    "маркет": "https://market.yandex.ru",
    "яндекс маркет": "https://market.yandex.ru",
    "avito": "https://www.avito.ru",
    "авито": "https://www.avito.ru",
    "2gis": "https://2gis.ru",
    "2гис": "https://2gis.ru",
    "два гис": "https://2gis.ru",
    "kinopoisk": "https://www.kinopoisk.ru",
    "кинопоиск": "https://www.kinopoisk.ru",
    "яндекс музыка": "https://music.yandex.ru",
    "music yandex": "https://music.yandex.ru",
    "hh": "https://hh.ru",
    "headhunter": "https://hh.ru",
    "хэдхантер": "https://hh.ru",
    "mail": "https://mail.ru",
    "mail ru": "https://mail.ru",
    "мейл ру": "https://mail.ru",
    "rutube": "https://rutube.ru",
    "рутуб": "https://rutube.ru",
}

# Дополнительные STT-алиасы. Они вынесены отдельно, чтобы было проще
# расширять словарь без риска сломать основной блок.
_SITE_ALIASES.update({
    "клоу": "https://claude.ai",
    "грау": "https://claude.ai",
    "гро": "https://claude.ai",
    "grow": "https://claude.ai",
    "gro": "https://claude.ai",
    "cloud": "https://claude.ai",
    "clod": "https://claude.ai",
    "cloth": "https://claude.ai",
    "clot": "https://claude.ai",
    "chloe": "https://claude.ai",
    "klo": "https://claude.ai",
    "чатт джипити": "https://chatgpt.com",
    "чат жпт": "https://chatgpt.com",
    "чат джи пи ти": "https://chatgpt.com",
    "chad gpt": "https://chatgpt.com",
})

_DOMAIN_RE = re.compile(r"^[a-z0-9а-яё.-]+\.[a-zа-яё]{2,}(/.*)?$", re.IGNORECASE)


def _strip_site_words(value: str) -> str:
    clean = value.strip().lower().replace("ё", "е")
    for word in ("сайт", "страницу", "страница"):
        if clean.startswith(word + " "):
            return clean.removeprefix(word).strip()
    return clean


def _clean_alias(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower().replace("ё", "е"))


def known_site_aliases() -> list[str]:
    """Возвращает известные названия сайтов для подсказки роутеру."""
    return sorted(_SITE_ALIASES)


def find_site_url(value: str, cutoff: float = 0.72) -> str:
    """Ищет сайт по точному, частичному или fuzzy совпадению."""
    clean = _clean_alias(value)
    if not clean:
        return ""

    if clean in _SITE_ALIASES:
        return _SITE_ALIASES[clean]

    for alias, url in _SITE_ALIASES.items():
        alias_clean = _clean_alias(alias)
        if clean == alias_clean:
            return url

        if len(clean) >= 4 and (clean in alias_clean or alias_clean in clean):
            return url

    if len(clean) < 3:
        return ""

    aliases = [_clean_alias(a) for a in _SITE_ALIASES]
    match = difflib.get_close_matches(clean, aliases, n=1, cutoff=cutoff)
    if match:
        for alias, url in _SITE_ALIASES.items():
            if _clean_alias(alias) == match[0]:
                return url

    return ""


def normalize_url_or_site(value: str) -> str:
    """Преобразует название сайта или домен в URL."""
    clean = _strip_site_words(value)
    if not clean:
        return ""

    site_url = find_site_url(clean)
    if site_url:
        return site_url

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
    if action.type == ActionType.OPEN_FOLDER:
        return "Открываю папку."
    if action.type == ActionType.WEB_SEARCH:
        return "Ищу."
    if action.type == ActionType.KEYBOARD_SHORTCUT:
        return "Готово."
    if action.type == ActionType.TYPE_TEXT:
        return "Пишу."
    if action.type == ActionType.SCREENSHOT:
        return "Скриншот."
    if action.type == ActionType.SYSTEM_INFO:
        return "Сейчас скажу."
    if action.type == ActionType.HELP:
        return "Показываю команды."
    if action.type == ActionType.GET_TIME:
        return "Сейчас скажу."
    if action.type == ActionType.GET_DATE:
        return "Сейчас скажу."
    if action.type == ActionType.EXIT:
        return "Завершаю работу."
    return "Готово."
