from datetime import datetime
import tkinter as tk
from tkinter import ttk

from src.action_audit import default_audit
from src.desktop_theme import install_theme, BG, TEXT, MUTED, PANEL


OUTCOME_FILTERS = {
    "Все результаты": None,
    "Передано на исполнение": "dispatch_allowed",
    "Заблокировано": "blocked",
    "Выполнено": "succeeded",
    "Ошибка": "failed",
    "Отменено": "cancelled",
}

OUTCOME_LABELS = {
    "dispatch_allowed": "Передано на исполнение",
    "blocked": "Заблокировано",
    "succeeded": "Выполнено",
    "failed": "Ошибка",
    "cancelled": "Отменено",
}

ACTION_LABELS = {
    "files.create": "Создание файла",
    "files.copy": "Копирование файла",
    "files.move": "Перемещение файла",
    "files.rename": "Переименование файла",
    "files.create_folder": "Создание папки",
    "files.replace": "Замена файла",
    "files.trash": "Перемещение в корзину",
    "files.undo": "Отмена изменения",
    "files.recover": "Проверка восстановления",
    "files.search": "Поиск файлов",
    "files.read_text": "Чтение документа",
    "get_time": "Текущее время",
    "get_date": "Текущая дата",
    "open_app": "Открытие приложения",
    "close_app": "Закрытие приложения",
    "open_url": "Открытие сайта",
    "open_folder": "Открытие папки",
    "web_search": "Поиск в интернете",
    "keyboard_shortcut": "Сочетание клавиш",
    "media_control": "Управление музыкой",
    "type_text": "Ввод текста",
    "screenshot": "Снимок экрана",
    "system_info": "Сведения о системе",
    "vpn_control": "Управление VPN",
    "window_control": "Управление окном",
    "voice_feedback": "Голосовой ответ",
    "routine": "Сценарий",
    "reminder": "Напоминание",
    "clear_dialogue": "Новый диалог",
    "help": "Справка",
    "ask_llm": "Вопрос ассистенту",
    "exit": "Завершение работы",
}


def _normalize(value):
    return " ".join(str(value).casefold().replace("ё", "е").split())


def open_action_audit(owner, button):
    install_theme(owner)
    panel = tk.Toplevel(owner)
    panel.title("Astra · журнал действий")
    panel.geometry("900x620")
    panel.minsize(760, 500)
    panel.configure(bg=BG)
    tk.Label(panel, text="История действий", font=("Segoe UI", 20, "bold"), fg=TEXT).pack(
        anchor="w", padx=24, pady=(22, 5)
    )
    tk.Label(
        panel,
        text="Журнал хранится на этом компьютере. Текст команд, пути и содержимое файлов не записываются.",
        fg=MUTED,
        wraplength=830,
        justify="left",
    ).pack(anchor="w", padx=24, pady=(0, 16))

    filters = tk.Frame(panel, bg=BG)
    filters.pack(fill="x", padx=24, pady=(0, 12))
    tk.Label(filters, text="Найти", bg=BG, fg=MUTED).pack(side="left", padx=(0, 8))
    search_value = tk.StringVar()
    search = tk.Entry(
        filters,
        textvariable=search_value,
        bg="#242c46",
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground="#3a4261",
        highlightcolor="#9786ff",
    )
    search.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 16))
    tk.Label(filters, text="Результат", bg=BG, fg=MUTED).pack(side="left", padx=(0, 8))
    outcome_value = tk.StringVar(value="Все результаты")
    outcome_filter = ttk.Combobox(
        filters,
        textvariable=outcome_value,
        values=tuple(OUTCOME_FILTERS),
        state="readonly",
        width=25,
    )
    outcome_filter.pack(side="right")

    card = tk.Frame(panel, bg=PANEL)
    card.pack(fill="both", expand=True, padx=24)
    listing = ttk.Treeview(card, columns=("time", "action", "outcome"), show="headings", selectmode="browse")
    for name, title, width in (("time", "Время", 155), ("action", "Действие", 330), ("outcome", "Результат", 280)):
        listing.heading(name, text=title)
        listing.column(name, width=width, minwidth=105, stretch=name != "time")
    scroll = ttk.Scrollbar(card, orient="vertical", command=listing.yview)
    listing.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    listing.pack(side="left", fill="both", expand=True)
    status = tk.StringVar(value="Загрузка истории…")
    tk.Label(panel, textvariable=status, fg=MUTED, wraplength=830, justify="left").pack(
        anchor="w", padx=24, pady=(10, 4)
    )

    def refresh(*_args):
        try:
            rows = default_audit().recent(500)
            query = _normalize(search_value.get())
            outcome = OUTCOME_FILTERS.get(outcome_value.get())
            visible = []
            for created, action, result, _correlation in rows:
                action_label = ACTION_LABELS.get(action, action)
                result_label = OUTCOME_LABELS.get(result, result)
                if outcome is not None and result != outcome:
                    continue
                if query and query not in _normalize(f"{action_label} {action} {result_label} {result}"):
                    continue
                visible.append((created, action_label, result_label))

            existing = listing.get_children()
            if existing:
                listing.delete(*existing)
            for created, action_label, result_label in visible:
                listing.insert(
                    "",
                    "end",
                    values=(f"{datetime.fromtimestamp(created):%d.%m %H:%M:%S}", action_label, result_label),
                )
            status.set(
                f"Показано {len(visible)} из {len(rows)} последних событий. "
                "Передача команды на исполнение ещё не подтверждает успех её действия."
            )
        except Exception:
            status.set("Не удалось прочитать локальный журнал")

    search_value.trace_add("write", refresh)
    outcome_value.trace_add("write", refresh)
    button(panel, "Обновить", refresh).pack(pady=(5, 12))
    refresh()
    return panel
