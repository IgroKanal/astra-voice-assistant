from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from src.reminders import ReminderStore
from src.reminders_ui import open_reminders


class ReminderUITests(unittest.TestCase):
    def test_table_selection_shows_full_text_and_updates_correct_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "tasks.sqlite")
            full_text = "Длинное напоминание\n" + "Подробности " * 200
            pending = store.add(full_text, time.time() + 600)
            delivered = store.add("Уже доставлено", 100)
            claim = store.claim_due(100)[0]
            store.acknowledge(delivered, claim.token)
            root = tk.Tk()
            root.withdraw()
            try:
                panel = open_reminders(root, store, lambda parent, text, command: tk.Button(parent, text=text, command=command))
                root.update()
                stack = list(panel.winfo_children())
                controls, texts = {}, []
                table = None
                while stack:
                    widget = stack.pop()
                    stack.extend(widget.winfo_children())
                    if isinstance(widget, ttk.Treeview): table = widget
                    if isinstance(widget, tk.Text): texts.append(widget)
                    if isinstance(widget, tk.Button): controls[widget.cget("text")] = widget
                self.assertEqual(set(table.get_children()), {pending, delivered})
                table.selection_set(pending)
                table.event_generate("<<TreeviewSelect>>")
                root.update()
                self.assertTrue(any(widget.get("1.0", "end-1c") == full_text.strip() for widget in texts))
                with patch("src.reminders_ui.messagebox.askyesno", return_value=True):
                    controls["Отменить выбранное"].invoke()
                states = {record.id: record.state for record in store.list()}
                self.assertEqual(states[pending], "cancelled")
                self.assertEqual(states[delivered], "delivered")
                table.selection_set(delivered)
                controls["Прочитано"].invoke()
                self.assertEqual({record.id: record.state for record in store.list()}[delivered], "completed")
            finally:
                root.destroy()
