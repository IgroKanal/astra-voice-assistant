from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from src.desktop_theme import install_theme


def open_reminders(owner, store, button, allow_create=lambda: True):
    install_theme(owner)
    panel = tk.Toplevel(owner)
    panel.title("Astra · напоминания")
    panel.geometry(f"900x{min(720, max(600, owner.winfo_screenheight() - 100))}")
    panel.minsize(800, 600)
    panel.configure(bg="#101322")
    tk.Label(panel, text="Мои задачи", font=("Segoe UI", 21, "bold")).pack(anchor="w", padx=22, pady=(20, 4))
    tk.Label(panel, text="Напоминания работают, пока Astra запущена. Просроченные будут доставлены при следующем запуске.", bg="#101322", fg="#a2abc9", wraplength=840).pack(anchor="w", padx=22, pady=(0, 14))
    text = tk.Entry(panel, bg="#191f34", fg="#e9ecff", insertbackground="#e9ecff", font=("Segoe UI", 12))
    text.pack(fill="x", padx=22, ipady=9)
    text.insert(0, "О чём напомнить")
    tk.Label(panel, text="Время Windows: ГГГГ-ММ-ДД ЧЧ:ММ", bg="#101322", fg="#a2abc9").pack(pady=(15, 3))
    due = tk.Entry(panel, font=("Segoe UI", 12))
    due.pack(fill="x", padx=22, ipady=6)
    due.insert(0, (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M"))
    table_card = tk.Frame(panel)
    table_card.pack(fill="both", expand=True, padx=22, pady=14)
    listing = ttk.Treeview(table_card, columns=("due", "state", "text"), show="headings", selectmode="browse", height=6)
    for column, label, width in (("due", "Срок", 150), ("state", "Статус", 140), ("text", "Напоминание", 450)):
        listing.heading(column, text=label)
        listing.column(column, width=width, minwidth=100, stretch=column == "text")
    scrollbar = ttk.Scrollbar(table_card, orient="vertical", command=listing.yview)
    listing.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    listing.pack(side="left", fill="both", expand=True)
    detail = tk.StringVar(value="Выбери задачу, чтобы прочитать её полностью.")
    detail_card = tk.Frame(panel)
    detail_card.pack(side="bottom", before=table_card, fill="x", padx=22)
    detail_text = tk.Text(detail_card, height=3, bg="#191f34", fg="#e9ecff", font=("Segoe UI", 10), wrap="word", relief="flat", padx=12, pady=8)
    detail_scroll = ttk.Scrollbar(detail_card, orient="vertical", command=detail_text.yview)
    detail_text.configure(yscrollcommand=detail_scroll.set)
    detail_scroll.pack(side="right", fill="y")
    detail_text.pack(side="left", fill="x", expand=True)
    def show_detail(*_):
        detail_text.configure(state="normal")
        detail_text.delete("1.0", "end")
        detail_text.insert("1.0", detail.get())
        detail_text.configure(state="disabled")
    detail.trace_add("write", show_detail)
    show_detail()
    status = tk.StringVar()
    tk.Label(panel, textvariable=status, bg="#101322", fg="#a2abc9", wraplength=840).pack(side="bottom", before=table_card, pady=6)
    records = []
    def refresh():
        nonlocal records
        try:
            records = store.list()
            selection = listing.selection()
            if listing.get_children():
                listing.delete(*listing.get_children())
            names = {"pending": "Ожидает", "delivering": "Доставка", "delivered": "Не прочитано", "completed": "Прочитано", "cancelled": "Отменено"}
            for record in records:
                listing.insert("", "end", iid=record.id, values=(f"{datetime.fromtimestamp(record.due):%d.%m %H:%M}", names[record.state], record.text.replace("\n", " ")[:120]))
            if selection and listing.exists(selection[0]):
                listing.selection_set(selection[0])
            elif not records:
                detail.set("Пока нет задач. Введи напоминание и выбери время выше.")
            else:
                detail.set("Выбери задачу, чтобы прочитать её полностью.")
            status.set(f"Всего: {len(records)} · ожидают: {sum(record.state in {'pending', 'delivering'} for record in records)} · текст зашифрован локально")
        except Exception:
            status.set("Не удалось прочитать напоминания")
    def add():
        try:
            if not allow_create():
                raise ValueError("Создание напоминаний отключено в разрешениях")
            timestamp = datetime.strptime(due.get().strip(), "%Y-%m-%d %H:%M").timestamp()
            if timestamp <= datetime.now().timestamp():
                raise ValueError("Выбери будущее время")
            store.add(text.get(), timestamp)
            refresh()
        except ValueError as exc:
            status.set(str(exc))
        except Exception:
            status.set("Не удалось сохранить напоминание")
    def cancel():
        selection = listing.selection()
        if selection and messagebox.askyesno("Отмена", "Отменить выбранное напоминание?", parent=panel):
            try:
                changed = store.cancel(selection[0])
                refresh()
                if not changed:
                    status.set("Статус изменился: напоминание уже доставлено или отменено")
            except Exception:
                status.set("Не удалось отменить напоминание")
    def complete():
        selection = listing.selection()
        if selection:
            try:
                store.complete(selection[0])
                refresh()
            except Exception:
                status.set("Не удалось изменить статус напоминания")
    def portable_backup():
        chosen = filedialog.asksaveasfilename(
            parent=panel, title="Создать переносимую копию напоминаний",
            defaultextension=".astra-reminders-portable",
            filetypes=[("Переносимые напоминания Astra", "*.astra-reminders-portable"), ("Все файлы", "*.*")],
        )
        if not chosen:
            return
        phrase = simpledialog.askstring("Парольная фраза", "Задай пароль от 12 символов и сохрани отдельно: без него копию не восстановить.", show="•", parent=panel)
        if phrase is None:
            return
        confirmation = simpledialog.askstring("Подтверждение парольной фразы", "Введи парольную фразу ещё раз.", show="•", parent=panel)
        if confirmation is None:
            return
        if phrase != confirmation:
            messagebox.showerror("Astra · перенос", "Парольные фразы не совпадают.", parent=panel)
            return
        try:
            count = store.create_portable_backup(Path(chosen), phrase)
            status.set(f"Переносимая копия создана: {count} ожидающих/непрочитанных напоминаний.")
        except Exception as exc:
            messagebox.showerror("Astra · перенос", str(exc), parent=panel)
        finally:
            phrase = confirmation = None
    def portable_restore():
        chosen = filedialog.askopenfilename(
            parent=panel, title="Выбери переносимую копию напоминаний Astra",
            filetypes=[("Переносимые напоминания Astra", "*.astra-reminders-portable"), ("Все файлы", "*.*")],
        )
        if not chosen:
            return
        phrase = simpledialog.askstring("Парольная фраза", "Введи парольную фразу от копии.", show="•", parent=panel)
        if phrase is None:
            return
        source = Path(chosen)
        try:
            new_count, conflicts = store.preview_portable_restore(source, phrase)
        except Exception as exc:
            messagebox.showerror("Astra · перенос", str(exc), parent=panel)
            return
        summary = (f"Будет добавлено новых напоминаний: {new_count}.\n"
                   f"Совпадающих ID без перезаписи: {conflicts}.\n\n"
                   "Статусы доставки будут безопасно восстановлены, текст получит DPAPI-шифрование этого ПК. Продолжить?")
        if not messagebox.askyesno("Проверка переноса", summary, parent=panel):
            phrase = None
            return
        try:
            restored, skipped = store.restore_portable_backup(source, phrase)
            refresh()
            status.set(f"Перенесено: {restored}. Пропущено совпадений: {skipped}.")
        except Exception as exc:
            messagebox.showerror("Astra · перенос", str(exc), parent=panel)
        finally:
            phrase = None
    actions = tk.Frame(panel, bg="#101322")
    actions.pack(side="bottom", before=table_card, pady=10)
    button(actions, "Добавить", add).pack(side="left", padx=4)
    button(actions, "Отменить выбранное", cancel).pack(side="left", padx=4)
    button(actions, "Обновить", refresh).pack(side="left", padx=4)
    button(actions, "Прочитано", complete).pack(side="left", padx=4)
    portable_actions = tk.Frame(panel, bg="#101322")
    portable_actions.pack(side="bottom", before=actions, pady=(0, 8))
    button(portable_actions, "Экспорт переносимой копии…", portable_backup).pack(side="left", padx=5)
    button(portable_actions, "Импорт переносимой копии…", portable_restore).pack(side="left", padx=5)
    def selected(_event=None):
        choice = listing.selection()
        if choice:
            record = next((item for item in records if item.id == choice[0]), None)
            if record:
                detail.set(record.text)
    listing.bind("<<TreeviewSelect>>", selected)
    refresh()
    return panel
