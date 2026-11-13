"""Optional first-run setup; nothing is persisted until the user finishes."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from src.action_policy import ALL_SCOPES
from src.desktop_settings import AIProfile, AVATAR_PROFILES, DEFAULT_AVATAR_ID, DesktopSettings


BG = "#101322"
PANEL = "#191f34"
TEXT = "#e9ecff"
MUTED = "#a2abc9"
ACCENT = "#9786ff"
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen3:4b"


def open_onboarding(owner, button, on_saved, store: DesktopSettings | None = None):
    """Open a non-modal three-step wizard for a new local user profile.

    The wizard does not enable the microphone, contact an AI endpoint, or
    download a model. Only the explicit Finish button writes DPAPI settings.
    """
    store = store or DesktopSettings()
    try:
        initial = store.load()
    except Exception:
        initial = AIProfile(provider="disabled")

    panel = tk.Toplevel(owner)
    panel.title("Astra · первый запуск")
    panel.geometry("720x560")
    panel.minsize(680, 520)
    panel.configure(bg=BG)
    panel.transient(owner)

    tk.Label(panel, text="Давайте настроим Astra", bg=BG, fg=TEXT,
             font=("Segoe UI", 20, "bold")).pack(anchor="w", padx=28, pady=(22, 2))
    tk.Label(panel, text="Настройки сохраняются только после нажатия «Готово».",
             bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w", padx=30, pady=(0, 12))
    step_title = tk.StringVar(master=panel, value="Шаг 1 из 3 · персонаж")
    tk.Label(panel, textvariable=step_title, bg=BG, fg=ACCENT,
             font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=30, pady=(0, 8))
    pages = tk.Frame(panel, bg=BG)
    pages.pack(fill="both", expand=True, padx=28)

    identity = initial.avatar_id if initial.avatar_id in AVATAR_PROFILES else DEFAULT_AVATAR_ID
    character_profiles = {key: dict(value) for key, value in initial.character_profiles.items()}
    character_profiles.setdefault(identity, {
        "assistant_name": initial.assistant_name or AVATAR_PROFILES[identity]["default_name"],
        "voice_id": initial.voice_id,
    })
    name_var = tk.StringVar(master=panel, value=character_profiles[identity]["assistant_name"])
    previous_avatar = [identity]
    avatar_labels = {value["label"]: key for key, value in AVATAR_PROFILES.items()}
    avatar_var = tk.StringVar(master=panel, value=AVATAR_PROFILES[identity]["label"])
    provider_var = tk.StringVar(master=panel, value="disabled")
    photo_cache = {}

    page_character = tk.Frame(pages, bg=BG)
    page_ai = tk.Frame(pages, bg=BG)
    page_privacy = tk.Frame(pages, bg=BG)

    copy = tk.Frame(page_character, bg=BG)
    copy.pack(side="left", fill="both", expand=True, padx=(0, 18))
    tk.Label(copy, text="Образ и имя", bg=BG, fg=TEXT,
             font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(4, 10))
    tk.Label(copy, text="Выбери женский или мужской образ. Имя можно оставить или задать своё.",
             wraplength=400, justify="left", bg=BG, fg=MUTED,
             font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 14))
    tk.Label(copy, text="Персонаж", bg=BG, fg=MUTED).pack(anchor="w")
    avatar_choice = ttk.Combobox(copy, textvariable=avatar_var, values=tuple(avatar_labels), state="readonly")
    avatar_choice.pack(fill="x", pady=(3, 14), ipady=4)
    tk.Label(copy, text="Имя ассистента", bg=BG, fg=MUTED).pack(anchor="w")
    name_entry = tk.Entry(copy, textvariable=name_var, bg=PANEL, fg=TEXT,
                          insertbackground=TEXT, relief="flat", font=("Segoe UI", 12))
    name_entry.pack(fill="x", pady=(3, 12), ipady=8)
    preview = tk.Label(page_character, text="2D", bg=PANEL, fg=MUTED,
                       width=24, height=14, compound="top")
    preview.pack(side="right", fill="y", padx=(0, 8), pady=8)
    preview_name = tk.StringVar(master=panel, value=name_var.get())
    tk.Label(page_character, textvariable=preview_name, bg=BG, fg=TEXT,
             font=("Segoe UI", 12, "bold")).pack(side="right", padx=(0, 8))

    def refresh_preview(*_args):
        selected = avatar_labels.get(avatar_var.get(), DEFAULT_AVATAR_ID)
        preview_name.set(name_var.get().strip() or AVATAR_PROFILES[selected]["default_name"])
        if selected not in photo_cache:
            try:
                root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
                image_path = root / "assets" / "avatars" / AVATAR_PROFILES[selected]["asset"]
                source = tk.PhotoImage(master=panel, file=str(image_path))
                factor = max(1, (max(source.width(), source.height()) + 219) // 220)
                photo_cache[selected] = source.subsample(factor, factor)
            except Exception:
                photo_cache[selected] = None
        image = photo_cache[selected]
        preview.configure(image=image or "", text="" if image else "Портрет недоступен")

    def avatar_changed(_event=None):
        old = previous_avatar[0]
        character_profiles[old] = {
            "assistant_name": name_var.get().strip() or AVATAR_PROFILES[old]["default_name"],
            "voice_id": character_profiles.get(old, {}).get("voice_id", ""),
        }
        selected = avatar_labels.get(avatar_var.get(), DEFAULT_AVATAR_ID)
        character_profiles.setdefault(selected, {
            "assistant_name": AVATAR_PROFILES[selected]["default_name"], "voice_id": "",
        })
        name_var.set(character_profiles[selected]["assistant_name"])
        previous_avatar[0] = selected
        refresh_preview()

    avatar_choice.bind("<<ComboboxSelected>>", avatar_changed)
    name_var.trace_add("write", refresh_preview)
    refresh_preview()

    tk.Label(page_ai, text="Искусственный интеллект", bg=BG, fg=TEXT,
             font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(4, 12))
    tk.Label(page_ai, text="Выбери, как Astra будет отвечать на свободные вопросы. Настройки можно поменять позже.",
             wraplength=620, justify="left", bg=BG, fg=MUTED,
             font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 14))
    tk.Radiobutton(
        page_ai, text="Пока не подключать ИИ · локальные команды Astra останутся доступны",
        variable=provider_var, value="disabled", bg=BG, fg=TEXT, selectcolor=PANEL,
        activebackground=BG, activeforeground=TEXT, wraplength=620, justify="left",
        font=("Segoe UI", 10),
    ).pack(anchor="w", pady=8)
    tk.Radiobutton(
        page_ai, text="Ollama на этом компьютере · модель не скачивается и сервер не проверяется",
        variable=provider_var, value="ollama", bg=BG, fg=TEXT, selectcolor=PANEL,
        activebackground=BG, activeforeground=TEXT, wraplength=620, justify="left",
        font=("Segoe UI", 10),
    ).pack(anchor="w", pady=8)
    tk.Radiobutton(
        page_ai, text="Использовать уже настроенные параметры окружения, если они есть",
        variable=provider_var, value="env", bg=BG, fg=TEXT, selectcolor=PANEL,
        activebackground=BG, activeforeground=TEXT, wraplength=620, justify="left",
        font=("Segoe UI", 10),
    ).pack(anchor="w", pady=8)
    tk.Label(page_ai, text=f"Локальный адрес: {OLLAMA_URL}\nМодель по умолчанию: {OLLAMA_MODEL}",
             bg=BG, fg=MUTED, justify="left", font=("Segoe UI", 9)).pack(anchor="w", padx=28, pady=6)
    tk.Label(page_ai, text="Подключение к Gemini и другим облачным моделям настраивается отдельно в разделе «ИИ, голос и разрешения».",
             bg=BG, fg=MUTED, wraplength=620, justify="left",
             font=("Segoe UI", 9)).pack(anchor="w", pady=(12, 4))

    summary = tk.StringVar(master=panel, value="")
    tk.Label(page_privacy, text="Готово к запуску", bg=BG, fg=TEXT,
             font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(4, 12))
    tk.Label(page_privacy, textvariable=summary, bg=PANEL, fg=TEXT,
             wraplength=600, justify="left", padx=18, pady=18,
             font=("Segoe UI", 11)).pack(fill="x", pady=(0, 16))
    tk.Label(page_privacy, text="Astra откроется в текстовом режиме. Микрофон останется выключен: включить его можно отдельной кнопкой в главном окне.",
             bg=BG, fg=MUTED, wraplength=620, justify="left",
             font=("Segoe UI", 10)).pack(anchor="w")

    page_frames = (page_character, page_ai, page_privacy)
    current_step = [0]
    for page in page_frames:
        page.pack_forget()

    def show_step(index: int):
        current_step[0] = index
        for page in page_frames:
            page.pack_forget()
        page_frames[index].pack(fill="both", expand=True)
        step_title.set((
            "Шаг 1 из 3 · персонаж",
            "Шаг 2 из 3 · ИИ",
            "Шаг 3 из 3 · запуск и приватность",
        )[index])
        back_button.configure(state="normal" if index else "disabled")
        next_button.configure(text="Готово" if index == 2 else "Далее →")
        if index == 2:
            selected = avatar_labels.get(avatar_var.get(), DEFAULT_AVATAR_ID)
            name = name_var.get().strip() or AVATAR_PROFILES[selected]["default_name"]
            provider = {
                "ollama": "Ollama · локально",
                "env": "настройки окружения",
                "disabled": "не подключён",
            }[provider_var.get()]
            summary.set(f"Персонаж: {name} · {AVATAR_PROFILES[selected]['label']}\nИИ: {provider}\nЗапуск: текстовый режим · микрофон выключен")

    def save_and_finish():
        selected = avatar_labels.get(avatar_var.get(), DEFAULT_AVATAR_ID)
        name = name_var.get().strip() or AVATAR_PROFILES[selected]["default_name"]
        characters = dict(character_profiles)
        characters[selected] = {
            "assistant_name": name,
            "voice_id": characters.get(selected, {}).get("voice_id", ""),
        }
        provider = provider_var.get()
        try:
            profile = replace(
                initial,
                provider=provider,
                model=OLLAMA_MODEL if provider == "ollama" else initial.model,
                base_url=OLLAMA_URL if provider == "ollama" else initial.base_url,
                api_key="" if provider in {"disabled", "ollama"} else initial.api_key,
                memory_enabled=False,
                assistant_name=name,
                avatar_id=selected,
                character_profiles=characters,
            ).validate()
            store.save(profile)
            on_saved()
            panel.destroy()
        except Exception as exc:
            messagebox.showerror("Astra · первый запуск", "Не удалось сохранить профиль: " + str(exc), parent=panel)

    def next_step():
        if current_step[0] == 0:
            selected = avatar_labels.get(avatar_var.get(), DEFAULT_AVATAR_ID)
            name = name_var.get().strip() or AVATAR_PROFILES[selected]["default_name"]
            try:
                replace(initial, assistant_name=name, avatar_id=selected).validate()
            except ValueError as exc:
                messagebox.showerror("Astra · имя", str(exc), parent=panel)
                return
        if current_step[0] == 2:
            save_and_finish()
        else:
            show_step(current_step[0] + 1)

    nav = tk.Frame(panel, bg=BG)
    nav.pack(fill="x", padx=28, pady=(10, 22))
    back_button = button(nav, "← Назад", lambda: show_step(max(0, current_step[0] - 1)))
    back_button.pack(side="left")
    cancel_button = button(nav, "Закрыть", panel.destroy)
    cancel_button.pack(side="right", padx=(8, 0))
    next_button = button(nav, "Далее →", next_step)
    next_button.pack(side="right")
    show_step(0)

    panel.astra_avatar_choice = avatar_choice
    panel.astra_name_entry = name_entry
    panel.astra_provider_var = provider_var
    panel.astra_summary = summary
    panel.astra_finish = save_and_finish
    panel.astra_step = lambda: current_step[0]
    panel.astra_next_button = next_button
    panel.astra_back_button = back_button
    return panel
