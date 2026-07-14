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
    VPN_CONTROL = "vpn_control"
    WINDOW_CONTROL = "window_control"
    VOICE_FEEDBACK = "voice_feedback"
    ROUTINE = "routine"
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
UNSUPPORTED_OPEN_TARGET = "__unsupported_open__"
AMBIGUOUS_CHAT_TARGET = "__ambiguous_chat__"
MIXED_COMMAND_TARGET = "__mixed_command__"
AMBIGUOUS_MUSIC_TARGET = "__ambiguous_music__"
UNRESOLVED_CONTEXT_TARGET = "__context_unavailable__"


OPEN_PREFIXES = (
    "открой",
    "открыть",
    # Observed STT substitutions for the imperative "открой". Keeping them
    # in the local parser prevents an action-like phrase from reaching the
    # conversation LLM and producing a false success claim.
    "откроется",
    "откроеться",
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


VOICE_FEEDBACK_COMMANDS = {
    "repeat_last": (
        "повтори",
        "повтори ответ",
        "повтори еще раз",
        "повтори ещё раз",
        "повтори что сказала",
        "что ты сказала",
        "скажи еще раз",
        "скажи ещё раз",
        "повтори последний ответ",
        "последний ответ",
    ),
    "last_heard": (
        "что ты услышала",
        "что услышала",
        "что ты распознала",
        "что распознала",
        "что я сказал",
        "что я сказала",
        "последняя фраза",
        "что было распознано",
        "что ты услышал",
        "что услышал",
        "что я говорил",
        "какая последняя фраза",
    ),
}

VPN_CONTROL_ACTIONS = {
    "connect": "connect",
    "disconnect": "disconnect",
    "status": "status",
}

VPN_WORDS = (
    "vpn",
    "впн",
    "впнку",
    "в п н",
    "ви пи эн",
    "випиэн",
    "амнезия",
    "амнезия впн",
    "amnezia",
    "amneziawg",
    "wireguard",
    "вайргард",
)

VPN_CONNECT_WORDS = (
    "включи",
    "включить",
    "подключи",
    "подключить",
    "запусти",
    "запустить",
    "активируй",
    "активировать",
    "соедини",
)

VPN_DISCONNECT_WORDS = (
    "выключи",
    "выключить",
    "отключи",
    "отключить",
    "останови",
    "остановить",
    "отруби",
    "выруби",
    "разорви",
)

VPN_STATUS_WORDS = (
    "статус",
    "status",
    "statues",
    "проверь",
    "проверить",
    "работает",
    "включен",
    "включен",
    "подключен",
    "подключен",
    "состояние",
)

WINDOW_LIST_COMMANDS = (
    "какие окна открыты",
    "какие открыты окна",
    "что открыто",
    "покажи окна",
    "покажи открытые окна",
    "список окон",
    "открытые окна",
    "какие приложения открыты",
    "что сейчас открыто",
)

ACTIVE_WINDOW_COMMANDS = (
    "активное окно",
    "какое окно активно",
    "что активно",
    "текущее окно",
    "какое сейчас окно",
    "где я сейчас",
)


WINDOW_STATE_COMMANDS = {
    "minimize": (
        "сверни окно",
        "сверни активное окно",
        "сверни текущее окно",
        "сверни",
    ),
    "maximize": (
        "разверни окно",
        "разверни активное окно",
        "разверни текущее окно",
        "разверни",
    ),
    "show_desktop": (
        "покажи рабочий стол",
        "сверни все окна",
        "рабочий стол",
    ),
    "previous": (
        "вернись обратно",
        "переключись обратно",
        "предыдущее окно",
        "верни предыдущее окно",
    ),
}

WINDOW_FOCUS_PREFIXES = (
    "переключись на",
    "переключись no",
    "переключись в",
    "переключиться на",
    "переключиться no",
    "перейди в",
    "перейди no",
    "перейти в",
    "сфокусируй",
    "сфокусируйся на",
    "активируй окно",
    "активировать окно",
    "покажи окно",
    "вернись на",
    "вернись в",
)

WINDOW_CONTROL_HINTS = (
    *WINDOW_LIST_COMMANDS,
    *ACTIVE_WINDOW_COMMANDS,
    *WINDOW_FOCUS_PREFIXES,
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
    "статус интернета": "internet",
    "интернет": "internet",
    "проверь интернет": "internet",
    "работает интернет": "internet",
    "status internet": "internet",
    "internet status": "internet",
    "status inter": "internet",
    "status enter": "internet",
    "статус inter": "internet",
    "статус интер": "internet",
    "статус энтер": "internet",
    "интернет статус": "internet",
    "проверка интернета": "internet",
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
    "отправь нажми enter": "enter",
    "отправь нажми энтер": "enter",
    "отправь enter": "enter",
    "отправь энтер": "enter",
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
    "покажи рабочий стол": "show_desktop",
    "рабочий стол": "show_desktop",
    "сверни все окна": "show_desktop",
    "открой загрузки браузера": "browser_downloads",
    "загрузки браузера": "browser_downloads",
    "история загрузок": "browser_downloads",
    "открой историю браузера": "browser_history",
    "история браузера": "browser_history",
    "новое окно браузера": "browser_new_window",
    "открой новое окно браузера": "browser_new_window",
    "создай новое окно браузера": "browser_new_window",
    "открой приватное окно": "incognito",
    "приватное окно": "incognito",
    "приватная вкладка": "incognito",
    "открой приватную вкладку": "incognito",
    "открой буфер обмена": "clipboard_history",
    "открой буфер up": "clipboard_history",
    "открой буфер ап": "clipboard_history",
    "открой буфер об": "clipboard_history",
    "открой буфер оп": "clipboard_history",
    "открой буфер ab": "clipboard_history",
    "буфер обмена": "clipboard_history",
    "история буфера": "clipboard_history",
    "история буфера обмена": "clipboard_history",
    # Volume
    "громче": "volume_up",
    "сделай громче": "volume_up",
    "увеличь громкость": "volume_up",
    "тише": "volume_down",
    "сделай тише": "volume_down",
    "уменьши громкость": "volume_down",
    "переключи звук": "volume_mute",
    "звук": "volume_mute",
    # Global media keys: they work with the active media session and do not
    # type text or execute a process/shell command.
    "пауза": "media_play_pause",
    "поставь на паузу": "media_play_pause",
    "музыку на паузу": "media_play_pause",
    "продолжи музыку": "media_play_pause",
    "возобнови музыку": "media_play_pause",
    "следующий трек": "media_next",
    "следующая песня": "media_next",
    "переключи трек": "media_next",
    "предыдущий трек": "media_previous",
    "предыдущая песня": "media_previous",
    "останови музыку": "media_stop",
}

INCOMPLETE_KEY_COMMANDS = (
    "нажми",
    "отправь нажми",
)

SITE_NAMES = (
    # AI
    "чатгпт",
    "чат гпт",
    "чат джипити",
    "чат gpt",
    "чат gp",
    "chat gp",
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
    "яндекс музыку",
    "яндекс музыки",
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
    "yandex music",
    "яндекс music",
    "яндекс музыка",
    "яндекс музыку",
    "яндекс мьюзик",
)

YANDEX_MUSIC_APP_TARGETS = {
    "yandex music",
    "яндекс music",
    "яндекс музыка",
    "яндекс музыку",
    "яндекс мьюзик",
}

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
    "музыку",
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
    *(item for values in VOICE_FEEDBACK_COMMANDS.values() for item in values),
    *EXIT_COMMANDS,
    *SCREENSHOT_COMMANDS,
    *SYSTEM_INFO_COMMANDS.keys(),
    *VPN_WORDS,
    *VPN_CONNECT_WORDS,
    *VPN_DISCONNECT_WORDS,
    *VPN_STATUS_WORDS,
    *WINDOW_CONTROL_HINTS,
    *(item for values in WINDOW_STATE_COMMANDS.values() for item in values),
    *KEYBOARD_COMMANDS.keys(),
    *INCOMPLETE_KEY_COMMANDS,
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
    "рабочий режим",
    "режим работы",
    "начни работу",
    "найди на ютубе",
    "поищи на ютубе",
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


_RAW_DOMAIN_RE = re.compile(
    r"^(https?://)?[a-z0-9а-яё.-]+\.[a-zа-яё]{2,}(?::\d{1,5})?(?:[/?#]\S*)?$",
    re.IGNORECASE,
)


def _raw_command_text(text: str) -> str:
    raw = text.strip()
    raw = _whitespace_re.sub(" ", raw)
    words = [
        word
        for word in raw.split()
        if normalize_text(word) not in _FILLER_WORDS
    ]
    return " ".join(words).strip()


def _raw_target_after_prefix(text: str, prefix: str) -> str:
    raw = _raw_command_text(text)
    match = re.match(
        rf"^{re.escape(prefix)}(?:[\s,.:;!?\-]+|$)",
        raw,
        flags=re.IGNORECASE,
    )
    if match is None:
        return ""
    return raw[match.end():].strip()


def _strip_site_words_preserve_url(value: str) -> str:
    clean = value.strip()
    normalized = clean.lower().replace("ё", "е")
    for word in ("сайт", "страницу", "страница"):
        if normalized.startswith(word + " "):
            return clean[len(word):].strip()
    return clean


def _is_raw_domain_target(value: str) -> bool:
    clean = _strip_site_words_preserve_url(value)
    if not clean:
        return False
    return bool(_RAW_DOMAIN_RE.match(clean))


def remove_filler_words(text: str) -> str:
    normalized = normalize_text(text)
    words = [word for word in normalized.split() if word not in _FILLER_WORDS]
    return " ".join(words)


def _is_repeated_exit_command(normalized: str) -> bool:
    """
    Распознаёт аварийный выход даже если STT услышал повтор:
    "стоп стоп", "стоп стоп стоп", "Stop Stop", "стап стоп".

    Важно: правило срабатывает только когда вся фраза состоит
    из stop-слов, чтобы случайная фраза со словом "стоп" внутри
    не завершала ассистента.
    """
    words = normalized.split()
    if not words:
        return False

    stop_words = {"стоп", "stop", "стап", "стаб"}
    return all(word in stop_words for word in words)




def _is_mixed_open_close_command(normalized: str) -> bool:
    """Блокирует фразы вида "открой и закрой VS Code".

    Без этого parser может взять первый глагол "открой" и выполнить
    неожиданное действие с target="и закрой ...".
    """
    words = normalized.split()
    if not words:
        return False

    has_open = any(word in words for word in {"открой", "открыть", "запусти", "запустить"})
    has_close = any(
        word in words
        for word in {"закрой", "закрыть", "выключи", "выключить", "заверши", "останови"}
    )
    return has_open and has_close


def _is_ambiguous_chat_target(target: str) -> bool:
    clean = normalize_text(target)
    return clean in {"чат", "ча", "chat", "chad", "chat bot", "чат бот"}


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


def _wake_phrase_pattern(phrase: str) -> str:
    """Builds a wake-phrase regex that preserves the raw command tail.

    `normalize_text()` removes dots and URL separators. That is fine for
    comparing wake phrases, but it breaks commands like
    "Астра, открой https://example.com" before the URL parser can see the
    original target. This pattern matches the wake phrase in the raw text while
    allowing punctuation between words, then `extract_command_after_wake()`
    passes the untouched command tail to `parse_command_text()`.
    """
    words = normalize_text(phrase).split()
    if not words:
        return ""

    separator = r"[\s,.:;!?\-]+"
    body = separator.join(re.escape(word) for word in words)
    return rf"(?<!\w){body}(?!\w)"


def extract_command_after_wake(text: str, wake_phrases: list[str]) -> ParsedCommand:
    """
    Ищет фразу активации и возвращает текст после неё.

    Пример:
    "Астра, открой блокнот" -> "открой блокнот".
    "Астра" -> WAKE_ONLY.
    "открой блокнот" -> NO_WAKE.

    Важно: после wake phrase команда передаётся в parser в raw-виде,
    чтобы не ломать домены и URL точками/слэшами.
    """
    normalized = normalize_text(text)
    if not normalized:
        return ParsedCommand(CommandType.EMPTY)

    raw = text
    wake_patterns = sorted(
        {_wake_phrase_pattern(phrase) for phrase in wake_phrases},
        key=len,
        reverse=True,
    )

    for pattern in wake_patterns:
        if not pattern:
            continue

        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            continue

        command_text = raw[match.end():].lstrip(" \t\r\n,.!?;:-").rstrip()
        if not command_text:
            return ParsedCommand(CommandType.WAKE_ONLY)
        return parse_command_text(command_text)

    return ParsedCommand(CommandType.NO_WAKE, text=normalized)




def _parse_voice_feedback(normalized: str) -> ParsedCommand | None:
    for target, phrases in VOICE_FEEDBACK_COMMANDS.items():
        if normalized in phrases:
            return ParsedCommand(CommandType.VOICE_FEEDBACK, text=normalized, target=target)

    return None


def _contains_vpn_word(normalized: str) -> bool:
    padded = f" {normalized} "
    for word in VPN_WORDS:
        clean = normalize_text(word)
        if not clean:
            continue
        if f" {clean} " in padded:
            return True
    return False


def _has_any_word(normalized: str, words: tuple[str, ...]) -> bool:
    padded = f" {normalized} "
    for word in words:
        clean = normalize_text(word)
        if f" {clean} " in padded:
            return True
    return False


def _parse_vpn_control(normalized: str) -> ParsedCommand | None:
    if not _contains_vpn_word(normalized):
        return None

    if _has_any_word(normalized, VPN_DISCONNECT_WORDS):
        return ParsedCommand(CommandType.VPN_CONTROL, text=normalized, target="disconnect")

    if _has_any_word(normalized, VPN_CONNECT_WORDS):
        return ParsedCommand(CommandType.VPN_CONTROL, text=normalized, target="connect")

    if _has_any_word(normalized, VPN_STATUS_WORDS) or normalized in {"vpn", "впн"}:
        return ParsedCommand(CommandType.VPN_CONTROL, text=normalized, target="status")

    # Короткая фраза только про VPN без действия безопаснее трактуется как статус.
    if len(normalized.split()) <= 3:
        return ParsedCommand(CommandType.VPN_CONTROL, text=normalized, target="status")

    return None

def _parse_window_control(normalized: str) -> ParsedCommand | None:
    if normalized in WINDOW_LIST_COMMANDS:
        return ParsedCommand(CommandType.WINDOW_CONTROL, text=normalized, target="list")

    if normalized in ACTIVE_WINDOW_COMMANDS:
        return ParsedCommand(CommandType.WINDOW_CONTROL, text=normalized, target="active")

    for prefix in WINDOW_FOCUS_PREFIXES:
        if normalized == prefix:
            return ParsedCommand(CommandType.WINDOW_CONTROL, text=normalized, target="focus:")
        if normalized.startswith(prefix + " "):
            target = normalized.removeprefix(prefix).strip()
            if target:
                return ParsedCommand(
                    CommandType.WINDOW_CONTROL,
                    text=normalized,
                    target=f"focus:{target}",
                )

    for target, phrases in WINDOW_STATE_COMMANDS.items():
        if normalized in phrases:
            return ParsedCommand(CommandType.WINDOW_CONTROL, text=normalized, target=target)

    return None


def _parse_routine(normalized: str) -> ParsedCommand | None:
    """Recognize an explicit routine request; config aliases stay exact-match."""
    direct_aliases = {
        "рабочий режим": "рабочий режим",
        "режим работы": "рабочий режим",
        "начни работу": "рабочий режим",
    }
    if normalized in direct_aliases:
        return ParsedCommand(
            CommandType.ROUTINE,
            text=normalized,
            target=direct_aliases[normalized],
        )

    for prefix in ("включи", "запусти"):
        marker = prefix + " "
        if normalized.startswith(marker):
            target = normalized.removeprefix(marker).strip()
            if target.endswith(" режим") or target.startswith("режим "):
                return ParsedCommand(CommandType.ROUTINE, text=normalized, target=target)

    return None


def _parse_youtube_search(text: str, normalized: str) -> ParsedCommand | None:
    prefixes = (
        "найди на ютубе",
        "найди в ютубе",
        "поищи на ютубе",
        "поищи в ютубе",
        "поиск на ютубе",
        "найди на youtube",
        "поищи на youtube",
    )
    for prefix in prefixes:
        if normalized == prefix:
            return ParsedCommand(CommandType.WEB_SEARCH, text=normalized, target="youtube:")
        if normalized.startswith(prefix + " "):
            query = _raw_target_after_prefix(text, prefix)
            if not query:
                query = normalized.removeprefix(prefix).strip()
            return ParsedCommand(
                CommandType.WEB_SEARCH,
                text=normalized,
                target=f"youtube:{query}",
            )
    return None


def _parse_keyboard_shortcut(normalized: str) -> ParsedCommand | None:
    if normalized in INCOMPLETE_KEY_COMMANDS:
        return ParsedCommand(
            CommandType.KEYBOARD_SHORTCUT,
            text=normalized,
            target="incomplete_key",
        )

    if normalized in KEYBOARD_COMMANDS:
        return ParsedCommand(
            CommandType.KEYBOARD_SHORTCUT,
            text=normalized,
            target=KEYBOARD_COMMANDS[normalized],
        )

    # STT часто обрезает конец "обмена": "открой буфер up/ап/об".
    # Любая фраза "открой буфер ..." безопасно открывает Win+V.
    if normalized.startswith("открой буфер") or normalized.startswith("покажи буфер"):
        return ParsedCommand(
            CommandType.KEYBOARD_SHORTCUT,
            text=normalized,
            target="clipboard_history",
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


def _is_yandex_music_app_target(target: str) -> bool:
    """Recognize only explicit app names, never the generic word "музыка"."""
    return normalize_text(target) in YANDEX_MUSIC_APP_TARGETS


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

    # v0.9.6: аварийный выход должен оставаться локальным даже при
    # повторном распознавании: "стоп стоп стоп".
    if _is_repeated_exit_command(normalized):
        return ParsedCommand(CommandType.EXIT, text=normalized)

    # v0.10.5: смешанные команды не выполняем автоматически.
    if _is_mixed_open_close_command(normalized):
        return ParsedCommand(CommandType.OPEN_APP, text=normalized, target=MIXED_COMMAND_TARGET)

    voice_feedback = _parse_voice_feedback(normalized)
    if voice_feedback is not None:
        return voice_feedback

    vpn_control = _parse_vpn_control(normalized)
    if vpn_control is not None:
        return vpn_control

    if normalized in HELP_COMMANDS:
        return ParsedCommand(CommandType.HELP, text=normalized)

    routine = _parse_routine(normalized)
    if routine is not None:
        return routine

    window_control = _parse_window_control(normalized)
    if window_control is not None:
        return window_control

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

    if normalized in {"включи музыку", "запусти музыку"}:
        return ParsedCommand(
            CommandType.OPEN_APP,
            text=normalized,
            target=AMBIGUOUS_MUSIC_TARGET,
        )

    if normalized in {"открой чат", "открой ча", "открыть чат", "запусти чат"}:
        return ParsedCommand(CommandType.OPEN_APP, text=normalized, target=AMBIGUOUS_CHAT_TARGET)

    # v0.9.5: не даём "открой окно" попадать в fuzzy app matching.
    # Раньше target="окно" частично совпадал с alias "блокнот" и случайно
    # запускал Notepad. Открытие/создание активных окон пока не поддерживаем.
    if normalized in {
        "открой окно",
        "открыть окно",
        "открой новое окно",
        "открыть новое окно",
        "открой активное окно",
        "открой последнее окно",
        "открой последнее",
        "открой последние",
        "открой последнии",
        "открой posledniy",
    }:
        return ParsedCommand(CommandType.OPEN_APP, text=normalized, target=UNSUPPORTED_OPEN_TARGET)

    # v0.9.3 hotfix: раньше это уходило как ASK_LLM, но is_command_like_text
    # всё равно матчил "закрой" как хинт, и фраза улетала в LLM-router, где
    # молча гасла (confidence=0, router_unknown_guard). Теперь это прямая
    # локальная команда с sentinel-таргетом — router вообще не вызывается,
    # Alt+F4 не выполняется, пользователь получает честный ответ.
    if normalized in {
        "закрой окно",
        "закрыть окно",
        "закрой ок",
        "закрыть ок",
        "закрой ак",
        "закрыть ак",
        "закрой аг",
        "закрыть аг",
        "закрой это окно",
        "закрой активное окно",
        "закрой текущее окно",
        "закрой данное окно",
        "закрой последнее",
        "закрой последние",
        "закрой последнии",
        "закрой последний",
        "закрой posledniy",
        "закрыть последнее",
        "закрыть последние",
        "закрой последнее окно",
        "закрой последние окно",
        "закрой последнии окно",
        "Закрой posledniy окно".lower(),
        "закрой последнее акно",
        "закрой последнее ок",
        "закрой последние ок",
        "закрой последнии ок",
        "закрой последнее ак",
        "закрой последнее аг",
        "закрыть последнее окно",
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

    youtube_search = _parse_youtube_search(text, normalized)
    if youtube_search is not None:
        return youtube_search

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

            raw_target = _raw_target_after_prefix(text, prefix)
            if _is_raw_domain_target(raw_target):
                return ParsedCommand(
                    CommandType.OPEN_URL,
                    text=normalized,
                    target=_strip_site_words_preserve_url(raw_target),
                )

            # v1.2: an installed Yandex Music client is the default for the
            # explicit product name. The website stays available through
            # "открой сайт Яндекс Музыки" and normal URL/domain handling.
            if _is_yandex_music_app_target(target):
                return ParsedCommand(
                    CommandType.OPEN_APP,
                    text=normalized,
                    target="яндекс музыка",
                )

            if _is_ambiguous_chat_target(target):
                return ParsedCommand(CommandType.OPEN_APP, text=normalized, target=AMBIGUOUS_CHAT_TARGET)

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
            if _is_yandex_music_app_target(target):
                return ParsedCommand(
                    CommandType.CLOSE_APP,
                    text=normalized,
                    target="яндекс музыка",
                )
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
