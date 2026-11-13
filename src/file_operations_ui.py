"""Explicit per-window write grant and review/confirm file operations."""
import queue
import threading
import tkinter as tk
from tkinter import messagebox

from src.file_transactions import FileTransactions


def open_file_operations(owner, workspace, button):
    panel = tk.Toplevel(owner)
    panel.title("Astra · файловые операции")
    panel.geometry("850x720")
    panel.configure(bg="#101322")
    from src.action_audit import record_action
    transactions = FileTransactions(workspace, audit=record_action)
    enabled = tk.BooleanVar(value=False)
    status = tk.StringVar(value="Запись выключена. Разрешение действует только в этом окне.")
    tk.Label(panel, text=str(workspace.root), bg="#101322", fg="#e9ecff", wraplength=800).pack(pady=12)
    tk.Checkbutton(panel, text="Разрешаю создание, копирование, перемещение и замену в этой папке", variable=enabled,
                   command=lambda: transactions.grant_write(enabled.get()), bg="#101322", fg="#e9ecff",
                   selectcolor="#191f34", activebackground="#101322", activeforeground="#e9ecff").pack(pady=8)
    trash_enabled = tk.BooleanVar(value=False)
    tk.Checkbutton(panel, text="Отдельно разрешаю отправлять выбранные файлы в Корзину Windows", variable=trash_enabled,
                   command=lambda: transactions.grant_trash(trash_enabled.get()), bg="#101322", fg="#e9ecff",
                   selectcolor="#191f34", activebackground="#101322", activeforeground="#e9ecff").pack(pady=4)
    def open_local_planner():
        from src.plan_ui import open_plan_ui
        open_plan_ui(panel, workspace, button, transactions=transactions)
    button(panel, "Составить план копирования/перемещения локальным ИИ", open_local_planner).pack(anchor="w", padx=20, pady=(2, 8))
    def entry(label):
        tk.Label(panel, text=label, bg="#101322", fg="#a2abc9").pack(anchor="w", padx=20)
        field = tk.Entry(panel, bg="#191f34", fg="#e9ecff", insertbackground="#e9ecff", font=("Segoe UI", 11))
        field.pack(fill="x", padx=20, pady=(0, 10), ipady=6)
        return field
    source = entry("Источник — относительный путь (для копирования/перемещения)")
    destination = entry("Назначение — относительный путь (для переименования укажи новое имя)")
    tk.Label(panel, text="Текст нового содержимого (только для создания/замены)", bg="#101322", fg="#a2abc9").pack(anchor="w", padx=20)
    content = tk.Text(panel, bg="#191f34", fg="#e9ecff", insertbackground="#e9ecff", height=8, font=("Consolas", 11))
    content.pack(fill="both", expand=True, padx=20, pady=8)
    footer = tk.Frame(panel, bg="#101322")
    footer.pack(side="bottom", before=content, fill="x")
    actions = tk.Frame(footer, bg="#101322")
    actions.pack(pady=8)
    mailbox = queue.Queue()
    busy = [False]
    panel.astra_file_busy = busy
    timer = [None]
    history_items = []
    history = tk.Listbox(footer, bg="#191f34", fg="#e9ecff", height=4, font=("Segoe UI", 10))
    history.pack(fill="x", padx=20, pady=6)
    tk.Label(footer, textvariable=status, wraplength=800, bg="#101322", fg="#a2abc9").pack(side="bottom", padx=20, pady=6)
    recovery_actions = tk.Frame(footer, bg="#101322")
    recovery_actions.pack(pady=5)
    def background(operation):
        if busy[0]:
            return
        busy[0] = True
        def work():
            try:
                result = operation()
                try:
                    records = transactions.history()
                except Exception:
                    mailbox.put((True, result + "; список журнала недоступен — проверь .astra-history", []))
                else:
                    mailbox.put((True, result, records))
            except Exception as exc:
                mailbox.put((False, str(exc), None))
        threading.Thread(target=work, daemon=True).start()
    def perform(kind):
        if busy[0]:
            return
        try:
            preview = transactions.preview(kind, source.get().strip() if kind in {"copy", "move"} else "", destination.get().strip(), content.get("1.0", "end-1c") if kind in {"create", "replace"} else "")
            origin = "новая папка" if kind == "mkdir" else preview.source or "новый текст"
            summary = f"Операция: {kind}\nИсточник: {origin}\nНазначение: {preview.destination}\nОбъём: {preview.size} байт\n\nИзменения ограничены выбранной папкой. Заменяемый файл сохраняется для восстановления. Выполнить?"
            if messagebox.askyesno("Astra · предварительный просмотр", summary, parent=panel):
                background(lambda: "Выполнено · " + transactions.execute(preview.token))
        except Exception as exc:
            status.set(str(exc))
    def trash_selected():
        if busy[0]:
            return
        try:
            preview = transactions.preview("trash", source=source.get().strip())
            summary = (f"В Корзину Windows будет перемещён файл:\n{preview.source}\n"
                       f"Размер: {preview.size} байт.\n\nAstra не удаляет его навсегда. Продолжить?")
            if messagebox.askyesno("Astra · перемещение в Корзину", summary, parent=panel):
                background(lambda: transactions.execute_trash(preview.token))
        except Exception as exc:
            status.set(str(exc))
    def undo():
        if busy[0] or not history.curselection():
            return
        record = history_items[history.curselection()[0]]
        if messagebox.askyesno("Восстановление", f"Отменить {record['operation']} → {record['destination']}?\nИзменённый после операции файл не будет перезаписан.", parent=panel):
            background(lambda: (transactions.undo(record["id"]) or "Операция отменена; созданные файлы и пустые папки сохранены в .astra-history"))
    for label, kind in [("Создать файл", "create"), ("Создать папку", "mkdir"), ("Заменить текст", "replace"), ("Копировать", "copy"), ("Переместить / переименовать", "move")]:
        button(actions, label, lambda value=kind: perform(value)).pack(side="left", padx=3)
    button(actions, "В Корзину", trash_selected).pack(side="left", padx=3)
    button(recovery_actions, "Отменить выбранную операцию", undo).pack(side="left", padx=4)
    def recover():
        if busy[0] or not history.curselection():
            return
        record = history_items[history.curselection()[0]]
        if record.get("status") not in {"prepared", "undo_prepared"}:
            status.set("Выбери незавершённую операцию prepared/undo_prepared")
            return
        if messagebox.askyesno("Проверка после аварии", "Сверить файлы и обновить статус журнала? Содержимое файлов изменяться не будет. Выполненную операцию затем можно отдельно отменить.", parent=panel):
            background(lambda: "Состояние проверено: " + transactions.recover(record["id"]))
    button(recovery_actions, "Проверить незавершённую операцию", recover).pack(side="left", padx=4)
    def poll():
        nonlocal history_items
        if not panel.winfo_exists():
            return
        try:
            ok, message, records = mailbox.get_nowait()
            busy[0] = False
            status.set(message)
            if ok:
                history_items = records
                history.delete(0, "end")
                for record in records:
                    history.insert("end", f"{record['status']} · {record['operation']} → {record['destination']}")
        except queue.Empty:
            pass
        timer[0] = panel.after(80, poll)
    def close():
        if busy[0]:
            status.set("Дождись окончания текущей операции перед закрытием")
            return
        transactions.grant_write(False)
        transactions.grant_trash(False)
        if timer[0] is not None:
            panel.after_cancel(timer[0])
        panel.destroy()
    panel.protocol("WM_DELETE_WINDOW", close)
    def destroyed(event):
        if event.widget == panel:
            transactions.grant_write(False)
            transactions.grant_trash(False)
            if timer[0] is not None:
                panel.after_cancel(timer[0])
                timer[0] = None
    panel.bind("<Destroy>", destroyed)
    background(lambda: "Готово. Запись по умолчанию выключена.")
    poll()
    return panel
