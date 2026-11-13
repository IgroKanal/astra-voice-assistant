import os
from pathlib import Path
import runpy
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.scroll_section import scroll_section
from src.personal_memory import PersonalMemory

ROOT = Path(__file__).resolve().parents[1]


class LayoutTests(unittest.TestCase):
    def test_keyboard_focus_scrolls_last_setting_into_small_viewport(self):
        root = tk.Tk()
        root.geometry("500x300")
        try:
            page, content = scroll_section(root)
            page.pack(fill="both", expand=True)
            fields = []
            for index in range(25):
                field = tk.Entry(content)
                field.pack(fill="x", pady=10)
                fields.append(field)
            root.update()
            fields[-1].event_generate("<FocusIn>")
            root.update()
            self.assertGreater(page.astra_canvas.yview()[0], 0)
            self.assertLessEqual(fields[-1].winfo_rooty() + fields[-1].winfo_height(), page.astra_canvas.winfo_rooty() + page.astra_canvas.winfo_height())
        finally:
            root.destroy()

    def test_memory_search_filters_sidebar_without_changing_notes(self):
        Desktop = runpy.run_path(str(ROOT / "astra_desktop.pyw"))["AstraDesktop"]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"LOCALAPPDATA": temp}):
            memory = PersonalMemory(Path(temp) / "AstraVoiceAssistant" / "memory.sqlite")
            memory.add("Работа", "Пример задачи")
            memory.add("Книги", "Пример чтения")
            root = tk.Tk()
            root.withdraw()
            try:
                owner = SimpleNamespace(window=root, button=lambda parent, text, command: tk.Button(parent, text=text, command=command))
                Desktop.open_memory(owner)
                root.update()
                panel = next(item for item in root.winfo_children() if isinstance(item, tk.Toplevel))
                stack = list(panel.winfo_children())
                listing = None
                while stack:
                    widget = stack.pop()
                    stack.extend(widget.winfo_children())
                    if isinstance(widget, tk.Listbox):
                        listing = widget
                self.assertEqual(listing.size(), 2)
                search = next(item for item in listing.master.winfo_children() if isinstance(item, tk.Entry))
                search.insert(0, "Книги")
                root.update()
                self.assertEqual(listing.get(0, "end"), ("Книги",))
                self.assertEqual(len(memory.search()), 2)
            finally:
                root.destroy()
