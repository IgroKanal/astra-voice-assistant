"""Windows desktop entry point. Launch using start_astra_app.vbs."""
from __future__ import annotations

import math
import json
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from src.desktop_bridge import DesktopBridge
from src.file_workspace import FileWorkspace
from src.personal_memory import PersonalMemory
from src.skill_executor import ActionPlan, SkillCall, SkillExecutor
from src.file_operations_ui import open_file_operations
from src.ai_settings_ui import open_ai_settings
from src.onboarding_ui import open_onboarding
from src.reminders import ReminderStore, ReminderWorker
from src.reminders_ui import open_reminders
from src.desktop_tray import DesktopTray, microphone_tooltip
from src.file_rag_ui import open_file_questions
from src.plan_ui import open_plan_ui
from src.desktop_settings import AVATAR_PROFILES, DEFAULT_AVATAR_ID, DesktopSettings
from src.onboarding_state import OnboardingState
from src.version import DISPLAY_VERSION

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BG = "#101322"
PANEL = "#191f34"
TEXT = "#e9ecff"
MUTED = "#a2abc9"
ACCENT = "#9786ff"


class AstraDesktop:
    def __init__(self, window: tk.Tk, reminder_store=None):
        self.window = window
        self.bridge = DesktopBridge(ROOT)
        self.tray = None
        self.reminder_store = reminder_store
        self.reminder_worker = None
        self.assistant_name, self.avatar_id = self.load_assistant_profile()
        self.onboarding_state = OnboardingState()
        try:
            self.onboarding_available = not DesktopSettings().path.exists() and not self.onboarding_state.dismissed()
        except Exception:
            self.onboarding_available = not DesktopSettings().path.exists()
        self.onboarding_banner = None
        self.avatar_photo = None
        self.avatar_photos = {}
        self.loaded_avatar_id = None
        self.loaded_avatar_speaking = None
        self.avatar_preview_session = None
        if reminder_store is not None:
            self.reminder_worker = ReminderWorker(reminder_store, self.bridge.emit)
            self.reminder_worker.start()
        self.busy = False
        self.mode_pending = False
        self.pending_mode = None
        self.closing = False
        self.closing_event = threading.Event()
        self.phase = 0.0
        window.title(f"{DISPLAY_VERSION} · персональный ассистент")
        icon = ROOT / "assets" / "branding" / "astra.ico"
        if icon.is_file():
            window.iconbitmap(str(icon))
        window.geometry("1040x720")
        window.minsize(840, 680)
        window.configure(bg=BG)
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.status = tk.StringVar(value="Запуск · микрофон выключен")
        self._build()
        self.switch("text")
        self.poll()
        self.animate()

    def button(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, bg="#2b3454", fg=TEXT,
                         activebackground=ACCENT, activeforeground=BG, relief="flat",
                         font=("Segoe UI", 10), padx=16, pady=10, cursor="hand2")

    @staticmethod
    def load_assistant_profile():
        try:
            profile = DesktopSettings().load()
            avatar_id = profile.avatar_id if profile.avatar_id in AVATAR_PROFILES else DEFAULT_AVATAR_ID
            return profile.assistant_name or AVATAR_PROFILES[avatar_id]["default_name"], avatar_id
        except Exception:
            return AVATAR_PROFILES[DEFAULT_AVATAR_ID]["default_name"], DEFAULT_AVATAR_ID

    def apply_settings(self):
        self.assistant_name, self.avatar_id = self.load_assistant_profile()
        self.avatar_name_label.set(self.assistant_name)
        self.loaded_avatar_id = None
        if DesktopSettings().path.exists():
            self.onboarding_available = False
            if self.onboarding_banner is not None:
                self.onboarding_banner.destroy()
                self.onboarding_banner = None
        self.switch("text")

    def open_ai_settings(self):
        return open_ai_settings(self.window, self.button, self.apply_settings, app=self)

    def open_onboarding(self):
        return open_onboarding(self.window, self.button, self.apply_settings)

    def dismiss_onboarding(self):
        if self.onboarding_banner is not None:
            self.onboarding_banner.pack_forget()
            try:
                self.onboarding_state.dismiss()
            except Exception as exc:
                self.append("Система", "Не удалось сохранить выбор первого запуска: " + str(exc))

    def _build(self):
        header = tk.Frame(self.window, bg=BG)
        header.pack(fill="x", padx=28, pady=(22, 16))
        tk.Label(header, text="ASTRA", font=("Segoe UI", 24, "bold"), bg=BG, fg=TEXT).pack(side="left")
        tk.Label(header, text=DISPLAY_VERSION.upper(), font=("Segoe UI", 9), bg=BG, fg=ACCENT).pack(side="left", padx=15)
        self.button(header, "Диагностика", self.diagnose).pack(side="right")
        from src.action_audit_ui import open_action_audit
        self.button(header, "Журнал", lambda: open_action_audit(self.window, self.button)).pack(side="right", padx=8)
        toolbar = tk.Frame(self.window, bg=BG)
        toolbar.pack(fill="x", padx=28, pady=(0, 12))
        self.button(toolbar, "Файлы", self.open_files).pack(side="left", padx=(0, 8))
        self.button(toolbar, "Память", self.open_memory).pack(side="left", padx=(0, 8))
        self.button(toolbar, "Задачи", self.open_tasks).pack(side="left", padx=(0, 8))
        self.button(toolbar, "ИИ, голос и разрешения", self.open_ai_settings).pack(side="left", padx=(0, 8))
        self.button(toolbar, "В системный трей", self.hide_to_tray).pack(side="right")
        if self.onboarding_available:
            self.onboarding_banner = tk.Frame(self.window, bg=PANEL, highlightbackground="#34304f", highlightthickness=1)
            self.onboarding_banner.pack(fill="x", padx=28, pady=(0, 12))
            onboarding_copy = tk.Frame(self.onboarding_banner, bg=PANEL)
            onboarding_copy.pack(side="left", fill="x", expand=True, padx=16, pady=10)
            tk.Label(onboarding_copy, text="Первый запуск Astra", font=("Segoe UI", 12, "bold"), bg=PANEL, fg=TEXT).pack(anchor="w")
            tk.Label(
                onboarding_copy,
                text="Выбери персонажа, имя и голос по желанию. Можно начать с текста: микрофон не включается сам.",
                wraplength=640, justify="left", bg=PANEL, fg=MUTED, font=("Segoe UI", 9),
            ).pack(anchor="w", pady=(3, 0))
            self.button(self.onboarding_banner, "Настроить", self.open_onboarding).pack(side="right", padx=(8, 8), pady=10)
            self.button(self.onboarding_banner, "Пока пропустить", self.dismiss_onboarding).pack(side="right", padx=(0, 8), pady=10)
        footer = tk.Frame(self.window, bg=BG)
        footer.pack(side="bottom", fill="x", padx=28, pady=14)
        for label, text in [("Время", "Астра, сколько времени"), ("Помощь", "Астра, помощь"), ("Дата", "Астра, какая сегодня дата")]:
            self.button(footer, label, lambda value=text: self.fill(value)).pack(side="left", padx=(0, 8))
        body = tk.Frame(self.window, bg=BG)
        body.pack(fill="both", expand=True, padx=28)
        side = tk.Frame(body, bg=PANEL, width=270)
        side.pack(side="left", fill="y", padx=(0, 18))
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(0, weight=1)
        self.avatar = tk.Canvas(side, bg=PANEL, height=250, width=260, highlightthickness=0)
        self.avatar.grid(row=0, column=0, sticky="nsew", pady=(8, 0))
        self.avatar_name_label = tk.StringVar(value=self.assistant_name)
        tk.Label(side, textvariable=self.avatar_name_label, font=("Segoe UI", 13, "bold"), bg=PANEL, fg=TEXT).grid(row=1, column=0, pady=3)
        tk.Label(side, textvariable=self.status, wraplength=230, font=("Segoe UI", 10), bg=PANEL, fg=MUTED).grid(row=2, column=0, padx=15, pady=6)
        self.button(side, "🎙  Голос · включить", lambda: self.switch("voice")).grid(row=3, column=0, sticky="ew", padx=12, pady=3)
        self.button(side, "⌨  Текст · микрофон выкл.", lambda: self.switch("text")).grid(row=4, column=0, sticky="ew", padx=12, pady=3)
        self.button(side, "Пауза", lambda: self.switch(None)).grid(row=5, column=0, sticky="ew", padx=12, pady=3)
        tk.Label(side, text="Голос включается кнопкой.\nДля команд говори «Астра».", wraplength=230, bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).grid(row=6, column=0, padx=12, pady=6)
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        conversation = tk.Frame(right, bg=PANEL)
        conversation.pack(fill="both", expand=True)
        self.chat = tk.Text(conversation, bg=PANEL, fg=TEXT, relief="flat", wrap="word",
                            font=("Segoe UI", 11), padx=18, pady=18, state="disabled")
        scrollbar = tk.Scrollbar(conversation, command=self.chat.yview)
        scrollbar.pack(side="right", fill="y")
        self.chat.configure(yscrollcommand=scrollbar.set)
        self.chat.pack(side="left", fill="both", expand=True)
        self.chat.tag_configure("user", foreground="#b5a9ff")
        self.chat.tag_configure("system", foreground=MUTED)
        self.chat.tag_configure("assistant", foreground=TEXT)
        row = tk.Frame(right, bg=BG)
        row.pack(side="bottom", before=conversation, fill="x", pady=(12, 0))
        self.entry = tk.Entry(row, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                              relief="flat", font=("Segoe UI", 12))
        self.entry.pack(side="left", fill="x", expand=True, ipady=12, padx=(0, 10))
        self.entry.bind("<Return>", lambda _event: self.send())
        self.button(row, "Отправить →", self.send).pack(side="right")
        self.append(self.assistant_name, f"Привет! Я готова помочь. Обращайся по имени «{self.assistant_name}». Микрофон по умолчанию выключен.")

    def append(self, who, text):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"{who}\n{text}\n\n", "user" if who == "Ты" else "assistant" if who == "Астра" else "system")
        if int(self.chat.index("end-1c").split(".")[0]) > 3000:
            self.chat.delete("1.0", "500.0")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def fill(self, value):
        self.entry.delete(0, "end")
        self.entry.insert(0, value)
        self.entry.focus_set()

    def hide_to_tray(self):
        if self.closing:
            return
        try:
            if self.tray is None:
                self.tray = DesktopTray(self.bridge.emit)
            self.tray.start()
            self.tray.set_tooltip(microphone_tooltip(
                self.bridge.mode if self.bridge.running else "text", self.status.get(),
            ))
            self.window.withdraw()
        except Exception:
            self.window.deiconify()
            self.status.set("Не удалось свернуть в трей · окно оставлено открытым")

    def show_from_tray(self):
        if not self.closing:
            self.window.deiconify()
            self.window.lift()

    def send(self):
        text = self.entry.get().strip()
        if not text:
            return
        try:
            self.bridge.send(text)
        except Exception as exc:
            self.append("Система", str(exc))
            return
        self.append("Ты", text)
        self.entry.delete(0, "end")

    def switch(self, mode):
        if self.closing:
            return
        if self.busy:
            self.pending_mode = mode
            self.mode_pending = True
            return
        self.busy = True
        self.status.set("Переключение режима…")
        bridge = self.bridge
        closing = self.closing_event
        def work():
            try:
                bridge.stop()
                if mode and not closing.is_set():
                    bridge.start(mode)
                else:
                    bridge.emit("status", "Пауза · микрофон выключен")
            except Exception as exc:
                bridge.emit("error", str(exc))
            finally:
                bridge.emit("ready", "")
        threading.Thread(target=work, daemon=True).start()

    def diagnose(self):
        self.append("Система", "Папка проекта: " + str(ROOT) + "\nРежим: " + self.bridge.mode + "\nПроцесс работает: " + str(self.bridge.running) + "\nПолный тест: tools/run_current_gate.ps1")

    def open_files(self):
        selected = filedialog.askdirectory(parent=self.window, title="Разрешить чтение выбранной папки на эту сессию")
        if not selected:
            return
        try:
            workspace = FileWorkspace(Path(selected))
        except Exception as exc:
            messagebox.showerror("Astra · файлы", str(exc), parent=self.window)
            return
        panel = tk.Toplevel(self.window)
        panel.title("Astra · файлы · только чтение")
        executor = SkillExecutor(workspace)
        panel.geometry("900x620")
        panel.configure(bg=BG)
        tk.Label(panel, text=str(workspace.root), bg=BG, fg=TEXT, font=("Segoe UI", 11), wraplength=850).pack(padx=20, pady=14)
        tk.Label(panel, text="Текстовые файлы, PDF, DOCX, XLSX и PPTX читаются локально. Выбери один файл или до пяти файлов с Ctrl/Shift для локального вопроса.", bg=BG, fg=MUTED, wraplength=850).pack()
        row = tk.Frame(panel, bg=BG)
        row.pack(fill="x", padx=20, pady=12)
        query = tk.Entry(row, bg=PANEL, fg=TEXT, insertbackground=TEXT, font=("Segoe UI", 11))
        query.pack(side="left", fill="x", expand=True, ipady=8)
        results = tk.Listbox(panel, selectmode="extended", bg=PANEL, fg=TEXT, selectbackground="#514583", font=("Segoe UI", 10), relief="flat")
        results.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        panel.astra_file_results = results
        status = tk.StringVar(value="")
        tk.Label(panel, textvariable=status, bg=BG, fg=MUTED, wraplength=850).pack(side="bottom", before=results, pady=8)
        panel.astra_files_status = status
        mailbox = queue.Queue()
        generation = [0]
        drain_timer = [None]
        def search():
            generation[0] += 1
            token = generation[0]
            value = query.get()
            status.set("Поиск…")
            def work():
                try:
                    result = executor.execute(ActionPlan((SkillCall("files.search", {"query": value}),)))[0]
                    if not result.ok:
                        raise ValueError(result.error)
                    mailbox.put((token, "files", result.value))
                except Exception as exc:
                    mailbox.put((token, "error", str(exc)))
            threading.Thread(target=work, daemon=True).start()
        def read(_event=None):
            selection = results.curselection()
            if not selection:
                return
            relative = results.get(selection[0])
            token = generation[0]
            def work():
                try:
                    if Path(relative).suffix.casefold() in workspace.IMAGE_SUFFIXES:
                        value = workspace.preview_image(relative)
                        mailbox.put((token, "image", (relative, value)))
                    else:
                        result = executor.execute(ActionPlan((SkillCall("files.read_text", {"path": relative}),)))[0]
                        if not result.ok:
                            raise ValueError(result.error)
                        mailbox.put((token, "text", (relative, result.value)))
                except Exception as exc:
                    mailbox.put((token, "error", str(exc)))
            threading.Thread(target=work, daemon=True).start()
        def drain():
            if not panel.winfo_exists():
                return
            for _ in range(20):
                try:
                    token, kind, value = mailbox.get_nowait()
                except queue.Empty:
                    break
                if token != generation[0]:
                    continue
                if kind == "files":
                    results.delete(0, "end")
                    for item in value:
                        results.insert("end", item.path)
                    status.set(f"Найдено: {len(value)} · до 500 результатов / 10000 файлов · двойной щелчок: читать документ")
                elif kind == "text":
                    viewer = tk.Toplevel(panel)
                    viewer.title(value[0])
                    viewer.geometry("800x560")
                    content = tk.Text(viewer, bg=PANEL, fg=TEXT, wrap="word", font=("Consolas", 11))
                    content.pack(fill="both", expand=True)
                    content.insert("1.0", value[1])
                    content.configure(state="disabled")
                elif kind == "image":
                    from io import BytesIO
                    from PIL import Image, ImageTk
                    relative, preview = value
                    viewer = tk.Toplevel(panel)
                    viewer.title("Astra · просмотр изображения · " + relative)
                    viewer.geometry("900x680")
                    image = Image.open(BytesIO(preview.png))
                    photo = ImageTk.PhotoImage(image, master=viewer)
                    label = tk.Label(viewer, image=photo, bg=PANEL)
                    label.image = photo
                    label.pack(fill="both", expand=True, padx=12, pady=8)
                    tk.Label(
                        viewer,
                        text=f"{preview.image_format} · {preview.original_width} × {preview.original_height} · локальный preview без отправки в ИИ",
                        bg=BG, fg=MUTED,
                    ).pack(pady=(0, 12))
                else:
                    status.set(value)
            drain_timer[0] = panel.after(80, drain)
        def close_files():
            if any(getattr(child, "astra_file_busy", [False])[0] for child in panel.winfo_children()):
                status.set("Дождись окончания файловой операции")
                return
            generation[0] += 1
            if drain_timer[0] is not None:
                panel.after_cancel(drain_timer[0])
            panel.destroy()
        panel.protocol("WM_DELETE_WINDOW", close_files)
        def destroyed(event):
            if event.widget == panel:
                generation[0] += 1
                if drain_timer[0] is not None:
                    panel.after_cancel(drain_timer[0])
                    drain_timer[0] = None
        panel.bind("<Destroy>", destroyed)
        self.button(row, "Найти", search).pack(side="right", padx=(10, 0))
        self.button(panel, "Операции с файлами · разрешения и восстановление", lambda: open_file_operations(panel, workspace, self.button)).pack(side="bottom", before=results, pady=6)
        self.button(panel, "План · симуляция и запуск разрешённых шагов", lambda: open_plan_ui(panel, workspace, self.button)).pack(side="bottom", before=results, pady=6)
        def ask_selected():
            selection = results.curselection()
            if selection:
                open_file_questions(panel, workspace, results.get(selection[0]), self.button)
            else:
                status.set("Выбери файл в списке")
        def ask_selected_many():
            selection = results.curselection()
            if not selection:
                status.set("Выбери от одного до пяти файлов в списке")
                return
            if len(selection) > 5:
                status.set("Для одного локального вопроса выбери не больше пяти файлов")
                return
            try:
                relatives = tuple(results.get(index) for index in selection)
                open_file_questions(panel, workspace, relatives, self.button)
            except Exception as exc:
                status.set(str(exc))
        self.button(panel, "Вопрос по выбранному файлу · локальный ИИ", ask_selected).pack(side="bottom", before=results, pady=6)
        self.button(panel, "Сравнить выбранные файлы · локальный ИИ", ask_selected_many).pack(side="bottom", before=results, pady=6)
        panel.astra_ask_selected_many = ask_selected_many
        panel.astra_open_selected = read
        query.bind("<Return>", lambda event: search())
        results.bind("<Double-Button-1>", read)
        search()
        drain()

    def open_tasks(self):
        try:
            if self.reminder_store is None:
                self.reminder_store = ReminderStore(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AstraVoiceAssistant" / "reminders.sqlite")
                self.reminder_worker = ReminderWorker(self.reminder_store, self.bridge.emit)
                self.reminder_worker.start()
            from src.desktop_settings import DesktopSettings
            open_reminders(self.window, self.reminder_store, self.button, allow_create=lambda: "reminders" in DesktopSettings().load().allowed_scopes)
        except Exception:
            self.append("Система", "Не удалось открыть локальные напоминания. Проверь базу и учётную запись Windows.")

    def open_memory(self):
        try:
            memory = PersonalMemory(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AstraVoiceAssistant" / "memory.sqlite")
        except Exception as exc:
            messagebox.showerror("Astra · память", str(exc), parent=self.window)
            return
        panel = tk.Toplevel(self.window)
        panel.title("Astra · личная память")
        panel.geometry("780x710")
        panel.configure(bg=BG)
        tk.Label(panel, text="Только явно сохранённые заметки · шифрование Windows DPAPI", bg=BG, fg=TEXT, font=("Segoe UI", 12)).pack(pady=(18, 6))
        tk.Label(panel, text="В облако не отправляется. Для локального диалога включи разрешение в «ИИ».", bg=BG, fg=MUTED).pack(pady=6)
        listing = tk.Listbox(panel, bg=PANEL, fg=TEXT, font=("Segoe UI", 11), relief="flat", height=7)
        listing.pack(fill="x", padx=20, pady=10)
        title = tk.Entry(panel, bg=PANEL, fg=TEXT, insertbackground=TEXT, font=("Segoe UI", 12))
        title.pack(fill="x", padx=20, ipady=8)
        title.insert(0, "Новая заметка")
        content = tk.Text(panel, bg=PANEL, fg=TEXT, insertbackground=TEXT, wrap="word", font=("Segoe UI", 11), relief="flat", height=10)
        content.pack(fill="both", expand=True, padx=20, pady=10)
        status = tk.StringVar()
        tk.Label(panel, textvariable=status, bg=BG, fg=MUTED).pack()
        notes = []
        def refresh():
            nonlocal notes
            try:
                notes = memory.search()
            except Exception:
                status.set("Не удалось расшифровать память. Проверь учётную запись Windows и резервную копию.")
                return
            listing.delete(0, "end")
            for note in notes:
                listing.insert("end", note.title)
            status.set(f"Сохранено: {len(notes)}. Пароли и API-ключи здесь не храни.")
        def select(_event=None):
            if listing.curselection():
                note = notes[listing.curselection()[0]]
                title.delete(0, "end")
                title.insert(0, note.title)
                content.delete("1.0", "end")
                content.insert("1.0", note.text)
        def save():
            try:
                memory.add(title.get(), content.get("1.0", "end-1c"))
                refresh()
                status.set("Новая запись сохранена. Существующие записи не перезаписываются.")
            except Exception as exc:
                status.set(str(exc))
        def forget():
            selection = listing.curselection()
            if selection and messagebox.askyesno("Забыть запись?", "Удалить выбранную запись из памяти Astra?", parent=panel):
                memory.forget(notes[selection[0]].id)
                refresh()
                title.delete(0, "end")
                content.delete("1.0", "end")
        def backup():
            chosen = filedialog.asksaveasfilename(
                parent=panel, title="Создать резервную копию памяти",
                defaultextension=".astra-memory.json",
                filetypes=[("Резервная копия Astra", "*.astra-memory.json"), ("JSON", "*.json")],
            )
            if not chosen:
                return
            try:
                count = memory.create_backup(Path(chosen))
                status.set(f"Резервная копия создана: {count} записей. Данные зашифрованы для этой учётной записи Windows.")
            except Exception as exc:
                messagebox.showerror("Astra · резервная копия", str(exc), parent=panel)
        def restore():
            chosen = filedialog.askopenfilename(
                parent=panel, title="Выбери резервную копию памяти Astra",
                filetypes=[("Резервная копия Astra", "*.astra-memory.json *.json"), ("Все файлы", "*.*")],
            )
            if not chosen:
                return
            try:
                new_count, conflicts = memory.preview_restore(Path(chosen))
            except Exception as exc:
                messagebox.showerror("Astra · восстановление", str(exc), parent=panel)
        def portable_backup():
            chosen = filedialog.asksaveasfilename(
                parent=panel, title="Создать переносимую зашифрованную копию",
                defaultextension=".astra-memory-portable",
                filetypes=[("Переносимая память Astra", "*.astra-memory-portable"), ("Все файлы", "*.*")],
            )
            if not chosen:
                return
            passphrase = simpledialog.askstring("Парольная фраза", "Задай парольную фразу (от 12 символов). Запиши её отдельно: восстановить файл без неё нельзя.", show="•", parent=panel)
            if passphrase is None:
                return
            confirmation = simpledialog.askstring("Подтверждение парольной фразы", "Введи парольную фразу ещё раз.", show="•", parent=panel)
            if confirmation is None:
                return
            if passphrase != confirmation:
                messagebox.showerror("Astra · перенос памяти", "Парольные фразы не совпадают.", parent=panel)
                return
            try:
                count = memory.create_portable_backup(Path(chosen), passphrase)
                status.set(f"Переносимая копия создана: {count} записей. Храни пароль отдельно от файла.")
            except Exception as exc:
                messagebox.showerror("Astra · перенос памяти", str(exc), parent=panel)
            finally:
                passphrase = confirmation = None
        def portable_restore():
            chosen = filedialog.askopenfilename(
                parent=panel, title="Выбери переносимую копию памяти Astra",
                filetypes=[("Переносимая память Astra", "*.astra-memory-portable"), ("Все файлы", "*.*")],
            )
            if not chosen:
                return
            passphrase = simpledialog.askstring("Парольная фраза", "Введи парольную фразу от переносимой копии.", show="•", parent=panel)
            if passphrase is None:
                return
            try:
                source = Path(chosen)
                new_count, conflicts = memory.preview_portable_restore(source, passphrase)
            except Exception as exc:
                messagebox.showerror("Astra · перенос памяти", str(exc), parent=panel)
                return
            summary = (f"Будет добавлено новых записей: {new_count}.\n"
                       f"Совпадающих ID без перезаписи: {conflicts}.\n\n"
                       "Записи будут зашифрованы для этой учётной записи Windows. Продолжить?")
            if not messagebox.askyesno("Проверка переносимого восстановления", summary, parent=panel):
                passphrase = None
                return
            try:
                restored, skipped = memory.restore_portable_backup(source, passphrase)
                refresh()
                status.set(f"Перенесено: {restored}. Пропущено совпадений: {skipped}.")
            except Exception as exc:
                messagebox.showerror("Astra · перенос памяти", str(exc), parent=panel)
            finally:
                passphrase = None
                return
            summary = (f"Будет добавлено новых записей: {new_count}.\n"
                       f"Совпадающих ID без перезаписи: {conflicts}.\n\n"
                       "Текущие записи останутся без изменений. Продолжить?")
            if not messagebox.askyesno("Проверка восстановления", summary, parent=panel):
                return
            try:
                restored, skipped = memory.restore_backup(Path(chosen))
                refresh()
                status.set(f"Добавлено: {restored}. Пропущено совпадений: {skipped}; текущие записи не перезаписаны.")
            except Exception as exc:
                messagebox.showerror("Astra · восстановление", str(exc), parent=panel)
        row = tk.Frame(panel, bg=BG)
        row.pack(pady=12)
        self.button(row, "Сохранить новую", save).pack(side="left", padx=6)
        self.button(row, "Забыть выбранную", forget).pack(side="left", padx=6)
        backup_row = tk.Frame(panel, bg=BG)
        backup_row.pack(pady=(0, 12))
        self.button(backup_row, "Создать резервную копию", backup).pack(side="left", padx=6)
        self.button(backup_row, "Восстановить из копии", restore).pack(side="left", padx=6)
        portable_row = tk.Frame(panel, bg=BG)
        portable_row.pack(pady=(0, 12))
        self.button(portable_row, "Создать переносимую копию", portable_backup).pack(side="left", padx=6)
        self.button(portable_row, "Восстановить переносимую копию", portable_restore).pack(side="left", padx=6)
        listing.bind("<<ListboxSelect>>", select)
        refresh()

    def poll(self):
        for _ in range(120):
            try:
                kind, text = self.bridge.events.get_nowait()
            except queue.Empty:
                break
            if kind == "ready":
                self.busy = False
                if self.tray is not None:
                    self._refresh_tray_tooltip()
                if self.mode_pending and not self.closing:
                    mode = self.pending_mode
                    self.mode_pending = False
                    self.switch(mode)
            elif kind == "status":
                self.status.set(text)
                self._refresh_tray_tooltip()
            elif kind == "tray_show":
                self.show_from_tray()
            elif kind == "tray_mode":
                self.switch(text)
            elif kind == "tray_exit":
                self.show_from_tray()
                self.close()
            elif kind == "tray_error":
                self.show_from_tray()
                self.append("Система", text)
            elif kind == "state":
                self.status.set(text)
                self._refresh_tray_tooltip()
            elif kind == "assistant":
                self.append(self.assistant_name, text)
                if self.bridge.mode == "text":
                    self.status.set("Текстовый режим · микрофон выключен")
                self._refresh_tray_tooltip()
            elif kind == "transcript":
                self.append("Ты · голос", text)
            elif kind == "reminder":
                if not self.closing and self.reminder_store is not None:
                    try:
                        item = json.loads(text)
                        if self.reminder_store.valid_claim(item["id"], item["token"]):
                            if self.reminder_store.acknowledge(item["id"], item["token"]):
                                self.append("Напоминание", item["text"])
                                self.status.set("Новое напоминание · открой чат Astra")
                                if self.tray is not None:
                                    self.tray.notify()
                    except Exception:
                        self.append("Система", "Не удалось доставить напоминание; оно будет повторено после истечения срока доставки.")
            elif kind == "reminder_error":
                self.append("Система", text)
            elif kind == "reminder_count":
                count = int(text)
                self.window.title(f"{DISPLAY_VERSION} · персональный ассистент" + (f" · напоминаний: {count}" if count else ""))
            elif kind == "error":
                self.status.set("Ошибка · смотри журнал")
                self.append("Система", text)
            elif kind == "exit":
                if not self.busy and not self.bridge.running:
                    self.status.set("Остановлена · микрофон выключен")
            elif kind == "output":
                text = text.removeprefix("Ты: ")
                if text.startswith("Астра: "):
                    self.append(self.assistant_name, text[7:])
                elif "|" not in text and text and self.bridge.mode == "voice":
                    self.append("Система", text)
                elif "| ERROR" in text or "| WARNING" in text:
                    self.append("Система", text)
        self.poll_timer = self.window.after(60, self.poll)

    def _refresh_tray_tooltip(self):
        if self.tray is None:
            return
        mode = self.bridge.mode if self.bridge.running else "text"
        self.tray.set_tooltip(microphone_tooltip(mode, self.status.get()))

    def animate(self):
        self.phase += 0.055
        c = self.avatar
        c.delete("all")
        y = 124 + math.sin(self.phase) * 5
        color = ACCENT if self.bridge.running else MUTED
        speaking = "Говорю" in self.status.get()
        thinking = "Распознаю" in self.status.get() or self.busy
        preview_session = self.avatar_preview_session
        if preview_session is not None:
            if preview_session.poll() is None:
                preview_session.set_state(self.avatar_state())
            else:
                self.avatar_preview_session = None
        if thinking:
            color = "#f1c883"
        if self.loaded_avatar_id != self.avatar_id:
            self.loaded_avatar_id = self.avatar_id
            resource_root = Path(getattr(sys, "_MEIPASS", ROOT))
            profile = AVATAR_PROFILES[self.avatar_id]
            for frame, image_name in (
                (False, profile["asset"]),
                (True, profile.get("speaking_asset") or profile["asset"]),
            ):
                try:
                    image_path = resource_root / "assets" / "avatars" / image_name
                    image = tk.PhotoImage(master=c, file=str(image_path))
                    factor = max(1, max(image.width(), image.height()) // 250)
                    self.avatar_photos[(self.avatar_id, frame)] = image.subsample(factor, factor)
                except Exception:
                    if frame:
                        self.avatar_photos[(self.avatar_id, frame)] = self.avatar_photos.get(
                            (self.avatar_id, False)
                        )
                    else:
                        self.avatar_photos[(self.avatar_id, frame)] = None
        mouth_open = speaking and math.sin(self.phase * 9) > 0
        self.loaded_avatar_speaking = speaking
        self.avatar_photo = self.avatar_photos.get((self.avatar_id, mouth_open))
        pulse = 2 + abs(math.sin(self.phase * (2 if speaking else 1))) * 3
        c.create_oval(30-pulse, y-115-pulse, 230+pulse, y+115+pulse, outline=color, width=2)
        if self.avatar_photo is not None:
            c.create_image(130, y, image=self.avatar_photo, anchor="center")
            if speaking:
                for index in range(3):
                    height = 5 + abs(math.sin(self.phase * 4 + index)) * 14
                    x = 108 + index * 22
                    c.create_line(x, 235, x, 235-height, fill=color, width=3, capstyle="round")
        else:
            c.create_oval(65, y-72, 195, y+72, fill="#292c50", outline=color, width=3)
            blink = math.sin(self.phase / 2) > 0.995
            for x in (105, 155):
                c.create_oval(x-7, y-14, x+7, y+(0 if blink else 8), fill="#c5bdff", outline="")
            if speaking:
                opening = 5 + abs(math.sin(self.phase * 5)) * 12
                c.create_oval(114, y+16, 146, y+16+opening, fill=color, outline="")
            else:
                c.create_arc(108, y+10, 152, y+35, start=200, extent=140, outline=color, style="arc", width=3)
        width, height = max(1, c.winfo_width()), max(1, c.winfo_height())
        scale = min(width / 260, height / 250)
        c.scale("all", 0, 0, scale, scale)
        c.move("all", (width - 260 * scale) / 2, (height - 250 * scale) / 2)
        self.animation_timer = self.window.after(40, self.animate)

    def avatar_state(self):
        status = self.status.get().casefold()
        if "ошибка" in status:
            return "error"
        if "говор" in status:
            return "speaking"
        if "слуш" in status:
            return "listening"
        if "распозн" in status or "дума" in status or self.busy:
            return "recognizing"
        return "idle"

    def close(self):
        if self.closing:
            return
        pending = list(self.window.winfo_children())
        while pending:
            widget = pending.pop()
            if getattr(widget, "astra_file_busy", [False])[0]:
                self.status.set("Дождись окончания файловой операции перед закрытием")
                return
            pending.extend(widget.winfo_children())
        self.closing = True
        self.closing_event.set()
        if self.avatar_preview_session is not None:
            self.avatar_preview_session.close()
            self.avatar_preview_session = None
        self.bridge.prevent_restart()
        self.status.set("Завершение…")
        bridge = self.bridge
        reminder_worker = self.reminder_worker
        tray = self.tray
        def finish():
            bridge.stop()
            if reminder_worker is not None:
                reminder_worker.stop()
            if tray is not None:
                tray.stop()
            bridge.emit("closed", "")
        threading.Thread(target=finish, daemon=True).start()
        self.wait_close()

    def wait_close(self):
        if self.bridge.process is None and not self.busy and (self.reminder_worker is None or not self.reminder_worker.thread.is_alive()) and (self.tray is None or self.tray.thread is None or not self.tray.thread.is_alive()):
            for timer in (self.poll_timer, self.animation_timer):
                self.window.after_cancel(timer)
            self.window.destroy()
        else:
            self.window.after(100, self.wait_close)


if __name__ == "__main__":
    os.chdir(ROOT)
    window = tk.Tk()
    try:
        try:
            reminder_store = ReminderStore(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AstraVoiceAssistant" / "reminders.sqlite")
        except Exception:
            reminder_store = None
        AstraDesktop(window, reminder_store=reminder_store)
        window.mainloop()
    except Exception as exc:
        messagebox.showerror("Astra", str(exc))
        raise
