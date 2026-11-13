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
    def test_history_table_loads_and_refreshes_empty_and_populated_profile(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"LOCALAPPDATA": temp}):
            root = tk.Tk()
            root.withdraw()
            try:
                panel = open_action_audit(root, lambda owner, text, command: tk.Button(owner, text=text, command=command))
                root.update()
                stack = list(panel.winfo_children())
                table = None
                refresh = None
                while stack:
                    widget = stack.pop()
                    stack.extend(widget.winfo_children())
                    if isinstance(widget, ttk.Treeview):
                        table = widget
                    if isinstance(widget, tk.Button) and widget.cget("text") == "Обновить":
                        refresh = widget
                self.assertIsNotNone(table)
                self.assertEqual(len(table.get_children()), 0)
                default_audit().record("files.copy", "succeeded")
                refresh.invoke()
                rows = table.get_children()
                self.assertEqual(len(rows), 1)
                self.assertEqual(table.item(rows[0], "values")[1:], ("Копирование", "Выполнено"))
                refresh.invoke()
                self.assertEqual(len(table.get_children()), 1)
            finally:
                root.destroy()
