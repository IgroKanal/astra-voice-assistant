from __future__ import annotations

import re
import json
import math
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, time as datetime_time
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
    MEDIA_CONTROL = "media_control"
    TYPE_TEXT = "type_text"
    SCREENSHOT = "screenshot"
    SYSTEM_INFO = "system_info"
    VPN_CONTROL = "vpn_control"
    WINDOW_CONTROL = "window_control"
    VOICE_FEEDBACK = "voice_feedback"
    ROUTINE = "routine"
    REMINDER = "reminder"
    MEMORY_NOTE = "memory_note"
    FILE_SEARCH = "file_search"
    FILE_OPEN = "file_open"
    FILE_READ = "file_read"
    FILE_QUESTION = "file_question"
    CLEAR_DIALOGUE = "clear_dialogue"
    HELP = "help"
    ASK_LLM = "ask_llm"
    EXIT = "exit"
    EMPTY = "empty"


@dataclass(frozen=True)
class ParsedCommand:
    type: CommandType
    text: str = ""
    target: str = ""
    query: str = ""


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
CANCEL_REMINDER_UI_TARGET = "__cancel_reminder_ui__"
CANCEL_NEXT_REMINDER_TARGET = "__cancel_next_reminder__"
CANCEL_REMINDER_MATCH_PREFIX = "__cancel_reminder_match__:"
LIST_UPCOMING_REMINDERS_TARGET = "__list_upcoming_reminders__"
MEMORY_HELP_TARGET = "__memory_help__"
MEMORY_LIST_TARGET = "__memory_list__"
MEMORY_SAVE_TARGET = "__memory_save__"
MEMORY_SEARCH_PREFIX = "__memory_search__:"
MEMORY_FORGET_PREFIX = "__memory_forget__:"
FILE_SEARCH_HELP_TARGET = "__file_search_help__"
FILE_OPEN_HELP_TARGET = "__file_open_help__"
FILE_READ_HELP_TARGET = "__file_read_help__"
FILE_READ_NEXT_TARGET = "__file_read_next__"
FILE_QUESTION_HELP_TARGET = "__file_question_help__"
LIST_REMINDER_PHRASES = frozenset({
    "покажи напоминания",
    "покажи мои напоминания",
    "какие у меня напоминания",
    "какие у меня есть напоминания",
    "какие у меня ближайшие напоминания",
    "какие ближайшие напоминания",
    "назови ближайшие напоминания",
    "что у меня с напоминаниями",
})
REMINDER_WEEKDAYS = {
    "понедельник": 0,
    "вторник": 1,
    "среду": 2,
    "четверг": 3,
    "пятницу": 4,
    "субботу": 5,
    "воскресенье": 6,
}
_CLOCK_WORD_VALUES = {"ноль": 0, "нуль": 0, "час": 1}
_CLOCK_ONES = {
    1: ("один", "одна"),
    2: ("два", "две"),
    3: ("три",),
    4: ("четыре",),
    5: ("пять",),
    6: ("шесть",),
    7: ("семь",),
    8: ("восемь",),
    9: ("девять",),
}
_CLOCK_TEENS = (
    "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать",
    "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать",
)
_CLOCK_TENS = {20: "двадцать", 30: "тридцать", 40: "сорок", 50: "пятьдесят"}
for _number, _forms in _CLOCK_ONES.items():
    for _form in _forms:
        _CLOCK_WORD_VALUES[_form] = _number
for _number, _word in enumerate(_CLOCK_TEENS, start=10):
    _CLOCK_WORD_VALUES[_word] = _number
for _tens, _word in _CLOCK_TENS.items():
    _CLOCK_WORD_VALUES[_word] = _tens
    for _ones, _forms in _CLOCK_ONES.items():
        for _form in _forms:
            _CLOCK_WORD_VALUES[f"{_word} {_form}"] = _tens + _ones
_CLOCK_NUMBER_PATTERN = "(?:\\d{1,2}|" + "|".join(
    re.escape(value) for value in sorted(_CLOCK_WORD_VALUES, key=lambda value: (-len(value), value))
) + ")"


def _parse_clock_number(value: str) -> int | None:
    return int(value) if value.isdigit() else _CLOCK_WORD_VALUES.get(value)


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

CLEAR_DIALOGUE_COMMANDS = (
    "начни новый диалог",
    "начать новый диалог",
    "новый диалог",
    "очисти диалог",
    "сбрось контекст разговора",
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
        "разверни на весь экран",
        "разверни окно на весь экран",
        "разверни в полный размер",
        "разверни окно в полный размер",
        "открой на весь экран",
        "открой окно на весь экран",
        "открой в полном режиме",
        "сделай на весь экран",
        "сделай окно на весь экран",
        "сделай окно большим",
        "сделай окно широким",
        "разверни широко",
        "максимизируй окно",
        "разверни",
    ),
    "restore": (
        "восстанови окно",
        "восстанови активное окно",
        "восстанови текущее окно",
        "верни обычный размер",
        "верни обычный размер окна",
        "верни на обычный размер",
        "верни на обычный размер окна",
        "верни окно в обычный размер",
        "сделай обычный размер окна",
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

WINDOW_TARGET_STATE_PREFIXES = {
    "minimize": (
        "сверни",
        "свернуть",
    ),
    "maximize": (
        "разверни",
        "развернуть",
        "максимизируй",
    ),
    "restore": (
        "восстанови",
        "восстановить",
        "верни обычный размер",
        "верни на обычный размер",
        "верни окно в обычный размер",
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
    "прибавь громкость": "volume_up",
    "тише": "volume_down",
    "сделай тише": "volume_down",
    "уменьши громкость": "volume_down",
    "убавь громкость": "volume_down",
    "переключи звук": "volume_mute",
    "звук": "volume_mute",
    # Global media keys: they work with the active media session and do not
    # type text or execute a process/shell command.
    "пауза": "media_play_pause",
    "поставь на паузу": "media_play_pause",
    "музыку на паузу": "media_play_pause",
    "продолжи музыку": "media_play",
    "возобнови музыку": "media_play",
    "следующий трек": "media_next",
    "следующая песня": "media_next",
    "переключи трек": "media_next",
    "предыдущий трек": "media_previous",
    "предыдущая песня": "media_previous",
    "верни предыдущий трек": "media_previous",
    "верни предыдущую песню": "media_previous",
    "начни трек заново": "media_restart_current",
    "перезапусти трек": "media_restart_current",
    "перезапусти песню": "media_restart_current",
    "останови музыку": "media_stop",
    "останови воспроизведение": "media_stop",
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
    "локальный плеер",
    "локальный проигрыватель",
    "медиаплеер",
    "медиа плеер",
    "проигрыватель",
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

MEDIA_TARGET_ALIASES = {
    "local": (
        "локальный плеер",
        "локальном плеере",
        "локального плеера",
        "локальный проигрыватель",
        "локальном проигрывателе",
        "медиаплеер",
        "медиа плеер",
        "плеер",
        "проигрыватель",
        "groove music",
        "музыка groove",
        "музыка грув",
        "грув музыка",
        # Частые безопасные ошибки Google STT для фразы
        # «в локальном плеере». Они используются только рядом с фиксированной
        # media-командой и никогда не становятся путём/именем процесса.
        "вокальный плеер",
        "вокальном плеере",
        "локальный пуэр",
        "локальном пуэре",
        "вокальный пуэр",
        "вокальном пуэре",
        "локальный pueri",
        "локальном pueri",
        "вокальный pueri",
        "вокальном pueri",
    ),
    "yandex": (
        "яндекс музыка",
        "яндекс музыке",
        "яндекс музыки",
        "яндекс музыку",
        "yandex music",
    ),
}

MEDIA_BASE_ACTIONS = {
    "пауза": "play_pause",
    "поставь на паузу": "play_pause",
    "продолжи": "play",
    "продолжи музыку": "play",
    "возобнови": "play",
    "возобнови музыку": "play",
    "следующий трек": "next",
    "следующая песня": "next",
    "переключи трек": "next",
    "предыдущий трек": "previous",
    "предыдущая песня": "previous",
    "верни предыдущий трек": "previous",
    "верни предыдущую песню": "previous",
    "начни трек заново": "restart_current",
    "перезапусти трек": "restart_current",
    "перезапусти песню": "restart_current",
    "останови": "stop",
    "останови музыку": "stop",
    "останови воспроизведение": "stop",
}


# Короткие окончания, которыми Google STT часто заменяет «в локальном
# плеере». Они принимаются только если начало фразы уже является точной
# allowlisted media-командой.
LOCAL_MEDIA_STT_TAILS = (
    "вока",
    "лока",
    "локо",
    "лака",
    "loco",
)


COMMAND_HINTS = (
    *OPEN_PREFIXES,
    *CLOSE_PREFIXES,
    *SEARCH_PREFIXES,
    *TYPE_TEXT_PREFIXES,
    *TIME_COMMANDS,
    *DATE_COMMANDS,
    *HELP_COMMANDS,
    *CLEAR_DIALOGUE_COMMANDS,
    "запомни",
    "запиши в память",
    "сохрани в памяти",
    "покажи сохраненные заметки",
    "какие заметки ты помнишь",
    "что ты помнишь",
    "забудь заметку",
    "найди заметку",
    "найди файл",
    "найди документ",
    "поищи файл",
    "поищи документ",
    "поиск файла",
    "поиск документа",
    "открой файл",
    "открой документ",
    "прочитай файл",
    "прочитай документ",
    "прочитай дальше",
    "продолжи чтение",
    "продолжи читать",
    "следующая часть",
    "спроси по файлу",
    "зачитай файл",
    "зачитай документ",
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

    if re.search(r"(?<!\w)(напомни|отмени (?:ближайшее |следующее )?напоминание)(?!\w)", normalized):
        return True
    if any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized) for phrase in LIST_REMINDER_PHRASES):
        return True

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

    # Exact active-window commands take precedence over targeted prefixes.
    for target, phrases in WINDOW_STATE_COMMANDS.items():
        if normalized in phrases:
            return ParsedCommand(CommandType.WINDOW_CONTROL, text=normalized, target=target)

    # Targeted state changes never execute a process or shell command.  The
    # target is used only to find an already visible top-level window.
    for action, prefixes in WINDOW_TARGET_STATE_PREFIXES.items():
        for prefix in prefixes:
            if normalized.startswith(prefix + " "):
                target = normalized.removeprefix(prefix).strip()
                if action == "maximize":
                    for suffix in (" на весь экран", " в полный размер", " в полном режиме"):
                        if target.endswith(suffix):
                            target = target[: -len(suffix)].strip()
                            break
                if action == "restore" and target.endswith(" окна"):
                    target = target.removesuffix(" окна").strip()
                if target and target not in {"окно", "активное окно", "текущее окно"}:
                    return ParsedCommand(
                        CommandType.WINDOW_CONTROL,
                        text=normalized,
                        target=f"{action}:{target}",
                    )

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


def _parse_targeted_media_control(normalized: str) -> ParsedCommand | None:
    # Direct wake commands may arrive as «следующий трек вока/лока».  Accept
    # these short STT corruptions only when the left side is an exact fixed
    # media action; arbitrary text never reaches this branch.
    for tail in LOCAL_MEDIA_STT_TAILS:
        suffix = " " + tail
        if normalized.endswith(suffix):
            base_phrase = normalized[: -len(suffix)].strip()
            action = MEDIA_BASE_ACTIONS.get(base_phrase)
            if action:
                return ParsedCommand(
                    CommandType.MEDIA_CONTROL,
                    text=normalized,
                    target=f"{action}:local",
                )

    for target, aliases in MEDIA_TARGET_ALIASES.items():
        for alias in aliases:
            candidates = []
            for connector in (" в ", " для "):
                suffix = connector + alias
                if normalized.endswith(suffix):
                    candidates.append(normalized[: -len(suffix)].strip())
            if normalized.startswith(alias + " "):
                candidates.append(normalized.removeprefix(alias).strip())

            # Natural Russian imperative forms: "останови локальный плеер",
            # "поставь локальный плеер на паузу".
            if normalized == f"останови {alias}":
                candidates.append("останови")
            if normalized == f"поставь {alias} на паузу":
                candidates.append("поставь на паузу")
            if normalized == f"продолжи {alias}":
                candidates.append("продолжи")

            for base_phrase in candidates:
                action = MEDIA_BASE_ACTIONS.get(base_phrase)
                if action:
                    return ParsedCommand(
                        CommandType.MEDIA_CONTROL,
                        text=normalized,
                        target=f"{action}:{target}",
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


def _memory_match_tail(raw_text: str, prefix: str) -> str | None:
    raw = _whitespace_re.sub(" ", raw_text.strip())
    match = re.match(
        rf"^{re.escape(prefix)}(?:[\s,.:;!?\-]+|$)",
        raw,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return raw[match.end():].strip(" \t\r\n,.:;!?")


def _parse_memory_command(raw_text: str, normalized: str) -> ParsedCommand | None:
    list_phrases = {
        "покажи сохраненные заметки",
        "покажи мои заметки",
        "какие заметки ты помнишь",
        "что ты запомнила",
        "что ты запомнил",
        "список сохраненных заметок",
        "список заметок",
        "покажи личную память",
    }
    if normalized in list_phrases:
        return ParsedCommand(CommandType.MEMORY_NOTE, text=normalized, target=MEMORY_LIST_TARGET)

    searches = (
        "найди заметку про",
        "найди в памяти",
        "покажи заметку про",
        "что я просил запомнить про",
        "что я просила запомнить про",
        "что ты помнишь про",
        "что ты помнишь о",
    )
    for prefix in searches:
        tail = _memory_match_tail(raw_text, prefix)
        if normalized == prefix or tail is not None:
            query = tail or ""
            if 3 <= len(query) <= 160 and all(char.isprintable() for char in query):
                return ParsedCommand(
                    CommandType.MEMORY_NOTE,
                    text=normalized,
                    target=MEMORY_SEARCH_PREFIX + query,
                )
            return ParsedCommand(CommandType.MEMORY_NOTE, text=normalized, target=MEMORY_HELP_TARGET)

    forgets = (
        "забудь заметку про",
        "удали из памяти заметку про",
        "забудь про",
    )
    for prefix in forgets:
        tail = _memory_match_tail(raw_text, prefix)
        if normalized == prefix or tail is not None:
            query = tail or ""
            if 3 <= len(query) <= 160 and all(char.isprintable() for char in query):
                return ParsedCommand(
                    CommandType.MEMORY_NOTE,
                    text=normalized,
                    target=MEMORY_FORGET_PREFIX + query,
                )
            return ParsedCommand(CommandType.MEMORY_NOTE, text=normalized, target=MEMORY_HELP_TARGET)

    save_match = re.match(
        r"^\s*(?:пожалуйста\s+)?(?:запомни(?:\s*,?\s*что)?|запиши\s+в\s+память|сохрани\s+в\s+памяти)\s*[:\-]?\s*(.*)$",
        raw_text.strip(),
        flags=re.IGNORECASE,
    )
    if save_match is not None:
        note = _whitespace_re.sub(" ", save_match.group(1).strip())
        if 3 <= len(note) <= 3000 and all(char.isprintable() for char in note):
            return ParsedCommand(CommandType.MEMORY_NOTE, text=note, target=MEMORY_SAVE_TARGET)
        return ParsedCommand(CommandType.MEMORY_NOTE, text=normalized, target=MEMORY_HELP_TARGET)

    if normalized in {"запомни", "запиши в память", "сохрани в памяти", "забудь заметку", "найди заметку"}:
        return ParsedCommand(CommandType.MEMORY_NOTE, text=normalized, target=MEMORY_HELP_TARGET)

    return None


def _parse_file_search_command(raw_text: str, normalized: str) -> ParsedCommand | None:
    prefixes = (
        "найди файл в папке",
        "найди документ в папке",
        "найди файл",
        "найди документ",
        "поищи файл",
        "поищи документ",
        "поиск файла",
        "поиск документа",
    )
    for prefix in prefixes:
        tail = _memory_match_tail(raw_text, prefix)
        if normalized == prefix or tail is not None:
            query = tail or ""
            if 2 <= len(query) <= 120 and all(char.isprintable() for char in query) and not any(char in query for char in "/\\:"):
                return ParsedCommand(CommandType.FILE_SEARCH, text=normalized, target=query)
            return ParsedCommand(CommandType.FILE_SEARCH, text=normalized, target=FILE_SEARCH_HELP_TARGET)
    if normalized in {"найди файл", "найди документ", "поищи файл", "поищи документ", "поиск файла", "поиск документа"}:
        return ParsedCommand(CommandType.FILE_SEARCH, text=normalized, target=FILE_SEARCH_HELP_TARGET)
    return None


def _parse_file_open_command(raw_text: str, normalized: str) -> ParsedCommand | None:
    prefixes = ("открой файл", "открой документ")
    for prefix in prefixes:
        tail = _memory_match_tail(raw_text, prefix)
        if normalized == prefix or tail is not None:
            filename = tail or ""
            if 2 <= len(filename) <= 120 and all(char.isprintable() for char in filename) and not any(char in filename for char in "/\\:"):
                return ParsedCommand(CommandType.FILE_OPEN, text=normalized, target=filename)
            return ParsedCommand(CommandType.FILE_OPEN, text=normalized, target=FILE_OPEN_HELP_TARGET)
    return None


def _parse_file_read_command(raw_text: str, normalized: str) -> ParsedCommand | None:
    if normalized in {"прочитай дальше", "продолжи чтение", "продолжи читать", "следующая часть"}:
        return ParsedCommand(CommandType.FILE_READ, text=normalized, target=FILE_READ_NEXT_TARGET)
    prefixes = ("прочитай файл", "прочитай документ", "зачитай файл", "зачитай документ")
    for prefix in prefixes:
        tail = _memory_match_tail(raw_text, prefix)
        if normalized == prefix or tail is not None:
            filename = tail or ""
            if 2 <= len(filename) <= 120 and all(char.isprintable() for char in filename) and not any(char in filename for char in "/\\:"):
                return ParsedCommand(CommandType.FILE_READ, text=normalized, target=filename)
            return ParsedCommand(CommandType.FILE_READ, text=normalized, target=FILE_READ_HELP_TARGET)
    return None


def _parse_file_question_command(raw_text: str, normalized: str) -> ParsedCommand | None:
    prefix = "спроси по файлу"
    tail = _memory_match_tail(raw_text, prefix)
    if normalized != prefix and tail is None:
        return None
    if not tail:
        return ParsedCommand(CommandType.FILE_QUESTION, text=normalized, target=FILE_QUESTION_HELP_TARGET)
    parts = re.split(r"\s+вопрос\s+", tail, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return ParsedCommand(CommandType.FILE_QUESTION, text=normalized, target=FILE_QUESTION_HELP_TARGET)
    filename, question = (part.strip() for part in parts)
    valid_filename = (
        2 <= len(filename) <= 120
        and all(char.isprintable() and unicodedata.category(char) not in {"Cf", "Cs"} for char in filename)
        and not any(char in filename for char in "/\\:")
    )
    valid_question = (
        2 <= len(question) <= 1000
        and all(char.isprintable() and unicodedata.category(char) not in {"Cf", "Cs"} for char in question)
    )
    if not valid_filename or not valid_question:
        return ParsedCommand(CommandType.FILE_QUESTION, text=normalized, target=FILE_QUESTION_HELP_TARGET)
    return ParsedCommand(CommandType.FILE_QUESTION, text=normalized, target=filename, query=question)


def parse_command_text(text: str) -> ParsedCommand:
    """Определяет тип команды уже без wake phrase."""
    normalized = remove_filler_words(text)
    if not normalized:
        return ParsedCommand(CommandType.EMPTY)

    if normalized in CLEAR_DIALOGUE_COMMANDS:
        return ParsedCommand(CommandType.CLEAR_DIALOGUE, text=normalized)

    file_question = _parse_file_question_command(text, normalized)
    if file_question is not None:
        return file_question

    file_search = _parse_file_search_command(text, normalized)
    if file_search is not None:
        return file_search

    file_open = _parse_file_open_command(text, normalized)
    if file_open is not None:
        return file_open

    file_read = _parse_file_read_command(text, normalized)
    if file_read is not None:
        return file_read

    memory_command = _parse_memory_command(text, normalized)
    if memory_command is not None:
        return memory_command

    if normalized in LIST_REMINDER_PHRASES:
        return ParsedCommand(CommandType.REMINDER, text=normalized, target=LIST_UPCOMING_REMINDERS_TARGET)
    if normalized in {"отмени ближайшее напоминание", "отмени следующее напоминание"}:
        return ParsedCommand(CommandType.REMINDER, text=normalized, target=CANCEL_NEXT_REMINDER_TARGET)
    if normalized.startswith("отмени напоминание "):
        query = normalized[len("отмени напоминание "):].strip()
        if 2 <= len(query) <= 160:
            return ParsedCommand(CommandType.REMINDER, text=normalized, target=CANCEL_REMINDER_MATCH_PREFIX + query)
    if normalized.startswith("отмени напоминание"):
        return ParsedCommand(CommandType.REMINDER, text=normalized, target=CANCEL_REMINDER_UI_TARGET)
    if normalized.startswith("напомни"):
        dated_match = re.fullmatch(
            r"напомни(?: мне)? (сегодня|завтра|послезавтра) в ("
            + _CLOCK_NUMBER_PATTERN
            + r")(?: ("
            + _CLOCK_NUMBER_PATTERN
            + r"))? (.+)",
            normalized,
        )
        if dated_match:
            day_offsets = {"сегодня": 0, "завтра": 1, "послезавтра": 2}
            hour = _parse_clock_number(dated_match[2])
            minute = _parse_clock_number(dated_match[3] or "0")
            text_to_remember = dated_match[4]
            if hour is not None and minute is not None and 0 <= hour <= 23 and 0 <= minute <= 59 and len(text_to_remember) <= 1000:
                local_now = datetime.now().astimezone()
                target_date = local_now.date() + timedelta(days=day_offsets[dated_match[1]])
                target_local = datetime.combine(target_date, datetime_time(hour, minute)).astimezone()
                delay = math.ceil(target_local.timestamp() - local_now.timestamp())
                if 1 <= delay <= 30 * 86400:
                    return ParsedCommand(
                        CommandType.REMINDER,
                        text=normalized,
                        target=json.dumps({"delay": delay, "text": text_to_remember}, ensure_ascii=False),
                    )
            return ParsedCommand(CommandType.REMINDER, text=normalized)

        weekday_match = re.fullmatch(
            r"напомни(?: мне)? (?:в|во) (понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье) в ("
            + _CLOCK_NUMBER_PATTERN
            + r")(?: ("
            + _CLOCK_NUMBER_PATTERN
            + r"))? (.+)",
            normalized,
        )
        if weekday_match:
            hour = _parse_clock_number(weekday_match[2])
            minute = _parse_clock_number(weekday_match[3] or "0")
            text_to_remember = weekday_match[4]
            if hour is not None and minute is not None and 0 <= hour <= 23 and 0 <= minute <= 59 and len(text_to_remember) <= 1000:
                local_now = datetime.now().astimezone()
                days_ahead = (REMINDER_WEEKDAYS[weekday_match[1]] - local_now.weekday()) % 7
                target_date = local_now.date() + timedelta(days=days_ahead)
                target_time = datetime_time(hour, minute)
                target_local = datetime.combine(target_date, target_time).astimezone()
                if target_local.timestamp() <= local_now.timestamp():
                    target_date += timedelta(days=7)
                    target_local = datetime.combine(target_date, target_time).astimezone()
                delay = math.ceil(target_local.timestamp() - local_now.timestamp())
                if 1 <= delay <= 30 * 86400:
                    return ParsedCommand(
                        CommandType.REMINDER,
                        text=normalized,
                        target=json.dumps({"delay": delay, "text": text_to_remember}, ensure_ascii=False),
                    )
            return ParsedCommand(CommandType.REMINDER, text=normalized)

        match = re.fullmatch(r"напомни(?: мне)? через (\d{1,5}|одну|один|два|две|три|четыре|пять|десять|пятнадцать|двадцать|тридцать|шестьдесят) (секунд[уы]?|минут[уы]?|час(?:а|ов)?) (.+)", normalized)
        if match:
            words = {"одну": 1, "один": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "десять": 10, "пятнадцать": 15, "двадцать": 20, "тридцать": 30, "шестьдесят": 60}
            amount = int(match[1]) if match[1].isdigit() else words[match[1]]
            multiplier = 1 if match[2].startswith("секунд") else 60 if match[2].startswith("минут") else 3600
            delay = amount * multiplier
            if 1 <= delay <= 30 * 86400 and len(match[3]) <= 1000:
                return ParsedCommand(CommandType.REMINDER, text=normalized, target=json.dumps({"delay": delay, "text": match[3]}, ensure_ascii=False))
        return ParsedCommand(CommandType.REMINDER, text=normalized)

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

    targeted_media = _parse_targeted_media_control(normalized)
    if targeted_media is not None:
        return targeted_media

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

    if normalized in {
        "включи локальную музыку",
        "запусти локальную музыку",
        "включи локальный плеер",
        "запусти локальный плеер",
        "включи groove",
        "включи грув",
        "включи музыку groove",
        "включи музыку грув",
        "запусти музыку groove",
        "запусти музыку грув",
    }:
        return ParsedCommand(
            CommandType.MEDIA_CONTROL,
            text=normalized,
            target="open_play_local",
        )

    if normalized in {"включи музыку", "запусти музыку"}:
        return ParsedCommand(
            CommandType.OPEN_APP,
            text=normalized,
            target=AMBIGUOUS_MUSIC_TARGET,
        )

    if normalized in {"выключи музыку", "закрой музыку"}:
        return ParsedCommand(
            CommandType.MEDIA_CONTROL,
            text=normalized,
            target="shutdown_yandex_music",
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
