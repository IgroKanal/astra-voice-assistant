"""Astra Quiet Orbit design tokens and native Tk component styles."""
from tkinter import ttk

BG = "#0B1020"
PANEL = "#131B2E"
PANEL_ALT = "#182238"
FIELD = "#1B2740"
TEXT = "#F2F5FF"
MUTED = "#A8B4CF"
ACCENT = "#A99BFF"
ACCENT_HOVER = "#BDB2FF"
CYAN = "#72D8D0"
BORDER = "#283652"
SUCCESS = "#72D8D0"
WARNING = "#F0C987"
ERROR = "#FF9EAA"
FONT = "Segoe UI"


def install_theme(root):
    """Install shared colors without changing global Tk defaults."""
    for pattern, value in {
        "*Font": "{Segoe UI} 10", "*Label.background": BG, "*Label.foreground": TEXT,
        "*Frame.background": BG, "*Entry.background": FIELD, "*Entry.foreground": TEXT,
        "*Entry.insertBackground": TEXT, "*Entry.relief": "flat",
        "*Entry.highlightBackground": BORDER, "*Entry.highlightColor": ACCENT,
        "*Listbox.background": PANEL, "*Listbox.foreground": TEXT,
        "*Listbox.selectBackground": "#3C3965", "*Listbox.selectForeground": TEXT,
        "*Listbox.relief": "flat", "*Listbox.borderWidth": 0,
        "*Text.selectBackground": "#49406D", "*Text.selectForeground": TEXT,
    }.items():
        root.option_add(pattern, value)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 12))
    style.configure(
        "TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(18, 11),
        font=(FONT, 10), borderwidth=0,
    )
    style.map(
        "TNotebook.Tab", background=[("selected", FIELD), ("active", PANEL_ALT)],
        foreground=[("selected", TEXT), ("active", TEXT)],
    )
    style.configure(
        "TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT,
        arrowcolor=ACCENT, padding=7, bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD,
    )
    style.map(
        "TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
        selectbackground=[("readonly", FIELD)], bordercolor=[("focus", ACCENT)],
    )
    style.configure(
        "Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
        rowheight=36, borderwidth=0, font=(FONT, 10),
    )
    style.configure(
        "Treeview.Heading", background=FIELD, foreground=MUTED, relief="flat",
        padding=(10, 9), font=(FONT, 9, "bold"),
    )
    style.map("Treeview", background=[("selected", "#3C3965")], foreground=[("selected", TEXT)])
    style.configure(
        "Vertical.TScrollbar", background=FIELD, troughcolor=PANEL,
        arrowcolor=MUTED, borderwidth=0, width=12,
    )
    style.configure(
        "Astra.Horizontal.TProgressbar", troughcolor=FIELD, background=ACCENT,
        bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT,
    )
