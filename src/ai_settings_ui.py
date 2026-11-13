"""AI configuration without editing environment files or exposing saved keys."""
import queue
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from src.desktop_settings import AIProfile, AVATAR_PROFILES, DEFAULT_AVATAR_ID, DesktopSettings
from src.profile_backup import export_profile, import_profile
from src.action_policy import ALL_SCOPES
from src.ollama_client import OllamaClient
from src.version import DISPLAY_VERSION


def open_ai_settings(owner, button, on_saved, app=None):
    store = DesktopSettings()
    panel = tk.Toplevel(owner)
    panel.title("Astra · настройки ИИ")
    panel.geometry("780x820")
    panel.configure(bg="#101322")
    tabs = ttk.Notebook(panel)
    tabs.pack(fill="both", expand=True, padx=12, pady=12)
    content = tk.Frame(tabs, bg="#101322")
    voice_tab = tk.Frame(tabs, bg="#101322")
    permissions = tk.Frame(tabs, bg="#101322")
    tabs.add(content, text="ИИ и память")
    tabs.add(voice_tab, text="Голос и микрофон")
    tabs.add(permissions, text="Разрешения навыков")
    profile_load_failed = False
    try:
        profile = store.load()
    except Exception:
        profile = AIProfile()
        profile_load_failed = True
    tk.Label(voice_tab, text=f"{DISPLAY_VERSION} · голос Windows", bg="#101322", fg="#e9ecff", font=("Segoe UI", 17)).pack(pady=18)
    tk.Label(voice_tab, text="2D-образ ассистента · персонажа можно просмотреть до сохранения", bg="#101322", fg="#a2abc9").pack(anchor="w", padx=24)
    avatar_labels = {item["label"]: identity for identity, item in AVATAR_PROFILES.items()}
    initial_avatar = profile.avatar_id if profile.avatar_id in AVATAR_PROFILES else DEFAULT_AVATAR_ID
    avatar_row = tk.Frame(voice_tab, bg="#101322")
    avatar_row.pack(fill="x", padx=24, pady=(2, 6))
    avatar = ttk.Combobox(avatar_row, values=tuple(avatar_labels), state="readonly", font=("Segoe UI", 11))
    avatar.pack(side="left", fill="x", expand=True, padx=(0, 12))
    preview_card = tk.Frame(avatar_row, bg="#191f34", width=92, height=82)
    preview_card.pack(side="right")
    preview_card.pack_propagate(False)
    preview_image = tk.Label(preview_card, bg="#191f34", fg="#a2abc9", text="2D")
    preview_image.pack(side="top", pady=(2, 0))
    preview_name = tk.StringVar(value="")
    tk.Label(preview_card, textvariable=preview_name, bg="#191f34", fg="#e9ecff", font=("Segoe UI", 8), wraplength=88).pack(side="bottom", fill="x")
    avatar.set(AVATAR_PROFILES[initial_avatar]["label"])
    panel.astra_avatar_preview = preview_image
    panel.astra_avatar_preview_name = preview_name
    character_profiles = {identity: dict(data) for identity, data in profile.character_profiles.items()}
    character_profiles.setdefault(initial_avatar, {
        "assistant_name": profile.assistant_name or AVATAR_PROFILES[initial_avatar]["default_name"],
        "voice_id": profile.voice_id,
    })
    tk.Label(voice_tab, text="Имя ассистента", bg="#101322", fg="#a2abc9").pack(anchor="w", padx=24)
    assistant_name = tk.Entry(voice_tab, bg="#191f34", fg="#e9ecff", insertbackground="#e9ecff", font=("Segoe UI", 11))
    initial_name = character_profiles[initial_avatar]["assistant_name"]
    assistant_name.insert(0, initial_name)
    assistant_name.pack(fill="x", padx=24, pady=(2, 8))
    previous_avatar = [initial_avatar]
    preview_photos = {}
    def refresh_avatar_preview(_event=None):
        selected = avatar_labels.get(avatar.get(), DEFAULT_AVATAR_ID)
        display_name = assistant_name.get().strip() or AVATAR_PROFILES[selected]["default_name"]
        preview_name.set(display_name)
        if selected not in preview_photos:
            try:
                resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
                image_path = resource_root / "assets" / "avatars" / AVATAR_PROFILES[selected]["asset"]
                image = tk.PhotoImage(master=panel, file=str(image_path))
                factor = max(1, (max(image.width(), image.height()) + 79) // 80)
                preview_photos[selected] = image.subsample(factor, factor)
            except Exception:
                preview_photos[selected] = None
        photo = preview_photos[selected]
        if photo is None:
            preview_image.configure(image="", text="Нет\nпортрета")
        else:
            preview_image.configure(image=photo, text="")
    panel.astra_refresh_avatar_preview = refresh_avatar_preview
    refresh_avatar_preview()
    assistant_name.bind("<KeyRelease>", refresh_avatar_preview)
    preview_process = [None]
    preview_status = tk.StringVar(value="3D-preview в отдельном окне повторяет текущий образ и состояние Astra.")
    tk.Label(voice_tab, textvariable=preview_status, bg="#101322", fg="#a2abc9", wraplength=650).pack(anchor="w", padx=24, pady=(0, 4))
    def preview_3d():
        process = preview_process[0]
        if process is not None and process.poll() is None:
            preview_status.set("3D-preview уже открыт. Закрой его окно перед повторным запуском.")
            return
        selected = avatar_labels.get(avatar.get(), DEFAULT_AVATAR_ID)
        display_name = assistant_name.get().strip() or AVATAR_PROFILES[selected]["default_name"]
        try:
            from src.avatar_preview import launch_avatar_preview
            current_state = app.avatar_state() if app is not None else "idle"
            preview_process[0] = launch_avatar_preview(selected, display_name, initial_state=current_state)
            if app is not None:
                app.avatar_preview_session = preview_process[0]
        except Exception as exc:
            preview_status.set("3D-preview недоступен: " + str(exc))
            messagebox.showerror("Astra · 3D персонаж", str(exc), parent=panel)
            return
        preview_status.set("Открыт 3D-preview: " + display_name + ". Он синхронизируется с состоянием Astra.")
    panel.astra_preview_3d = preview_3d
    tk.Button(voice_tab, text="Открыть 3D-preview выбранного персонажа", command=preview_3d,
              bg="#34304f", fg="#e9ecff", activebackground="#51447e", relief="flat",
              font=("Segoe UI", 10)).pack(anchor="w", padx=24, pady=(0, 10))
    def avatar_changed(_event=None):
        selected = avatar_labels.get(avatar.get(), DEFAULT_AVATAR_ID)
        previous = previous_avatar[0]
        character_profiles[previous] = {
            "assistant_name": assistant_name.get().strip() or AVATAR_PROFILES[previous]["default_name"],
            "voice_id": voices_map.get(voices.get(), character_profiles[previous]["voice_id"]),
        }
        selected_profile = character_profiles.setdefault(selected, {
            "assistant_name": AVATAR_PROFILES[selected]["default_name"], "voice_id": "",
        })
        assistant_name.delete(0, "end")
        assistant_name.insert(0, selected_profile["assistant_name"])
        select_voice_identity(selected_profile["voice_id"])
        previous_avatar[0] = selected
        refresh_avatar_preview()
    avatar.bind("<<ComboboxSelected>>", avatar_changed)
    tk.Label(voice_tab, text="Выбор микрофона применяется только после сохранения и нажатия «Голос». При старте микрофон выключен.", bg="#101322", fg="#a2abc9", wraplength=650).pack(padx=24, pady=6)
    tk.Label(voice_tab, text="Устройство ввода", bg="#101322", fg="#a2abc9").pack(anchor="w", padx=24)
    microphones = ttk.Combobox(voice_tab, state="readonly", font=("Segoe UI", 11))
    microphones.pack(fill="x", padx=24, pady=(2, 8))
    tk.Label(voice_tab, text="Голос синтеза Windows", bg="#101322", fg="#a2abc9").pack(anchor="w", padx=24)
    voices = ttk.Combobox(voice_tab, state="readonly", font=("Segoe UI", 11))
    voices.pack(fill="x", padx=24, pady=(2, 8))
    rate = tk.IntVar(value=AIProfile().voice_rate)
    volume = tk.DoubleVar(value=AIProfile().voice_volume)
    tk.Label(voice_tab, text="Скорость речи", bg="#101322", fg="#a2abc9").pack(anchor="w", padx=24)
    tk.Scale(voice_tab, from_=80, to=300, variable=rate, orient="horizontal", bg="#101322", fg="#e9ecff", highlightthickness=0).pack(fill="x", padx=20)
    tk.Label(voice_tab, text="Громкость речи", bg="#101322", fg="#a2abc9").pack(anchor="w", padx=24)
    tk.Scale(voice_tab, from_=0, to=100, variable=volume, orient="horizontal", bg="#101322", fg="#e9ecff", highlightthickness=0).pack(fill="x", padx=20)
    status = tk.StringVar(value="Ключ хранится локально в зашифрованном виде. Проверка сети запускается отдельно.")
    if profile_load_failed:
        status.set("Сохранённые настройки не прочитаны. Можно сохранить новый профиль.")
    # Values are filled after profile decryption; device names never leave this computer.
    rate.set(profile.voice_rate)
    volume.set(profile.voice_volume)
    mailbox = queue.Queue()
    microphone_map = {"Системный выбор Windows": None}
    microphones["values"] = ("Системный выбор Windows",)
    microphones.set("Системный выбор Windows")
    voices_map = {"Системный голос Windows": ""}
    voices["values"] = ("Системный голос Windows",)
    voices.set("Системный голос Windows")
    busy = [False]
    def select_voice_identity(voice_id):
        if not voice_id:
            voices.set("Системный голос Windows")
            return
        for display, identity in voices_map.items():
            if identity == voice_id:
                voices.set(display)
                return
        label = f"Сохранённый голос ({voice_id[:48]})"
        voices_map[label] = voice_id
        voices["values"] = tuple(voices_map)
        voices.set(label)
    select_voice_identity(character_profiles[initial_avatar]["voice_id"])
    if profile.microphone_index is not None:
        label = f"Устройство №{profile.microphone_index} (последний выбор)"
        microphone_map[label] = profile.microphone_index
        microphones["values"] = ("Системный выбор Windows", label)
        microphones.set(label)
    def discover_audio():
        if busy[0]:
            return
        busy[0] = True
        status.set("Ищу локальные устройства и голоса Windows…")
        def work():
            try:
                import speech_recognition as sr
                names = sr.Microphone.list_microphone_names()
                microphone_rows = [(f"{index}: {name}", index) for index, name in enumerate(names)]
            except Exception:
                microphone_rows = None
            try:
                import pyttsx3
                engine = pyttsx3.init("sapi5")
                voice_rows = [(str(getattr(voice, "name", "Голос Windows")), str(getattr(voice, "id", ""))) for voice in engine.getProperty("voices") or []]
                engine.stop()
            except Exception:
                voice_rows = None
            mailbox.put(("audio", (microphone_rows, voice_rows)))
        threading.Thread(target=work, name="astra-audio-devices", daemon=True).start()
    scope_labels = {"apps": "Приложения из разрешённого списка", "browser": "Браузер и поиск", "folders": "Открытие известных папок", "media": "Медиа и громкость", "windows": "Управление окнами", "typing": "Ввод текста и клавиши", "system": "Сведения о системе и скриншоты", "vpn": "Заданный VPN", "routines": "Пользовательские режимы", "reminders": "Создание напоминаний"}
    scope_vars = {scope: tk.BooleanVar(value=scope in profile.allowed_scopes) for scope in ALL_SCOPES}
    tk.Label(permissions, text="Отключённые навыки блокируются перед исполнением,\nвключая шаги пользовательских режимов. Файловая запись\nразрешается отдельно в выбранной папке.", bg="#101322", fg="#a2abc9").pack(pady=18)
    for scope, variable in scope_vars.items():
        tk.Checkbutton(permissions, text=scope_labels[scope], variable=variable, bg="#101322", fg="#e9ecff", selectcolor="#191f34", activebackground="#101322", activeforeground="#e9ecff").pack(anchor="w", padx=30, pady=4)
    labels = {"env": "Настройки существующего проекта (.env)", "disabled": "ИИ выключен · только команды", "ollama": "Локальный Ollama · без облака", "gemini": "Облачный Gemini", "compatible": "Облачный совместимый API"}
    tk.Label(content, text="Интеллект Astra", bg="#101322", fg="#e9ecff", font=("Segoe UI", 19)).pack(pady=20)
    provider = ttk.Combobox(content, values=list(labels.values()), state="readonly", font=("Segoe UI", 11))
    provider.set(labels[profile.provider])
    provider.pack(fill="x", padx=24, pady=10)
    def field(label, value, secret=False):
        tk.Label(content, text=label, bg="#101322", fg="#a2abc9").pack(anchor="w", padx=24)
        widget = tk.Entry(content, bg="#191f34", fg="#e9ecff", insertbackground="#e9ecff", show="•" if secret else "", font=("Segoe UI", 11))
        widget.insert(0, value)
        widget.pack(fill="x", padx=24, pady=(0, 14), ipady=7)
        return widget
    model = field("Модель", profile.model)
    endpoint = field("Адрес сервера (для Ollama — localhost, для облака — HTTPS)", profile.base_url)
    key = field("API-ключ (для локального Ollama оставь пустым)", profile.api_key, True)
    memory = tk.BooleanVar(value=profile.memory_enabled)
    tk.Checkbutton(content, text="Использовать мои сохранённые заметки только в локальном диалоге", variable=memory, bg="#101322", fg="#e9ecff", selectcolor="#191f34", activebackground="#101322", activeforeground="#e9ecff").pack(padx=20, pady=8)
    def provider_changed(_event=None):
        code = next(code for code, label in labels.items() if label == provider.get())
        if code == "ollama":
            endpoint.delete(0, "end")
            endpoint.insert(0, "http://127.0.0.1:11434")
            key.delete(0, "end")
        elif code == "gemini":
            endpoint.delete(0, "end")
            endpoint.insert(0, "https://generativelanguage.googleapis.com/v1beta/openai/")
        if code != "ollama":
            memory.set(False)
    provider.bind("<<ComboboxSelected>>", provider_changed)
    tk.Label(content, text="Ollama использует только установленную модель. Новые модели автоматически не скачиваются.\nОблачный режим отправляет вопросы выбранному провайдеру.", bg="#101322", fg="#a2abc9", wraplength=680).pack(padx=20, pady=10)
    discover_button = tk.Button(voice_tab, text="Обнаружить устройства и голоса", command=discover_audio, bg="#2b3454", fg="#e9ecff", relief="flat", font=("Segoe UI", 10), padx=16, pady=9)
    discover_button.pack(pady=8)
    tk.Label(panel, textvariable=status, bg="#101322", fg="#a2abc9", wraplength=680).pack(padx=20, pady=12)
    timer = [None]
    panel.astra_profile_status = status
    panel.astra_busy = busy
    def current():
        code = next(code for code, label in labels.items() if label == provider.get())
        selected_avatar = avatar_labels.get(avatar.get(), DEFAULT_AVATAR_ID)
        selected_voice = voices_map.get(voices.get(), character_profiles[selected_avatar]["voice_id"])
        selected_name = assistant_name.get().strip()
        character_profiles[selected_avatar] = {"assistant_name": selected_name, "voice_id": selected_voice}
        return AIProfile(provider=code, model=model.get().strip(), base_url=endpoint.get().strip(), api_key=key.get(), memory_enabled=memory.get(), allowed_scopes=tuple(scope for scope, variable in scope_vars.items() if variable.get()), assistant_name=selected_name, voice_id=selected_voice, microphone_index=microphone_map.get(microphones.get(), profile.microphone_index), voice_rate=rate.get(), voice_volume=volume.get(), avatar_id=selected_avatar, character_profiles=dict(character_profiles)).validate()
    def save():
        if busy[0]:
            status.set("Дождись завершения проверки или прослушивания")
            return
        try:
            store.save(current())
            on_saved()
            status.set("Сохранено. Astra перезапускается в текстовом режиме; микрофон выключен.")
        except Exception:
            status.set("Не удалось сохранить профиль. Проверь провайдера, адрес и модель.")

    def backup_export():
        if busy[0]:
            status.set("Дождись завершения текущей операции")
            return
        try:
            snapshot = current()
        except Exception as exc:
            status.set(str(exc))
            return
        passphrase = simpledialog.askstring(
            "Зашифрованная копия профиля", "Придумай парольную фразу (не менее 12 символов):",
            show="•", parent=panel,
        )
        if passphrase is None:
            return
        confirmation = simpledialog.askstring(
            "Подтверждение парольной фразы", "Введи её ещё раз:", show="•", parent=panel,
        )
        if confirmation is None:
            return
        if passphrase != confirmation:
            status.set("Парольные фразы не совпали; файл не создавался")
            return
        chosen = filedialog.asksaveasfilename(
            parent=panel, title="Сохранить зашифрованный профиль Astra",
            defaultextension=".astra-profile-backup",
            filetypes=[("Резервная копия профиля Astra", "*.astra-profile-backup")],
        )
        if not chosen:
            return
        target = Path(chosen)
        if target.exists() and not messagebox.askyesno(
            "Заменить резервную копию?", "Выбранный файл будет заменён зашифрованной копией.", parent=panel,
        ):
            return
        busy[0] = True
        status.set("Создаю зашифрованную резервную копию…")
        def work():
            try:
                export_profile(target, snapshot, passphrase)
                mailbox.put(("backup_exported", str(target)))
            except Exception:
                mailbox.put(("status", "Не удалось создать профильную копию. Проверь путь и парольную фразу."))
        threading.Thread(target=work, name="astra-profile-export", daemon=True).start()

    def backup_import():
        if busy[0]:
            status.set("Дождись завершения текущей операции")
            return
        chosen = filedialog.askopenfilename(
            parent=panel, title="Открыть зашифрованный профиль Astra",
            filetypes=[("Резервная копия профиля Astra", "*.astra-profile-backup"), ("Все файлы", "*.*")],
        )
        if not chosen:
            return
        passphrase = simpledialog.askstring(
            "Парольная фраза профиля", "Введи парольную фразу резервной копии:",
            show="•", parent=panel,
        )
        if passphrase is None:
            return
        busy[0] = True
        status.set("Проверяю и расшифровываю профиль…")
        def work():
            try:
                restored = import_profile(Path(chosen), passphrase)
                mailbox.put(("backup_import_ready", restored))
            except Exception:
                mailbox.put(("status", "Не удалось открыть копию: проверь файл и парольную фразу."))
        threading.Thread(target=work, name="astra-profile-import", daemon=True).start()

    def check_local():
        if busy[0]:
            return
        try:
            client = OllamaClient(endpoint.get().strip(), timeout=5)
        except ValueError as exc:
            status.set(str(exc))
            return
        busy[0] = True
        status.set("Проверяю локальный сервер…")
        def work():
            try:
                mailbox.put(("status", "Установленные модели: " + ", ".join(client.models())))
            except Exception:
                mailbox.put(("status", "Ollama недоступен по этому локальному адресу. Ничего не скачивалось."))
        threading.Thread(target=work, daemon=True).start()
    actions = tk.Frame(content, bg="#101322")
    actions.pack(pady=10)
    button(actions, "Проверить Ollama", check_local).pack(side="left", padx=5)
    button(actions, "Сохранить и применить", save).pack(side="left", padx=5)
    button(voice_tab, "Прослушать выбранный голос", lambda: preview_voice()).pack(pady=(2, 8))
    button(voice_tab, "Сохранить голос и микрофон", save).pack(pady=5)
    button(permissions, "Сохранить разрешения", save).pack(pady=15)
    backup_row = tk.Frame(permissions, bg="#101322")
    backup_row.pack(pady=(0, 14))
    button(backup_row, "Экспорт профиля…", backup_export).pack(side="left", padx=5)
    button(backup_row, "Импорт профиля…", backup_import).pack(side="left", padx=5)
    tk.Label(permissions, text="Профильная копия может содержать API-ключ, но только внутри шифрования. Нужна парольная фраза от 12 символов; потерянную фразу восстановить нельзя. Импорт заменит настройки профиля, но не затронет память и напоминания.", bg="#101322", fg="#a2abc9", wraplength=650, justify="left").pack(padx=24, pady=(0, 12))
    def preview_voice():
        if busy[0]:
            return
        try:
            config = current()
        except Exception as exc:
            status.set(str(exc))
            return
        busy[0] = True
        status.set("Произношу тестовую фразу на выбранном голосе…")
        def work():
            try:
                import pyttsx3
                engine = pyttsx3.init("sapi5")
                if config.voice_id:
                    engine.setProperty("voice", config.voice_id)
                engine.setProperty("rate", config.voice_rate)
                engine.setProperty("volume", config.voice_volume)
                engine.say(f"Привет, я {config.assistant_name or 'Астра'}. Это проверка голоса.")
                engine.runAndWait()
                engine.stop()
                result = "Прослушивание завершено"
            except Exception:
                result = "Системное озвучивание недоступно"
            mailbox.put(("status", result))
        threading.Thread(target=work, name="astra-voice-preview", daemon=True).start()
    def poll():
        try:
            kind, message = mailbox.get_nowait()
            if kind == "audio":
                microphone_rows, voice_rows = message
                if microphone_rows is not None:
                    microphone_map.clear()
                    microphone_map["Системный выбор Windows"] = None
                    microphone_map.update(microphone_rows)
                    microphones["values"] = tuple(microphone_map)
                    current_index = profile.microphone_index
                    selected = next((name for name, index in microphone_map.items() if index == current_index), "Системный выбор Windows")
                    microphones.set(selected)
                if voice_rows is not None:
                    voices_map.clear()
                    voices_map["Системный голос Windows"] = ""
                    voices_map.update(voice_rows)
                    voices["values"] = tuple(voices_map)
                    select_voice_identity(character_profiles[previous_avatar[0]]["voice_id"])
                status.set("Устройства и голоса обновлены локально")
            elif kind == "backup_import_ready":
                restored = message
                summary = (f"Импортировать профиль {restored.assistant_name or 'Astra'}?\n\n"
                           f"Провайдер: {restored.provider}\nМодель: {restored.model}\n"
                           f"Разрешений навыков: {len(restored.allowed_scopes)}\n\n"
                           "Текущий профиль будет заменён. Память и напоминания останутся без изменений. "
                           "Выбор микрофона может потребовать проверки на этом компьютере.")
                if messagebox.askyesno("Подтверждение импорта профиля", summary, parent=panel):
                    try:
                        store.save(restored)
                        on_saved()
                        status.set("Профиль импортирован; Astra перезапущена в текстовом режиме")
                    except Exception:
                        status.set("Не удалось сохранить импортированный профиль; текущие данные не изменены")
                else:
                    status.set("Импорт отменён; текущий профиль не изменён")
            else:
                status.set(message)
            busy[0] = False
        except queue.Empty:
            pass
        timer[0] = panel.after(100, poll)
    def close():
        if timer[0] is not None:
            panel.after_cancel(timer[0])
        panel.destroy()
    panel.protocol("WM_DELETE_WINDOW", close)
    def destroyed(event):
        if event.widget == panel and timer[0] is not None:
            panel.after_cancel(timer[0])
            timer[0] = None
    panel.bind("<Destroy>", destroyed)
    poll()
    return panel
