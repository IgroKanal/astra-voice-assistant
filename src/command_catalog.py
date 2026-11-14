"""Curated examples for actions already supported by Astra's local parser."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CommandExample:
    key: str
    title: str
    phrase: str
    description: str


@dataclass(frozen=True)
class CommandGroup:
    key: str
    title: str
    examples: tuple[CommandExample, ...]


COMMAND_GROUPS = (
    CommandGroup("basic", "Основное", (
        CommandExample("time", "Узнать время", "сколько времени", "Спросить текущее местное время."),
        CommandExample("date", "Узнать дату", "какая сегодня дата", "Спросить сегодняшнюю дату."),
        CommandExample("help", "Помощь голосом", "помощь", "Попросить короткую справку голосом или в чате."),
        CommandExample("new_dialogue", "Начать новый диалог", "начни новый диалог", "Сбросить контекст текущего разговора после подтверждения."),
        CommandExample("memory_save", "Запомнить личную заметку", "запомни, что я предпочитаю ответы по-русски", "Сохранить короткую заметку локально; нужны локальная память и разрешение личных заметок."),
        CommandExample("memory_list", "Список личных заметок", "покажи сохранённые заметки", "Назвать до трёх заголовков заметок, хранящихся локально."),
        CommandExample("memory_search", "Найти личную заметку", "найди заметку про язык ответов", "Найти одну заметку по точному фрагменту и прочитать её коротко."),
        CommandExample("memory_forget", "Забыть личную заметку", "забудь заметку про язык ответов", "Удалить только одну заметку при единственном совпадении; неоднозначный запрос ничего не удаляет."),
        CommandExample("file_search", "Поиск в разрешённой папке", "найди файл договор", "Искать только имена внутри папки, выбранной в разделе «Файлы»; требуется wake-фраза и отдельное разрешение."),
        CommandExample("file_open", "Открыть точное имя файла", "открой файл договор.pdf", "Открывает одно точное совпадение для разрешённого документа или медиа; нужны выбранная папка и отдельное разрешение."),
        CommandExample("file_read", "Прочитать документ голосом", "прочитай файл договор.pdf", "Озвучить локальным Windows SAPI отрывок одного TXT/MD/PDF/DOCX/XLSX/PPTX-документа из выбранной папки; нужен wake и отдельное разрешение."),
        CommandExample("file_read_next", "Продолжить чтение документа", "прочитай дальше", "Озвучить следующий отрывок текущего документа локальным Windows SAPI; доступ к выбранной папке и разрешение чтения должны оставаться активными."),
        CommandExample("file_question", "Задать вопрос по файлу", "спроси по файлу договор.pdf вопрос какие сроки указаны", "Передаёт вопрос и ограниченные цитаты из одного точно названного документа только локальному Ollama; приватный ответ звучит через Windows SAPI. Нужны wake-фраза, открытая выбранная папка и разрешение ask_files. Облачный маршрут запрещён."),
    )),
    CommandGroup("apps", "Приложения и сайты", (
        CommandExample("open_youtube", "Открыть YouTube", "открой YouTube", "Открыть известный сайт в браузере."),
        CommandExample("open_telegram", "Открыть Telegram", "открой Telegram", "Открыть приложение из настроенного списка Astra."),
        CommandExample("open_firefox", "Открыть Firefox", "открой Firefox", "Открыть приложение из настроенного списка Astra."),
        CommandExample("web_search", "Найти в интернете", "найди в интернете погода завтра", "Открыть поиск с указанной темой."),
        CommandExample("youtube_search", "Найти видео", "найди на ютубе Python 3.12", "Открыть поиск видео на YouTube."),
    )),
    CommandGroup("media", "Музыка и громкость", (
        CommandExample("music_play", "Включить локальную музыку", "включи локальную музыку", "Открыть настроенный локальный плеер и начать воспроизведение."),
        CommandExample("music_next", "Следующий трек", "следующий трек в локальном плеере", "Переключить трек в явно названном локальном плеере."),
        CommandExample("music_pause", "Поставить на паузу", "поставь на паузу", "Отправить стандартную команду паузы активному медиаплееру."),
        CommandExample("music_previous", "Предыдущий трек", "предыдущий трек в локальном плеере", "Переключить на предыдущий трек в явно названном локальном плеере."),
        CommandExample("volume_up", "Сделать громче", "прибавь громкость", "Немного увеличить системную громкость."),
    )),
    CommandGroup("windows", "Окна", (
        CommandExample("window_list", "Показать открытые окна", "какие окна открыты", "Показать доступные окна приложений."),
        CommandExample("window_minimize", "Свернуть окно", "сверни окно", "Свернуть активное окно."),
        CommandExample("window_maximize", "Развернуть окно", "разверни окно", "Развернуть активное окно Windows."),
        CommandExample("window_restore", "Обычный размер окна", "верни обычный размер окна", "Вернуть активное окно к обычному размеру."),
    )),
    CommandGroup("tasks", "Напоминания", (
        CommandExample("reminder", "Создать напоминание", "напомни через пять минут сделать перерыв", "Сохранить напоминание на заданный срок."),
        CommandExample("reminder_at_time", "Напомнить к определённому времени", "напомни завтра в девять тридцать позвонить", "Поставить напоминание на местное время сегодня, завтра, послезавтра или в ближайший день недели; Astra понимает часы словами и цифрами."),
        CommandExample("reminder_list", "Узнать ближайшие напоминания", "покажи мои напоминания", "Назвать до трёх ближайших активных напоминаний; полный список остаётся в разделе «Задачи» приложения Astra."),
        CommandExample("reminder_cancel_match", "Отменить напоминание по названию", "отмени напоминание про встречу", "Отменить только одно активное напоминание, если точный фрагмент однозначно совпал с его названием."),
        CommandExample("reminder_cancel", "Узнать, как отменить", "отмени напоминание", "Получить подсказку о списке напоминаний в разделе «Задачи»."),
    )),
)

_SEARCH_RE = re.compile(r"[^\w]+", re.UNICODE)


def _normalize_search(value: str) -> str:
    return _SEARCH_RE.sub(" ", value.casefold().replace("ё", "е")).strip()


def search_command_examples(query: str) -> tuple[tuple[CommandGroup, CommandExample], ...]:
    """Return curated entries matching every query token, preserving display order."""
    tokens = _normalize_search(query).split()
    matches = []
    for group in COMMAND_GROUPS:
        for example in group.examples:
            searchable = _normalize_search(" ".join((group.title, example.title, example.phrase, example.description)))
            if all(token in searchable for token in tokens):
                matches.append((group, example))
    return tuple(matches)
