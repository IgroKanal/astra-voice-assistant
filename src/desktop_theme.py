"""Shared visual defaults for Astra windows and native Tk controls."""
from tkinter import ttk

BG = "#101322"
PANEL = "#191f34"
FIELD = "#242c46"
TEXT = "#e9ecff"
MUTED = "#a2abc9"
ACCENT = "#9786ff"


def install_theme(root):
    for pattern, value in {
        "*Font": "{Segoe UI} 10", "*Label.background": BG, "*Label.foreground": TEXT,
        "*Frame.background": BG, "*Entry.background": FIELD, "*Entry.foreground": TEXT,
        "*Entry.insertBackground": TEXT, "*Entry.relief": "flat",
        "*Listbox.background": PANEL, "*Listbox.foreground": TEXT,
        "*Listbox.selectBackground": "#49406d", "*Listbox.selectForeground": TEXT,
        "*Listbox.relief": "flat", "*Listbox.borderWidth": 0,
        "*Text.selectBackground": "#49406d", "*Text.selectForeground": TEXT,
    }.items():
        root.option_add(pattern, value)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(16, 9), font=("Segoe UI", 10))
    style.map("TNotebook.Tab", background=[("selected", FIELD), ("active", "#303953")], foreground=[("selected", TEXT)])
    style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT, arrowcolor=ACCENT, padding=5)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)], selectbackground=[("readonly", FIELD)])
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=34, borderwidth=0, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", background=FIELD, foreground=MUTED, relief="flat", padding=(10, 9), font=("Segoe UI", 9, "bold"))
    style.map("Treeview", background=[("selected", "#49406d")], foreground=[("selected", TEXT)])
    style.configure("Vertical.TScrollbar", background=FIELD, troughcolor=PANEL, arrowcolor=MUTED, borderwidth=0, width=12)
