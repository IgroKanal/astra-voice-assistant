"""A keyboard-accessible scrolling settings page without global wheel hooks."""
import tkinter as tk
from tkinter import ttk
from src.desktop_theme import BG


def scroll_section(parent):
    page = tk.Frame(parent, bg=BG)
    canvas = tk.Canvas(page, bg=BG, highlightthickness=0, borderwidth=0)
    bar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    content = tk.Frame(canvas, bg=BG)
    item = canvas.create_window((0, 0), window=content, anchor="nw")
    content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
    def focused(event):
        widget = event.widget
        if widget.winfo_toplevel() != page.winfo_toplevel() or not str(widget).startswith(str(content) + "."):
            return
        total = max(1, content.winfo_height())
        top = widget.winfo_rooty() - content.winfo_rooty()
        visible_top = canvas.canvasy(0)
        if top < visible_top or top + widget.winfo_height() > visible_top + canvas.winfo_height():
            canvas.yview_moveto(max(0, top - 20) / total)
    page.winfo_toplevel().bind("<FocusIn>", focused, add="+")
    def wheel(event):
        if event.delta and str(event.widget).startswith(str(content)):
            steps = max(1, abs(int(event.delta / 120)))
            canvas.yview_scroll(-steps if event.delta > 0 else steps, "units")
    page.winfo_toplevel().bind("<MouseWheel>", wheel, add="+")
    # All bindings are owned by the Toplevel, which is destroyed with the settings panel.
    page.astra_canvas = canvas
    page.astra_content = content
    return page, content
