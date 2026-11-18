"""Searchable, non-executing command examples for Astra Desktop."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.command_catalog import CommandExample, search_command_examples

BG = "#101322"
PANEL = "#191f34"
TEXT = "#e9ecff"
MUTED = "#a2abc9"
ACCENT = "#9786ff"


def open_command_catalog(parent, make_button, insert_command):
    panel = tk.Toplevel(parent)
    panel.title("Astra · команды")
    panel.geometry("760x560")
    panel.minsize(660, 480)
    panel.configure(bg=BG)
    panel.transient(parent)
    panel.columnconfigure(0, weight=1)
    panel.rowconfigure(1, weight=1)

    header = tk.Frame(panel, bg=BG)
    header.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 12))
    tk.Label(header, text="Команды Astra", bg=BG, fg=TEXT,
             font=("Segoe UI", 18, "bold")).pack(anchor="w")
    tk.Label(header, text="Найди пример и вставь его в поле чата для проверки.",
             bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 9))

    search_var = tk.StringVar()
    search = tk.Entry(header, textvariable=search_var, bg=PANEL, fg=TEXT,
                      insertbackground=TEXT, relief="flat", font=("Segoe UI", 11))
    search.pack(fill="x", ipady=8)
    search.insert(0, "Поиск по названию, команде или описанию")
    placeholder = "Поиск по названию, команде или описанию"
    search.configure(fg=MUTED)

    content = tk.Frame(panel, bg=BG)
    content.grid(row=1, column=0, sticky="nsew", padx=22)
    content.columnconfigure(0, weight=3)
    content.columnconfigure(1, weight=2)
    content.rowconfigure(0, weight=1)

    list_panel = tk.Frame(content, bg=PANEL)
    list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
    list_panel.rowconfigure(0, weight=1)
    list_panel.columnconfigure(0, weight=1)
    tree = ttk.Treeview(list_panel, columns=("category", "command"), show="headings", selectmode="browse")
    tree.heading("category", text="Раздел")
    tree.heading("command", text="Команда")
    tree.column("category", width=145, minwidth=110, stretch=False)
    tree.column("command", width=285, minwidth=190, stretch=True)
    tree.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
    scrollbar = ttk.Scrollbar(list_panel, orient="vertical", command=tree.yview)
    scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=10)
    tree.configure(yscrollcommand=scrollbar.set)
    empty = tk.Label(list_panel, text="Ничего не найдено", bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 10))

    detail_panel = tk.Frame(content, bg=PANEL)
    detail_panel.grid(row=0, column=1, sticky="nsew")
    detail_panel.columnconfigure(0, weight=1)
    tk.Label(detail_panel, text="Выбранный пример", bg=PANEL, fg=ACCENT,
             font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))
    title = tk.StringVar(value="Выбери команду слева")
    tk.Label(detail_panel, textvariable=title, bg=PANEL, fg=TEXT, wraplength=245,
             justify="left", font=("Segoe UI", 13, "bold")).grid(row=1, column=0, sticky="nw", padx=16)
    phrase = tk.StringVar(value="")
    tk.Label(detail_panel, textvariable=phrase, bg="#252b48", fg="#c5b7ff", wraplength=245,
             justify="left", font=("Segoe UI", 10), padx=10, pady=9).grid(row=2, column=0, sticky="ew", padx=16, pady=(12, 8))
    description = tk.StringVar(value="")
    tk.Label(detail_panel, textvariable=description, bg=PANEL, fg=MUTED, wraplength=245,
             justify="left", font=("Segoe UI", 9)).grid(row=3, column=0, sticky="nw", padx=16, pady=(0, 12))
    tk.Label(detail_panel,
             text="Вставка заполнит поле чата. Команда не запускается автоматически.",
             bg=PANEL, fg=MUTED, wraplength=245, justify="left",
             font=("Segoe UI", 9)).grid(row=4, column=0, sticky="sew", padx=16, pady=16)

    footer = tk.Frame(panel, bg=BG)
    footer.grid(row=2, column=0, sticky="ew", padx=22, pady=14)
    footer.columnconfigure(0, weight=1)
    count = tk.StringVar()
    tk.Label(footer, textvariable=count, bg=BG, fg=MUTED,
             font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w")
    insert_button = make_button(footer, "Вставить в чат", lambda: None)
    insert_button.grid(row=0, column=1, padx=(8, 0))
    make_button(footer, "Закрыть", panel.destroy).grid(row=0, column=2, padx=(8, 0))

    entries: dict[str, tuple[str, CommandExample]] = {}
    selected: dict[str, tuple[str, CommandExample] | None] = {"item": None}

    def select_item(_event=None):
        selection = tree.selection()
        selected["item"] = entries.get(selection[0]) if selection else None
        item = selected["item"]
        if item is None:
            title.set("Выбери команду слева")
            phrase.set("")
            description.set("")
            insert_button.configure(state="disabled")
            return
        _category, example = item
        title.set(example.title)
        phrase.set(example.phrase or "Открой раздел «Задачи» в приложении.")
        description.set(example.description)
        insert_button.configure(state="normal")

    def refresh(*_args):
        query = search_var.get()
        if query == placeholder:
            query = ""
        selected["item"] = None
        entries.clear()
        for row in tree.get_children():
            tree.delete(row)
        matches = search_command_examples(query)
        count.set(f"Найдено: {len(matches)}")
        if matches:
            empty.grid_remove()
        else:
            empty.grid(row=0, column=0, sticky="nsew")
        for group, example in matches:
            tree.insert("", "end", iid=example.key, values=(group.title, example.title))
            entries[example.key] = (group.key, example)
        select_item()

    def insert_selected():
        item = selected["item"]
        if item is None:
            return
        _category, example = item
        panel.destroy()
        insert_command(example.phrase)

    def clear_placeholder(_event=None):
        if search.get() == placeholder:
            search.delete(0, "end")
            search.configure(fg=TEXT)

    tree.bind("<<TreeviewSelect>>", select_item)
    tree.bind("<Double-1>", lambda _event: insert_selected())
    tree.bind("<Return>", lambda _event: (insert_selected(), "break")[1])
    panel.bind("<Escape>", lambda _event: panel.destroy())
    search.bind("<FocusIn>", clear_placeholder)
    search_var.trace_add("write", refresh)
    insert_button.configure(command=insert_selected, state="disabled")
    refresh()
    search.focus_set()
    panel.astra_command_search = search
    panel.astra_command_tree = tree
    panel.astra_command_insert = insert_button
    panel.astra_command_count = count
    panel.astra_command_title = title
    panel.astra_command_phrase = phrase
    panel.astra_command_description = description
    return panel
