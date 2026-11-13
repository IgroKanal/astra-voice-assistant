from datetime import datetime
import tkinter as tk
from tkinter import ttk
from src.action_audit import default_audit
from src.desktop_theme import install_theme, BG, TEXT, MUTED


def open_action_audit(owner, button):
    install_theme(owner)
    panel = tk.Toplevel(owner)
    panel.title("Astra · журнал действий")
    panel.geometry("850x580")
    panel.configure(bg=BG)
    tk.Label(panel, text="История действий", font=("Segoe UI", 20, "bold"), fg=TEXT).pack(anchor="w", padx=24, pady=(22, 5))
    tk.Label(panel, text="События хранятся на этом компьютере. Текст команд и документы сюда не попадают.", fg=MUTED, wraplength=790).pack(anchor="w", padx=24, pady=(0, 18))
    card = tk.Frame(panel)
    card.pack(fill="both", expand=True, padx=24)
    listing = ttk.Treeview(card, columns=("time", "action", "outcome"), show="headings", selectmode="browse")
    for name, title, width in (("time", "Время", 150), ("action", "Действие", 300), ("outcome", "Результат", 240)):
        listing.heading(name, text=title)
        listing.column(name, width=width, minwidth=100, stretch=name != "time")
    scroll = ttk.Scrollbar(card, orient="vertical", command=listing.yview)
    listing.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    listing.pack(side="left", fill="both", expand=True)
    status = tk.StringVar()
    tk.Label(panel, textvariable=status, fg=MUTED, wraplength=790).pack(padx=24, pady=12)
    def refresh():
        try:
            rows = default_audit().recent()
            existing = listing.get_children()
            if existing:
                listing.delete(*existing)
            labels = {"dispatch_allowed": "Передано на исполнение", "blocked": "Заблокировано", "succeeded": "Выполнено", "failed": "Ошибка", "cancelled": "Отменено"}
            for created, action, outcome, correlation in rows:
                names = {"files.create": "Создание файла", "files.copy": "Копирование", "files.move": "Перемещение", "files.rename": "Переименование", "files.create_folder": "Создание папки", "files.replace": "Замена файла", "files.trash": "Перемещение в корзину", "files.undo": "Отмена изменения", "files.recover": "Проверка восстановления", "files.search": "Поиск файлов", "files.read_text": "Чтение документа", "get_time": "Текущее время", "get_date": "Текущая дата", "open_app": "Открытие приложения", "close_app": "Закрытие приложения", "open_url": "Открытие сайта", "window_control": "Управление окном", "media_control": "Управление музыкой", "ask_llm": "Вопрос ассистенту", "exit": "Завершение работы"}
                listing.insert("", "end", values=(f"{datetime.fromtimestamp(created):%d.%m %H:%M:%S}", names.get(action, action), labels.get(outcome, outcome)))
            status.set("Передача команды на исполнение не подтверждает успех её действия.")
        except Exception:
            status.set("Не удалось прочитать локальный журнал")
    button(panel, "Обновить", refresh).pack(pady=8)
    refresh()
    return panel
