from datetime import datetime
import tkinter as tk
from src.action_audit import default_audit


def open_action_audit(owner, button):
    panel = tk.Toplevel(owner)
    panel.title("Astra · журнал действий")
    panel.geometry("800x520")
    tk.Label(panel, text="Локально · последние 5000 событий · без текста команд, путей и содержимого файлов", wraplength=760).pack(pady=12)
    listing = tk.Listbox(panel, font=("Segoe UI", 10))
    listing.pack(fill="both", expand=True, padx=16)
    status = tk.StringVar()
    tk.Label(panel, textvariable=status).pack(pady=6)
    def refresh():
        try:
            rows = default_audit().recent()
            listing.delete(0, "end")
            labels = {"dispatch_allowed": "Передано на исполнение", "blocked": "Заблокировано", "succeeded": "Выполнено", "failed": "Ошибка", "cancelled": "Отменено"}
            for created, action, outcome, correlation in rows:
                listing.insert("end", f"{datetime.fromtimestamp(created):%d.%m %H:%M:%S} · {action} · {labels.get(outcome, outcome)} · {correlation[:8]}")
            status.set("Передача команды на исполнение не подтверждает успех её действия.")
        except Exception:
            status.set("Не удалось прочитать локальный журнал")
    button(panel, "Обновить", refresh).pack(pady=8)
    refresh()
    return panel
