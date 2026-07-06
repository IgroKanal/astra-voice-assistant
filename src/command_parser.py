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


@dataclass(frozen=True)
class ParsedCommand:
    type: CommandType
    text: str = ""
    target: str = ""


# v0.9.3: sentinel-таргет для CLOSE_APP, когда команда явно про закрытие
# активного/текущего окна, а не про конкретное приложение из whitelist.
# Обрабатывается в main.py.handle_action фиксированным честным ответом,
# без Alt+F4 и без похода в LLM-router.
UNSUPPORTED_CLOSE_TARGET = "__unsupported_close__"


OPEN_PREFIXES = (
    "открой",
    "открыть",
    "запусти",
    "запустить",
    "включи",
    "зайди",
    "перейди",
)

APP_FIRST_OPEN_PREFIXES = (
    "запусти",
    "запустить",
    "включи",
)

CLOSE_PREFIXES = (
    "закрой",
    "закрыть",
    "выключи",
    "заверши",
    "останови",
)

SEARCH_PREFIXES = (
    "найди",
    "найти",
    "поищи",
    "поищи в интернете",
    "загугли",
    "загуглить",
    "найди в интернете",
    "поиск",
)

TYPE_TEXT_PREFIXES = (
    "напиши",
    "напечатай",
    "введи",
    "впиши",
    "набери",
    "пиши",
)

EXIT_COMMANDS = (
    "стоп",
    "выход",
    "завершить работу",
    "завершись",
    "закройся",
    "пока",
)

TIME_COMMANDS = (
    "сколько время",
    "сколько времени",
    "сколько сейчас время",
    "сколько сейчас времени",
    "какое сейчас время",
    "какое время",
    "сейчас время",
    "который час",
    "текущее время",
)

DATE_COMMANDS = (
    "какое сегодня число",
    "какая сегодня дата",
    "сегодняшняя дата",
    "какое число",
    "какая дата",
)

HELP_COMMANDS = (
    "помощь",
    "команды",
    "список команд",
    "покажи команды",
    "что ты умеешь",
    "что умеешь",
    "что ты можешь",
    "возможности",
    "твои возможности",
    "как пользоваться",
)

SCREENSHOT_COMMANDS = (
    "скриншот",
    "сделай скриншот",
    "сделай снимок экрана",
    "сними экран",
    "сохрани скриншот",
    "сохрани снимок экрана",
)

SYSTEM_INFO_COMMANDS = {
    "статус системы": "summary",
    "информация о системе": "summary",
    "покажи статус системы": "summary",
    "сколько заряд": "battery",
    "заряд": "battery",
    "заряд батареи": "battery",
    "сколько батареи": "battery",
    "сколько памяти": "memory",
    "память": "memory",
    "свободная память": "memory",
    "сколько места": "disk",
    "место на диске": "disk",
    "свободное место": "disk",
}

KEYBOARD_COMMANDS = {
    # Browser tabs / navigation
    "закрой вкладку": "close_tab",
    "закрой текущую вкладку": "close_tab",
    "закрой последнюю вкладку": "close_tab",
    "закрыть вкладку": "close_tab",
    "закройте вкладку": "close_tab",
    "закройте эту вкладку": "close_tab",
    "закроет вкладку": "close_tab",
    "закроет эту вкладку": "close_tab",
    "закрой сайт": "close_tab",
    "закрыть сайт": "close_tab",
    "закрой страницу": "close_tab",
    "закрыть страницу": "close_tab",
    "новая вкладка": "new_tab",
    "открой новую вкладку": "new_tab",
    "создай новую вкладку": "new_tab",
    "верни вкладку": "reopen_tab",
    "верни закрытую вкладку": "reopen_tab",
    "восстанови вкладку": "reopen_tab",
    "следующая вкладка": "next_tab",
    "переключи вкладку": "next_tab",
    "предыдущая вкладка": "previous_tab",
    "прошлая вкладка": "previous_tab",
    "адресная строка": "address_bar",
    "открой адресную строку": "address_bar",
    "выдели адрес": "address_bar",
    "найди на странице": "find_on_page",
    "поиск на странице": "find_on_page",
    "обнови страницу": "refresh",
    "обнови сайт": "refresh",
    "перезагрузи страницу": "refresh",
    "перезагрузи сайт": "refresh",
    "назад": "browser_back",
    "вернись назад": "browser_back",
    "вперед": "browser_forward",
    "перейди вперед": "browser_forward",
    "инкогнито": "incognito",
    "открой инкогнито": "incognito",
    "полный экран": "fullscreen",
    "полноэкранный режим": "fullscreen",
    # Clipboard / edit
    "скопируй": "copy",
    "копировать": "copy",
    "вставь": "paste",
    "вставить": "paste",
    "выдели все": "select_all",
    "выделить все": "select_all",
    "сохрани": "save",
    "сохранить": "save",
    # Keys
    "нажми enter": "enter",
    "нажми энтер": "enter",
    "энтер": "enter",
    "escape": "escape",
    "esc": "escape",
    "нажми escape": "escape",
    "нажми esc": "escape",
    "удали": "backspace",
    "backspace": "backspace",
    "пробел": "space",
    "нажми пробел": "space",
    "страница вниз": "page_down",
    "прокрути вниз": "page_down",
    "страница вверх": "page_up",
    "прокрути вверх": "page_up",
    "в начало": "home",
    "в конец": "end",
    # Volume
    "громче": "volume_up",
    "сделай громче": "volume_up",
    "увеличь громкость": "volume_up",
    "тише": "volume_down",
    "сделай тише": "volume_down",
    "уменьши громкость": "volume_down",
    "переключи звук": "volume_mute",
    "звук": "volume_mute",
}

SITE_NAMES = (
    # AI
    "чатгпт",
    "чат гпт",
    "чат джипити",
    "чат gpt",
    "чатт gpt",
    "чат кпт",
    "чатт джипити",
    "чат жпт",
    "чат джи пи ти",
    "chad gpt",
    "джипити",
    "гпт",
    "gpt",
    "chatgpt",
    "chat gpt",
    "openai",
    "опен ai",
    "опенэйай",
    "claude",
    "клоуд",
    "клауд",
    "клод",
    "клодт",
    "клот",
    "кло",
    "клоу",
    "грау",
    "гро",
    "grow",
    "gro",
    "cloud",
    "clod",
    "cloth",
    "clot",
    "chloe",
    "klo",
    "anthropic",
    "антропик",
    "gemini",
    "джемини",
    "гемини",
    "perplexity",
    "перплексити",
    "copilot",
    "копайлот",
    "huggingface",
    "hugging face",
    "хаггинг фейс",
    # Dev
    "github",
    "гитхаб",
    "gitlab",
    "гитлаб",
    "stackoverflow",
    "stack overflow",
    "стак оверфлоу",
    "pypi",
    "пайпи",
    "npm",
    "нпм",
    "mdn",
    "docker hub",
    "докер хаб",
    # Common
    "ютуб",
    "ютюб",
    "youtube",
    "гугл",
    "google",
    "яндекс",
    "yandex",
    "вк",
    "вконтакте",
    "telegram web",
    "телеграм веб",
    "телега веб",
    "gmail",
    "гмейл",
    "почта gmail",
    "drive",
    "google drive",
    "гугл диск",
    "docs",
    "google docs",
    "гугл документы",
    "sheets",
    "google sheets",
    "гугл таблицы",
    "calendar",
    "google calendar",
    "гугл календарь",
    "переводчик",
    "google translate",
    "гугл переводчик",
    "translate",
    "wikipedia",
    "википедия",
    "reddit",
    "реддит",
    "twitch",
    "твич",
    "discord",
    "дискорд",
    "spotify",
    "спотифай",
    "figma",
    "фигма",
    "notion",
    "ноушен",
    "whatsapp",
    "ватсап",
    "ozon",
    "озон",
    "wildberries",
    "вайлдберриз",
    "market",
    "маркет",
    "яндекс маркет",
    "авито",
    "avito",
    "2гис",
    "два гис",
    "2gis",
    "кинопоиск",
    "kinopoisk",
    "яндекс музыка",
    "music yandex",
    "hh",
    "headhunter",
    "хэдхантер",
    "mail",
    "mail ru",
    "мейл ру",
    "rutube",
    "рутуб",
)

APP_LIKE_NAMES = (
    "телеграм",
    "телега",
    "telegram",
    "тг",
    "tg",
    "код",
    "vs code",
    "vs cod",
    "vs код",
    "vs кот",
    "vscode",
    "visual studio code",
    "браузер",
    "хром",
    "chrome",
    "edge",
)

FOLDER_NAMES = (
    "загрузки",
    "загрузок",
    "скачанные",
    "downloads",
    "рабочий стол",
    "desktop",
    "документы",
    "documents",
    "изображения",
    "картинки",
    "pictures",
    "музыка",
    "music",
    "видео",
    "videos",
    "проект",
    "проекта",
    "проект астра",
    "астра проект",
    "папка проекта",
    "папка астра",
)

COMMAND_HINTS = (
    *OPEN_PREFIXES,
    *CLOSE_PREFIXES,
    *SEARCH_PREFIXES,
    *TYPE_TEXT_PREFIXES,
    *TIME_COMMANDS,
    *DATE_COMMANDS,
    *HELP_COMMANDS,
    *EXIT_COMMANDS,
    *SCREENSHOT_COMMANDS,
    *SYSTEM_INFO_COMMANDS.keys(),
    *KEYBOARD_COMMANDS.keys(),
    "открой сайт",
    "закрой сайт",
    "открой папку",
    # STT may produce phrases like "обнови страница ютуб" instead of
    # the exact command "обнови страницу". These verb hints keep refresh
    # phrases in command-handling flow instead of general LLM chat.
    "обнови",
    "обновить",
    "перезагрузи",
    "перезагрузить",
    "закройте",
    "закроет",
    "закрывайте",
)

_FILLER_WORDS = (
    "пожалуйста",
    "пж",
    "ну",
)

_whitespace_re = re.compile(r"\s+")
_punctuation_re = re.compile(r"[,.!?;:()\[\]{}\"'«»\-]")


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


def is_command_like_text(text: str) -> bool:
    """
    Проверяет, похожа ли фраза на команду.

    Использует границы слов, чтобы "приоткрой" не считалось совпадением
    с командой "открой".
    """
    normalized = normalize_text(text)
    if not normalized:
        return False

    hints = sorted({normalize_text(item) for item in COMMAND_HINTS}, key=len, reverse=True)
    for hint in hints:
        if not hint:
            continue

        pattern = rf"(?<!\w){re.escape(hint)}(?!\w)"
        if re.search(pattern, normalized):
            return True

    return False


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


def _parse_keyboard_shortcut(normalized: str) -> ParsedCommand | None:
    if normalized in KEYBOARD_COMMANDS:
        return ParsedCommand(
            CommandType.KEYBOARD_SHORTCUT,
            text=normalized,
            target=KEYBOARD_COMMANDS[normalized],
        )

    words = normalized.split()
    first = words[0] if words else ""
    second = words[1] if len(words) > 1 else ""

    # Фразы с уточнением сайта всё равно являются локальной командой
    # для активной вкладки, а не поводом отправлять запрос в LLM-router.
    # STT часто меняет падеж: "страницу" -> "страница".
    refresh_verbs = {"обнови", "обновить", "перезагрузи", "перезагрузить"}
    refresh_target = " ".join(words[1:]).strip()
    if first in refresh_verbs and (
        len(words) == 1
        or second.startswith("стран")
        or second.startswith("сайт")
        or _is_site_target(refresh_target)
    ):
        return ParsedCommand(
            CommandType.KEYBOARD_SHORTCUT,
            text=normalized,
            target="refresh",
        )

    # STT может распознать "закрой вкладку" как "закроет вкладку" или
    # "закройте вкладку". Если во фразе есть корень вкладки и глагол закрытия,
    # это безопасная локальная команда Ctrl+W.
    close_stems = ("закрой", "закрыть", "закройте", "закроет", "закрывай")
    if "вкладк" in normalized and any(stem in normalized for stem in close_stems):
        return ParsedCommand(
            CommandType.KEYBOARD_SHORTCUT,
            text=normalized,
            target="close_tab",
        )

    prefix_commands = {
        "закрой вкладку ": "close_tab",
        "закрой сайт ": "close_tab",
        "закрой страницу ": "close_tab",
    }
    for prefix, target in prefix_commands.items():
        if normalized.startswith(prefix):
            return ParsedCommand(
                CommandType.KEYBOARD_SHORTCUT,
                text=normalized,
                target=target,
            )

    return None

def _parse_targeted_type_text(normalized: str) -> ParsedCommand | None:
    """
    Понимает фразы вида:
    - "в блокнот напиши привет"
    - "в блокноте напиши привет"
    - "напиши в блокнот привет"

    Действие всё равно безопасное: оно требует wake phrase в main.py.
    """
    app_names = ("блокнот", "notepad", "телеграм", "telegram", "тг", "код", "vs code")

    for app_name in app_names:
        for intro in (f"в {app_name} ", f"в {app_name}е "):
            if normalized.startswith(intro):
                rest = normalized.removeprefix(intro).strip()
                for prefix in TYPE_TEXT_PREFIXES:
                    if rest == prefix:
                        return ParsedCommand(
                            CommandType.TYPE_TEXT,
                            text=normalized,
                            target=f"app={app_name};text=",
                        )
                    if rest.startswith(prefix + " "):
                        text = rest.removeprefix(prefix).strip()
                        return ParsedCommand(
                            CommandType.TYPE_TEXT,
                            text=normalized,
                            target=f"app={app_name};text={text}",
                        )

        for prefix in TYPE_TEXT_PREFIXES:
            marker = f"{prefix} в {app_name} "
            if normalized.startswith(marker):
                text = normalized.removeprefix(marker).strip()
                return ParsedCommand(
                    CommandType.TYPE_TEXT,
                    text=normalized,
                    target=f"app={app_name};text={text}",
                )

    return None

def _parse_type_text(normalized: str) -> ParsedCommand | None:
    for prefix in TYPE_TEXT_PREFIXES:
        if normalized == prefix:
            return ParsedCommand(CommandType.TYPE_TEXT, text=normalized, target="")
        if normalized.startswith(prefix + " "):
            target = normalized.removeprefix(prefix).strip()
            return ParsedCommand(CommandType.TYPE_TEXT, text=normalized, target=target)

    return None


def _strip_folder_words(value: str) -> str:
    value = normalize_text(value)
    for word in ("папку", "папка", "папке"):
        if value.startswith(word + " "):
            return value.removeprefix(word).strip()
    return value


def _strip_site_words(value: str) -> str:
    value = normalize_text(value)
    for word in ("сайт", "страницу", "страница"):
        if value.startswith(word + " "):
            return value.removeprefix(word).strip()
    return value


def _is_folder_target(target: str) -> bool:
    clean = _strip_folder_words(target)
    return clean in FOLDER_NAMES


def _is_site_target(target: str) -> bool:
    clean = _strip_site_words(target)
    return clean in SITE_NAMES or "." in clean


def _is_app_like_target(target: str) -> bool:
    clean = normalize_text(target)
    return clean in APP_LIKE_NAMES


def _parse_system_info(normalized: str) -> ParsedCommand | None:
    if normalized in SYSTEM_INFO_COMMANDS:
        return ParsedCommand(
            CommandType.SYSTEM_INFO,
            text=normalized,
            target=SYSTEM_INFO_COMMANDS[normalized],
        )
    return None


def parse_command_text(text: str) -> ParsedCommand:
    """Определяет тип команды уже без wake phrase."""
    normalized = remove_filler_words(text)
    if not normalized:
        return ParsedCommand(CommandType.EMPTY)

    if normalized in HELP_COMMANDS:
        return ParsedCommand(CommandType.HELP, text=normalized)

    # Частые голосовые команды без явного "открой".
    # В голосе пользователь часто говорит просто "диспетчер задач".
    if normalized in {
        "диспетчер",
        "диспетчер задач",
        "диспетчер зада",
        "диспетчер задо",
        "диспетчер zada",
        "диспетчер zado",
        "task manager",
        "таск менеджер",
    }:
        return ParsedCommand(CommandType.OPEN_APP, text=normalized, target="диспетчер задач")

    # v0.8.3: не делаем "включи/выключи звук" через mute-toggle,
    # потому что без чтения реального состояния это может дать обратный эффект.
    if normalized in {"включи звук", "выключи звук", "без звука"}:
        return ParsedCommand(CommandType.ASK_LLM, text=normalized)

    # v0.9.3 hotfix: раньше это уходило как ASK_LLM, но is_command_like_text
    # всё равно матчил "закрой" как хинт, и фраза улетала в LLM-router, где
    # молча гасла (confidence=0, router_unknown_guard). Теперь это прямая
    # локальная команда с sentinel-таргетом — router вообще не вызывается,
    # Alt+F4 не выполняется, пользователь получает честный ответ.
    if normalized in {
        "закрой окно",
        "закрыть окно",
        "закрой это окно",
        "закрой активное окно",
        "закрой текущее окно",
        "закрой данное окно",
    }:
        return ParsedCommand(CommandType.CLOSE_APP, text=normalized, target=UNSUPPORTED_CLOSE_TARGET)

    keyboard = _parse_keyboard_shortcut(normalized)
    if keyboard is not None:
        return keyboard

    targeted_type_text = _parse_targeted_type_text(normalized)
    if targeted_type_text is not None:
        return targeted_type_text

    type_text = _parse_type_text(normalized)
    if type_text is not None:
        return type_text

    system_info = _parse_system_info(normalized)
    if system_info is not None:
        return system_info

    if normalized in SCREENSHOT_COMMANDS:
        return ParsedCommand(CommandType.SCREENSHOT, text=normalized)

    if normalized in EXIT_COMMANDS:
        return ParsedCommand(CommandType.EXIT, text=normalized)

    if normalized in TIME_COMMANDS:
        return ParsedCommand(CommandType.GET_TIME, text=normalized)

    if normalized in DATE_COMMANDS:
        return ParsedCommand(CommandType.GET_DATE, text=normalized)

    for prefix in SEARCH_PREFIXES:
        if normalized == prefix:
            return ParsedCommand(CommandType.WEB_SEARCH, text=normalized, target="")
        if normalized.startswith(prefix + " "):
            target = normalized.removeprefix(prefix).strip()
            return ParsedCommand(CommandType.WEB_SEARCH, text=normalized, target=target)

    for prefix in OPEN_PREFIXES:
        if normalized == prefix:
            return ParsedCommand(CommandType.OPEN_APP, text=normalized, target="")
        if normalized.startswith(prefix + " "):
            target = normalized.removeprefix(prefix).strip()

            if _is_folder_target(target):
                return ParsedCommand(
                    CommandType.OPEN_FOLDER,
                    text=normalized,
                    target=_strip_folder_words(target),
                )

            # "запусти телеграм" — приложение, "открой телеграм веб" — сайт.
            if prefix in APP_FIRST_OPEN_PREFIXES and _is_app_like_target(target):
                return ParsedCommand(CommandType.OPEN_APP, text=normalized, target=target)

            if _is_site_target(target):
                return ParsedCommand(
                    CommandType.OPEN_URL,
                    text=normalized,
                    target=_strip_site_words(target),
                )

            return ParsedCommand(CommandType.OPEN_APP, text=normalized, target=target)

    for prefix in CLOSE_PREFIXES:
        if normalized == prefix:
            return ParsedCommand(CommandType.CLOSE_APP, text=normalized, target="")
        if normalized.startswith(prefix + " "):
            target = normalized.removeprefix(prefix).strip()
            if target in SITE_NAMES or any(
                word in target for word in ("сайт", "вкладк", "страниц")
            ):
                return ParsedCommand(
                    CommandType.KEYBOARD_SHORTCUT,
                    text=normalized,
                    target="close_tab",
                )
            return ParsedCommand(CommandType.CLOSE_APP, text=normalized, target=target)

    return ParsedCommand(CommandType.ASK_LLM, text=normalized)
