import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from src.action_audit import default_audit
from src.action_audit_ui import open_action_audit


class AuditUITests(unittest.TestCase):
    def test_history_searches_filters_and_refreshes_without_showing_event_details(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"LOCALAPPDATA": temp}):
            root = tk.Tk()
            root.withdraw()
            try:
                panel = open_action_audit(root, lambda owner, text, command: tk.Button(owner, text=text, command=command))
                root.update()
                stack = list(panel.winfo_children())
                table = None
                refresh = None
                search = None
                outcome_filter = None
                while stack:
                    widget = stack.pop()
                    stack.extend(widget.winfo_children())
                    if isinstance(widget, ttk.Treeview):
                        table = widget
                    if isinstance(widget, tk.Button) and widget.cget("text") == "Обновить":
                        refresh = widget
                    if isinstance(widget, tk.Entry):
                        search = widget
                    if isinstance(widget, ttk.Combobox):
                        outcome_filter = widget
                self.assertIsNotNone(table)
                self.assertIsNotNone(search)
                self.assertIsNotNone(outcome_filter)
                self.assertEqual(len(table.get_children()), 0)
                default_audit().record("files.copy", "succeeded")
                default_audit().record("files.move", "blocked")
                default_audit().record("files.read_text", "failed")
                refresh.invoke()
                rows = table.get_children()
                self.assertEqual(len(rows), 3)
                self.assertEqual(table.item(rows[0], "values")[1:], ("Чтение документа", "Ошибка"))

                search.insert(0, "ПЕРЕМЁЩЕНИЕ")
                rows = table.get_children()
                self.assertEqual(len(rows), 1)
                self.assertEqual(table.item(rows[0], "values")[1], "Перемещение файла")

                search.delete(0, "end")
                outcome_filter.set("Заблокировано")
                rows = table.get_children()
                self.assertEqual(len(rows), 1)
                self.assertEqual(table.item(rows[0], "values")[1:], ("Перемещение файла", "Заблокировано"))
                self.assertEqual(table.item(rows[0], "values")[0].count("."), 1)
                self.assertNotIn("private", " ".join(str(table.item(row, "values")) for row in rows).casefold())
                self.assertEqual(len(table.get_children()), 1)
            finally:
                root.destroy()

    def test_clear_history_requires_confirmation_and_then_clears_local_table(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"LOCALAPPDATA": temp}):
            root = tk.Tk()
            root.withdraw()
            try:
                panel = open_action_audit(root, lambda owner, text, command: tk.Button(owner, text=text, command=command))
                root.update()
                stack = list(panel.winfo_children())
                table = None
                clear = None
                refresh = None
                while stack:
                    widget = stack.pop()
                    stack.extend(widget.winfo_children())
                    if isinstance(widget, ttk.Treeview):
                        table = widget
                    if isinstance(widget, tk.Button) and widget.cget("text") == "Очистить историю":
                        clear = widget
                    if isinstance(widget, tk.Button) and widget.cget("text") == "Обновить":
                        refresh = widget
                self.assertIsNotNone(table)
                self.assertIsNotNone(clear)
                self.assertIsNotNone(refresh)
                default_audit().record("files.copy", "succeeded")
                refresh.invoke()
                with patch("src.action_audit_ui.messagebox.askyesno", return_value=False) as confirm:
                    clear.invoke()
                confirm.assert_called_once()
                self.assertEqual(len(table.get_children()), 1)
                self.assertEqual(len(default_audit().recent()), 1)
                with patch("src.action_audit_ui.messagebox.askyesno", return_value=True) as confirm:
                    clear.invoke()
                confirm.assert_called_once()
                self.assertEqual(len(table.get_children()), 0)
                self.assertEqual(default_audit().recent(), [])
            finally:
                root.destroy()
