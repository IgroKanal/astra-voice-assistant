"""Exercise Tk callbacks and the real worker without touching other apps."""
from pathlib import Path
import runpy
import sys
import time
import tkinter as tk
from tkinter import ttk
import unittest
import tempfile
import gc
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
AstraDesktop = runpy.run_path(str(ROOT / "astra_desktop.pyw"))["AstraDesktop"]


class DesktopUITests(unittest.TestCase):
    def tearDown(self):
        # Tk objects must be collected on the owning main thread, before a
        # later worker can trigger cyclic GC while another Tk interpreter runs.
        gc.collect()

    def pump(self, window, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            window.update()
            if predicate():
                return
            time.sleep(0.02)
        self.fail("Desktop callback timed out")

    def test_text_roundtrip_pause_and_close(self):
        window = tk.Tk()
        window.withdraw()
        app = AstraDesktop(window)
        try:
            self.pump(window, lambda: not app.busy and app.bridge.running)
            app.fill("Астра, сколько времени")
            app.send()
            self.pump(window, lambda: "Сейчас" in app.chat.get("1.0", "end"))
            self.assertEqual(app.entry.get(), "")
            app.switch(None)
            self.pump(window, lambda: not app.busy and not app.bridge.running)
            self.assertIn("выключен", app.status.get())
        finally:
            app.bridge.stop()
            window.destroy()

    def test_new_dialogue_button_waits_for_runtime_reset_event(self):
        window = tk.Tk()
        window.withdraw()
        app = AstraDesktop(window)
        sent = []
        try:
            self.pump(window, lambda: not app.busy and app.bridge.running)
            app.append("Ты", "старый пользовательский вопрос")
            app.bridge.send = lambda text: sent.append(text)
            with patch("astra_desktop.messagebox.askyesno", return_value=True) as confirm:
                app.new_dialogue()
            self.assertEqual(confirm.call_count, 1)
            self.assertEqual(sent, [f"{app.assistant_name}, начни новый диалог"])
            self.assertIn("старый пользовательский вопрос", app.chat.get("1.0", "end"))
            app.bridge.emit("conversation_reset", "")
            self.pump(window, lambda: "старый пользовательский вопрос" not in app.chat.get("1.0", "end"))
            self.assertEqual(app.chat.get("1.0", "end").strip(), "")
            app.bridge.emit("assistant", "Начала новый диалог.")
            self.pump(window, lambda: "Начала новый диалог." in app.chat.get("1.0", "end"))
        finally:
            app.bridge.prevent_restart()
            app.bridge.stop()
            window.after_cancel(app.poll_timer)
            window.after_cancel(app.animation_timer)
            window.destroy()

    def test_command_catalog_search_inserts_without_sending(self):
        window = tk.Tk()
        window.withdraw()
        app = AstraDesktop(window)
        sent = []
        app.bridge.send = lambda text: sent.append(text)
        panel = None
        try:
            self.pump(window, lambda: not app.busy and app.bridge.running)
            panel = app.open_command_catalog()
            window.update()
            search = panel.astra_command_search
            tree = panel.astra_command_tree
            search.delete(0, "end")
            search.insert(0, "новый диалог")
            window.update()
            rows = tree.get_children()
            self.assertEqual(rows, ("new_dialogue",))
            tree.selection_set(rows[0])
            window.update()
            self.assertEqual(panel.astra_command_phrase.get(), "начни новый диалог")
            self.assertIn("контекст текущего разговора", panel.astra_command_description.get())
            panel.astra_command_insert.invoke()
            self.assertEqual(app.entry.get(), f"{app.assistant_name}, начни новый диалог")
            self.assertEqual(sent, [])
            self.assertFalse(panel.winfo_exists())
        finally:
            if panel is not None:
                try:
                    panel.destroy()
                except tk.TclError:
                    pass
            app.bridge.prevent_restart()
            app.bridge.stop()
            window.after_cancel(app.poll_timer)
            window.after_cancel(app.animation_timer)
            window.destroy()

    def test_close_during_startup_leaves_no_runtime(self):
        window = tk.Tk()
        window.withdraw()
        app = AstraDesktop(window)
        app.close()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                window.update()
                if not window.winfo_exists():
                    break
            except tk.TclError:
                break
            time.sleep(0.02)
        self.assertFalse(app.bridge.running)
        with self.assertRaises(RuntimeError):
            app.bridge.start("text")

    def test_file_panel_does_not_write_without_grant(self):
        from src.file_workspace import FileWorkspace
        from src.file_operations_ui import open_file_operations
        with tempfile.TemporaryDirectory(prefix="astra-file-ui-", dir=ROOT) as temp:
            window = tk.Tk()
            window.withdraw()
            app = AstraDesktop(window)
            try:
                self.pump(window, lambda: not app.busy)
                panel = open_file_operations(window, FileWorkspace(Path(temp)), app.button)
                self.pump(window, lambda: not panel.astra_file_busy[0])
                self.assertEqual(list(Path(temp).iterdir()), [])
                panel.astra_file_busy[0] = True
                app.close()
                self.assertFalse(app.closing)
                panel.astra_file_busy[0] = False
                panel.tk.call(panel.protocol("WM_DELETE_WINDOW"))
            finally:
                app.bridge.prevent_restart()
                app.bridge.stop()
                window.after_cancel(app.poll_timer)
                window.after_cancel(app.animation_timer)
                window.destroy()

    def test_file_browser_opens_safe_image_preview_without_model_request(self):
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix="astra-image-preview-", dir=ROOT) as temp:
            image_path = Path(temp) / "portrait.png"
            Image.new("RGBA", (40, 30), (140, 80, 220, 255)).save(image_path)
            window = tk.Tk()
            window.withdraw()
            app = AstraDesktop(window)
            try:
                self.pump(window, lambda: not app.busy)
                with patch("astra_desktop.filedialog.askdirectory", return_value=temp):
                    app.open_files()
                panel = next(item for item in window.winfo_children()
                             if isinstance(item, tk.Toplevel) and item.title().startswith("Astra · файлы"))
                self.pump(window, lambda: panel.astra_file_results.size() == 1)
                panel.astra_file_results.selection_set(0)
                panel.astra_open_selected()
                self.pump(window, lambda: any(
                    isinstance(item, tk.Toplevel) and item.title().startswith("Astra · просмотр изображения")
                    for item in panel.winfo_children()
                ))
                viewer = next(item for item in panel.winfo_children()
                              if isinstance(item, tk.Toplevel) and item.title().startswith("Astra · просмотр изображения"))
                self.assertIn("portrait.png", viewer.title())
                self.assertTrue(image_path.is_file())
            finally:
                app.bridge.prevent_restart()
                app.bridge.stop()
                window.after_cancel(app.poll_timer)
                window.after_cancel(app.animation_timer)
                window.destroy()

    def test_voice_file_search_grant_exists_only_while_selected_folder_window_is_open(self):
        with tempfile.TemporaryDirectory(prefix="astra-file-session-grant-", dir=ROOT) as temp:
            window = tk.Tk()
            window.withdraw()
            app = AstraDesktop(window)
            try:
                self.pump(window, lambda: not app.busy)
                with patch("astra_desktop.filedialog.askdirectory", return_value=temp):
                    app.open_files()
                panel = next(
                    item for item in window.winfo_children()
                    if isinstance(item, tk.Toplevel) and item.title().startswith("Astra · файлы")
                )
                self.assertIs(app.active_file_panel, panel)
                self.assertEqual(app.active_file_workspace.root, Path(temp).resolve())
                panel.destroy()
                window.update()
                self.assertIsNone(app.active_file_workspace)
                self.assertIsNone(app.active_file_panel)
            finally:
                app.bridge.prevent_restart()
                app.bridge.stop()
                window.after_cancel(app.poll_timer)
                window.after_cancel(app.animation_timer)
                window.destroy()

    def test_plan_ui_simulation_shows_read_only_steps_without_io(self):
        from src.file_workspace import FileWorkspace
        from src.plan_ui import open_plan_ui
        from src.skill_executor import SkillExecutor
        with tempfile.TemporaryDirectory(prefix="astra-plan-ui-", dir=ROOT) as temp:
            root = Path(temp)
            (root / "report.txt").write_text("private report", encoding="utf-8")
            window = tk.Tk()
            window.withdraw()
            button = lambda parent, text, command: tk.Button(parent, text=text, command=command)
            panel = open_plan_ui(window, FileWorkspace(root), button)
            try:
                panel.astra_skill_selector.set("Поиск файлов")
                panel.astra_argument_entry.insert(0, "report")
                panel.astra_add_step()
                self.assertEqual(panel.astra_run_button.cget("state"), "disabled")
                with patch.object(SkillExecutor, "execute", side_effect=AssertionError("simulation executed I/O")):
                    panel.astra_simulate_plan()
                    window.update()
                    output = panel.astra_plan_output.get("1.0", "end")
                    self.assertIn("файлы не читались и не изменялись", output)
                    self.assertIn("Требуется: разрешённая папка пользователя", output)
                    self.assertEqual(panel.astra_run_button.cget("state"), "normal")
                    with patch("src.plan_ui.messagebox.askyesno", return_value=False):
                        panel.astra_execute_plan()
                self.assertEqual((root / "report.txt").read_text(encoding="utf-8"), "private report")
                self.assertEqual(sorted(item.name for item in root.iterdir()), ["report.txt"])
            finally:
                panel.astra_close()
                window.destroy()

    def test_ai_plan_copy_requires_grant_preview_and_confirmation(self):
        from src.file_transactions import FileTransactions
        from src.file_workspace import FileWorkspace
        from src.plan_ui import open_plan_ui
        with tempfile.TemporaryDirectory(prefix="astra-plan-copy-ui-", dir=ROOT) as temp:
            root = Path(temp)
            (root / "source.bin").write_bytes(b"\x00\xffAstra")
            workspace = FileWorkspace(root)
            transactions = FileTransactions(workspace)
            transactions.grant_write(True)
            window = tk.Tk()
            window.withdraw()
            button = lambda parent, text, command: tk.Button(parent, text=text, command=command)
            panel = open_plan_ui(window, workspace, button, transactions=transactions)
            try:
                panel.astra_skill_selector.set("Копирование файла")
                panel.astra_skill_selector.event_generate("<<ComboboxSelected>>")
                window.update()
                panel.astra_argument_entry.insert(0, "source.bin")
                panel.astra_destination_entry.insert(0, "copy.bin")
                panel.astra_add_step()
                panel.astra_simulate_plan()
                window.update()
                self.assertFalse((root / "copy.bin").exists())
                self.assertIn("временное разрешение записи", panel.astra_plan_output.get("1.0", "end"))
                with patch("src.plan_ui.messagebox.askyesno", return_value=True) as confirm:
                    panel.astra_execute_plan()
                    self.assertIn("Источник: source.bin", confirm.call_args.args[1])
                    self.assertIn("Назначение: copy.bin", confirm.call_args.args[1])
                    self.pump(window, lambda: panel.astra_status.get() == "План завершён · проверь результат")
                self.assertEqual((root / "copy.bin").read_bytes(), b"\x00\xffAstra")
                self.assertTrue(transactions.history())
            finally:
                transactions.grant_write(False)
                panel.astra_close()
                window.destroy()

    def test_ai_plan_can_create_folder_and_rename_with_exact_confirmation(self):
        from src.file_transactions import FileTransactions
        from src.file_workspace import FileWorkspace
        from src.plan_ui import open_plan_ui
        with tempfile.TemporaryDirectory(prefix="astra-plan-rename-ui-", dir=ROOT) as temp:
            root = Path(temp)
            (root / "old.txt").write_text("safe", encoding="utf-8")
            workspace = FileWorkspace(root)
            transactions = FileTransactions(workspace)
            transactions.grant_write(True)
            window = tk.Tk()
            window.withdraw()
            button = lambda parent, text, command: tk.Button(parent, text=text, command=command)
            panel = open_plan_ui(window, workspace, button, transactions=transactions)
            try:
                panel.astra_skill_selector.set("Создание пустой папки")
                panel.astra_skill_selector.event_generate("<<ComboboxSelected>>")
                window.update()
                panel.astra_argument_entry.insert(0, "archive")
                panel.astra_add_step()
                panel.astra_skill_selector.set("Переименование файла")
                panel.astra_skill_selector.event_generate("<<ComboboxSelected>>")
                window.update()
                panel.astra_argument_entry.insert(0, "old.txt")
                panel.astra_destination_entry.insert(0, "new.txt")
                panel.astra_add_step()
                panel.astra_simulate_plan()
                window.update()
                with patch("src.plan_ui.messagebox.askyesno", return_value=True) as confirm:
                    panel.astra_execute_plan()
                    self.assertIn("Путь: archive", confirm.call_args.args[1])
                    self.assertIn("Источник: old.txt", confirm.call_args.args[1])
                    self.assertIn("Назначение: new.txt", confirm.call_args.args[1])
                    self.pump(window, lambda: panel.astra_status.get() == "План завершён · проверь результат")
                self.assertTrue((root / "archive").is_dir())
                self.assertEqual((root / "new.txt").read_text(encoding="utf-8"), "safe")
                self.assertFalse((root / "old.txt").exists())
            finally:
                transactions.grant_write(False)
                panel.astra_close()
                window.destroy()

    def test_file_operations_planner_reuses_the_same_write_grant_owner(self):
        from src.file_operations_ui import open_file_operations
        from src.file_transactions import FileTransactions
        from src.file_workspace import FileWorkspace
        with tempfile.TemporaryDirectory(prefix="astra-file-plan-entry-", dir=ROOT) as temp:
            window = tk.Tk()
            window.withdraw()
            workspace = FileWorkspace(Path(temp))
            button = lambda parent, text, command: tk.Button(parent, text=text, command=command)
            panel = open_file_operations(window, workspace, button)
            try:
                target = next(widget for widget in panel.winfo_children()
                              if isinstance(widget, tk.Button) and "Составить план" in widget.cget("text"))
                with patch("src.plan_ui.open_plan_ui") as open_planner:
                    target.invoke()
                open_planner.assert_called_once()
                args, kwargs = open_planner.call_args
                self.assertIs(args[0], panel)
                self.assertIs(args[1], workspace)
                self.assertIsInstance(kwargs["transactions"], FileTransactions)
                self.assertFalse(kwargs["transactions"].writable)
            finally:
                panel.destroy()
                window.destroy()

    def test_plan_ui_requires_local_request_consent_and_displays_model_proposal(self):
        from src.desktop_settings import AIProfile
        from src.file_workspace import FileWorkspace
        from src.skill_executor import ActionPlan, SkillCall
        from src.plan_ui import open_plan_ui
        with tempfile.TemporaryDirectory(prefix="astra-local-plan-ui-", dir=ROOT) as temp:
            window = tk.Tk()
            window.withdraw()
            button = lambda parent, text, command: tk.Button(parent, text=text, command=command)
            panel = open_plan_ui(window, FileWorkspace(Path(temp)), button)
            try:
                panel.astra_ai_request.insert(0, "Найди договоры за май")
                with patch("src.plan_ui.DesktopSettings.load", return_value=AIProfile(provider="ollama")) as load_profile, \
                     patch("src.plan_ui.PlanInterpreter") as interpreter:
                    panel.astra_propose_plan()
                    self.assertEqual(load_profile.call_count, 0)
                    self.assertEqual(interpreter.call_count, 0)
                    panel.astra_ai_consent.set(True)
                    interpreter.return_value.interpret.return_value = ActionPlan((
                        SkillCall("files.search", {"query": "договор"}),
                    ))
                    panel.astra_propose_plan()
                    self.pump(window, lambda: "Предложено шагов" in panel.astra_status.get())
                    self.assertEqual(load_profile.call_count, 1)
                    self.assertEqual(interpreter.call_count, 1)
                    self.assertIn("файлы не читались", panel.astra_plan_output.get("1.0", "end"))
                    self.assertEqual(panel.astra_run_button.cget("state"), "disabled")
                    self.assertIn("Поиск файлов: договор", panel.astra_steps_view.get(0))
            finally:
                panel.astra_close()
                window.destroy()

    def test_ai_settings_open_does_not_save_or_contact_server(self):
        from unittest.mock import patch
        from src.ai_settings_ui import open_ai_settings
        from src.desktop_settings import AIProfile, DesktopSettings
        window = tk.Tk()
        window.withdraw()
        app = AstraDesktop(window)
        try:
            with patch.object(DesktopSettings, "load", return_value=AIProfile()), \
                 patch.object(DesktopSettings, "save", side_effect=AssertionError("No automatic save")):
                panel = open_ai_settings(window, app.button, lambda: None)
                window.update()
                self.assertTrue(panel.winfo_exists())
                self.assertEqual(panel.astra_local_router_control.cget("state"), "disabled")
                self.assertFalse(panel.astra_local_router_variable.get())
                panel.astra_provider_selector.set("Локальный Ollama · без облака")
                panel.astra_provider_selector.event_generate("<<ComboboxSelected>>")
                window.update()
                self.assertEqual(panel.astra_local_router_control.cget("state"), "normal")
                self.assertFalse(panel.astra_current_profile().local_command_router_enabled)
                panel.astra_local_router_variable.set(True)
                self.assertTrue(panel.astra_current_profile().local_command_router_enabled)
                labels = set()
                stack = list(panel.winfo_children())
                while stack:
                    item = stack.pop()
                    stack.extend(item.winfo_children())
                    if isinstance(item, tk.Button):
                        labels.add(item.cget("text"))
                self.assertIn("Экспорт профиля…", labels)
                self.assertIn("Импорт профиля…", labels)
                panel.tk.call(panel.protocol("WM_DELETE_WINDOW"))
        finally:
            app.bridge.prevent_restart()
            app.bridge.stop()
            window.after_cancel(app.poll_timer)
            window.after_cancel(app.animation_timer)
            window.destroy()

    def test_profile_backup_export_and_confirmed_import_work_from_settings(self):
        import os
        from src.ai_settings_ui import open_ai_settings
        from src.desktop_settings import AIProfile, DesktopSettings
        from src.profile_backup import import_profile
        with tempfile.TemporaryDirectory(prefix="astra-profile-ui-") as temp:
            with patch.dict(os.environ, {"LOCALAPPDATA": temp}):
                window = tk.Tk()
                window.withdraw()
                app = AstraDesktop(window)
                saved = []
                panels = []
                try:
                    panel = open_ai_settings(window, app.button, lambda: saved.append(True))
                    panels.append(panel)
                    window.update()
                    def button_named(name):
                        stack = list(panel.winfo_children())
                        while stack:
                            item = stack.pop()
                            stack.extend(item.winfo_children())
                            if isinstance(item, tk.Button) and item.cget("text") == name:
                                return item
                        raise AssertionError("Settings action is missing: " + name)
                    passphrase = "correct horse battery staple"
                    backup = Path(temp) / "profile.astra-profile-backup"
                    with patch("src.ai_settings_ui.simpledialog.askstring", side_effect=[passphrase, passphrase]), \
                         patch("src.ai_settings_ui.filedialog.asksaveasfilename", return_value=str(backup)):
                        button_named("Экспорт профиля…").invoke()
                        self.pump(window, lambda: backup.is_file() and not panel.astra_busy[0])
                    exported = import_profile(backup, passphrase)
                    self.assertEqual(exported.provider, "env")

                    replacement = AIProfile(
                        provider="disabled", assistant_name="Сая", avatar_id="female_saya",
                        character_profiles={"female_saya": {"assistant_name": "Сая", "voice_id": ""}},
                    ).validate()
                    from src.profile_backup import export_profile
                    replacement_file = Path(temp) / "replacement.astra-profile-backup"
                    export_profile(replacement_file, replacement, passphrase)
                    with patch("src.ai_settings_ui.filedialog.askopenfilename", return_value=str(replacement_file)), \
                         patch("src.ai_settings_ui.simpledialog.askstring", return_value=passphrase), \
                         patch("src.ai_settings_ui.messagebox.askyesno", return_value=True):
                        button_named("Импорт профиля…").invoke()
                        self.pump(window, lambda: bool(saved))
                    imported = DesktopSettings().load()
                    self.assertEqual(imported.provider, "disabled")
                    self.assertEqual(imported.assistant_name, "Сая")
                    self.assertEqual(imported.avatar_id, "female_saya")
                    self.assertEqual(imported.character_profiles["female_saya"]["assistant_name"], "Сая")
                finally:
                    for panel in panels:
                        if panel.winfo_exists():
                            panel.destroy()
                    app.bridge.prevent_restart()
                    app.bridge.stop()
                    window.after_cancel(app.poll_timer)
                    window.after_cancel(app.animation_timer)
                    window.destroy()

    def test_portable_memory_backup_requires_confirmation_and_is_available_in_memory_panel(self):
        import os
        from src.personal_memory import PersonalMemory
        from src.portable_memory_backup import decrypt_memory
        with tempfile.TemporaryDirectory(prefix="astra-portable-memory-ui-") as temp:
            root = Path(temp)
            source = PersonalMemory(root / "source.sqlite")
            source.add("Импортируемая заметка", "Только после явного согласия")
            passphrase = "correct horse battery staple"
            incoming = root / "incoming.astra-memory-portable"
            source.create_portable_backup(incoming, passphrase)
            outgoing = root / "outgoing.astra-memory-portable"
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root / "profile")}):
                window = tk.Tk()
                window.withdraw()
                app = AstraDesktop(window)
                panel = None
                try:
                    app.open_memory()
                    window.update()
                    panel = next(item for item in window.winfo_children()
                                 if isinstance(item, tk.Toplevel) and item.title() == "Astra · личная память")
                    def button_named(name):
                        stack = list(panel.winfo_children())
                        while stack:
                            item = stack.pop()
                            stack.extend(item.winfo_children())
                            if isinstance(item, tk.Button) and item.cget("text") == name:
                                return item
                        raise AssertionError("Memory action is missing: " + name)
                    self.assertIsNotNone(button_named("Создать переносимую копию"))
                    self.assertIsNotNone(button_named("Восстановить переносимую копию"))
                    with patch("tkinter.simpledialog.askstring", return_value=passphrase), \
                         patch("tkinter.filedialog.askopenfilename", return_value=str(incoming)), \
                         patch("tkinter.messagebox.askyesno", return_value=True):
                        button_named("Восстановить переносимую копию").invoke()
                    target = PersonalMemory(root / "profile" / "AstraVoiceAssistant" / "memory.sqlite")
                    self.assertEqual(target.search()[0].text, "Только после явного согласия")
                    with patch("tkinter.simpledialog.askstring", side_effect=[passphrase, passphrase]), \
                         patch("tkinter.filedialog.asksaveasfilename", return_value=str(outgoing)):
                        button_named("Создать переносимую копию").invoke()
                    exported = decrypt_memory(outgoing.read_bytes(), passphrase)
                    self.assertEqual(exported[0]["title"], "Импортируемая заметка")
                finally:
                    if panel is not None and panel.winfo_exists():
                        panel.destroy()
                    app.bridge.prevent_restart()
                    app.bridge.stop()
                    window.after_cancel(app.poll_timer)
                    window.after_cancel(app.animation_timer)
                    window.destroy()

    def test_permission_center_revokes_scope_in_isolated_dpapi_profile(self):
        import os
        from src.ai_settings_ui import open_ai_settings
        from src.action_policy import ActionPolicy
        from src.desktop_settings import DesktopSettings
        from src.task_router import ActionType, AssistantAction
        with tempfile.TemporaryDirectory(prefix="astra-permission-ui-") as temp:
            window = tk.Tk()
            window.withdraw()
            app = AstraDesktop(window)
            saved = []
            try:
                with patch.dict(os.environ, {"LOCALAPPDATA": temp}):
                    panel = open_ai_settings(window, app.button, lambda: saved.append(True))
                    tabs = next(item for item in panel.winfo_children() if isinstance(item, ttk.Notebook))
                    tabs.select(2)
                    window.update()
                    checkboxes = {}
                    stack = list(panel.winfo_children())
                    while stack:
                        item = stack.pop()
                        stack.extend(item.winfo_children())
                        if isinstance(item, tk.Checkbutton):
                            checkboxes[item.cget("text")] = item
                    apps = checkboxes["Приложения из разрешённого списка"]
                    self.assertTrue(apps.winfo_ismapped())
                    apps.invoke()
                    buttons = [item for item in tabs.nametowidget(tabs.tabs()[2]).winfo_children()
                               if isinstance(item, tk.Button) and item.cget("text") == "Сохранить разрешения"]
                    buttons[0].invoke()
                    self.assertEqual(saved, [True])
                    profile = DesktopSettings().load()
                    self.assertNotIn("apps", profile.allowed_scopes)
                    action = AssistantAction(ActionType.OPEN_APP, target="calculator")
                    self.assertFalse(ActionPolicy(profile.allowed_scopes).check(action).allowed)
                    panel.tk.call(panel.protocol("WM_DELETE_WINDOW"))
            finally:
                app.bridge.prevent_restart()
                app.bridge.stop()
                window.after_cancel(app.poll_timer)
                window.after_cancel(app.animation_timer)
                window.destroy()

    def test_permission_center_scrolls_cards_and_keeps_actions_visible(self):
        import os
        from src.ai_settings_ui import open_ai_settings
        with tempfile.TemporaryDirectory(prefix="astra-permission-layout-") as temp, patch.dict(os.environ, {"LOCALAPPDATA": temp}):
            window = tk.Tk()
            window.withdraw()
            app = AstraDesktop(window)
            try:
                panel = open_ai_settings(window, app.button, lambda: None)
                panel.geometry("780x668")
                tabs = next(item for item in panel.winfo_children() if isinstance(item, ttk.Notebook))
                tabs.select(2)
                window.update()
                permissions = tabs.nametowidget(tabs.tabs()[2])
                self.assertTrue(panel.astra_permission_save.winfo_ismapped())
                self.assertTrue(panel.astra_permission_backup.winfo_ismapped())
                self.assertLessEqual(
                    panel.astra_permission_save.winfo_rooty() + panel.astra_permission_save.winfo_height(),
                    panel.winfo_rooty() + panel.winfo_height(),
                )
                self.assertLessEqual(
                    panel.astra_permission_backup.winfo_rooty() + panel.astra_permission_backup.winfo_height(),
                    panel.winfo_rooty() + panel.winfo_height(),
                )
                canvas = permissions.astra_canvas
                self.assertGreater(canvas.winfo_height(), 0)
                files_card = panel.astra_permission_cards["files"]
                self.assertEqual(files_card.cget("text"), "Поиск файлов в выбранной папке")
                open_files_card = panel.astra_permission_cards["open_files"]
                self.assertEqual(open_files_card.cget("text"), "Открытие файлов голосом")
                last_card = open_files_card
                last_card.event_generate("<FocusIn>")
                window.update()
                self.assertGreater(canvas.yview()[0], 0)
                self.assertLessEqual(
                    last_card.winfo_rooty() + last_card.winfo_height(),
                    canvas.winfo_rooty() + canvas.winfo_height(),
                )
                self.assertTrue(last_card.winfo_ismapped())
            finally:
                app.bridge.prevent_restart()
                app.bridge.stop()
                window.after_cancel(app.poll_timer)
                window.after_cancel(app.animation_timer)
                panel.destroy()
                window.destroy()

    def test_character_selector_changes_default_name_and_persists_choice(self):
        import os
        from src.ai_settings_ui import open_ai_settings
        from src.desktop_settings import AIProfile, DesktopSettings
        with tempfile.TemporaryDirectory(prefix="astra-avatar-ui-") as temp:
            window = tk.Tk()
            window.withdraw()
            app = AstraDesktop(window)
            saved = []
            try:
                with patch.dict(os.environ, {"LOCALAPPDATA": temp}):
                    DesktopSettings().save(AIProfile(
                        provider="disabled", assistant_name="Мику", avatar_id="female_miku", voice_id="female-voice",
                        character_profiles={
                            "female_miku": {"assistant_name": "Мику", "voice_id": "female-voice"},
                            "male_ren": {"assistant_name": "Рэн", "voice_id": "male-voice"},
                        },
                    ))
                    panel = open_ai_settings(window, app.button, lambda: saved.append(True))
                    self.assertTrue(panel.astra_avatar_preview.cget("image"))
                    self.assertEqual(panel.astra_avatar_preview_name.get(), "Мику")
                    initial_portrait = panel.astra_avatar_preview.cget("image")
                    tabs = next(item for item in panel.winfo_children() if isinstance(item, ttk.Notebook))
                    voice_tab = tabs.nametowidget(tabs.tabs()[1])
                    combos = []
                    entries = []
                    buttons = []
                    stack = list(voice_tab.winfo_children())
                    while stack:
                        item = stack.pop()
                        stack.extend(item.winfo_children())
                        if isinstance(item, ttk.Combobox):
                            combos.append(item)
                        if type(item) is tk.Entry:
                            entries.append(item)
                        if isinstance(item, tk.Button) and item.cget("text") == "Сохранить голос и микрофон":
                            buttons.append(item)
                    character = next(item for item in combos if "Рэн · мужской образ" in item.cget("values"))
                    self.assertEqual(len(character.cget("values")), 4)
                    voice = next(item for item in combos if any("female-voice" in str(value) for value in item.cget("values")))
                    character.set("Рэн · мужской образ")
                    character.event_generate("<<ComboboxSelected>>")
                    window.update()
                    name = entries[0]
                    self.assertEqual(name.get(), "Рэн")
                    self.assertEqual(panel.astra_avatar_preview_name.get(), "Рэн")
                    ren_portrait = panel.astra_avatar_preview.cget("image")
                    self.assertNotEqual(ren_portrait, initial_portrait)
                    self.assertIn("male-voice", voice.get())
                    name.delete(0, "end")
                    name.insert(0, "Сова")
                    panel.astra_refresh_avatar_preview()
                    window.update()
                    self.assertEqual(panel.astra_avatar_preview_name.get(), "Сова")
                    character.set("Мику · женский образ")
                    character.event_generate("<<ComboboxSelected>>")
                    window.update()
                    self.assertEqual(name.get(), "Мику")
                    self.assertEqual(panel.astra_avatar_preview_name.get(), "Мику")
                    self.assertIn("female-voice", voice.get())
                    character.set("Рэн · мужской образ")
                    character.event_generate("<<ComboboxSelected>>")
                    window.update()
                    self.assertEqual(name.get(), "Сова")
                    self.assertIn("male-voice", voice.get())
                    self.assertIn("Сая · женский образ", character.cget("values"))
                    self.assertIn("Кай · мужской образ", character.cget("values"))
                    character.set("Сая · женский образ")
                    character.event_generate("<<ComboboxSelected>>")
                    window.update()
                    self.assertEqual(name.get(), "Сая")
                    self.assertEqual(panel.astra_avatar_preview_name.get(), "Сая")
                    saya_portrait = panel.astra_avatar_preview.cget("image")
                    self.assertNotEqual(saya_portrait, ren_portrait)
                    name.delete(0, "end")
                    name.insert(0, "Юна")
                    panel.astra_refresh_avatar_preview()
                    window.update()
                    self.assertEqual(panel.astra_avatar_preview_name.get(), "Юна")
                    character.set("Кай · мужской образ")
                    character.event_generate("<<ComboboxSelected>>")
                    window.update()
                    self.assertEqual(name.get(), "Кай")
                    self.assertEqual(panel.astra_avatar_preview_name.get(), "Кай")
                    kai_portrait = panel.astra_avatar_preview.cget("image")
                    self.assertNotEqual(kai_portrait, saya_portrait)
                    name.delete(0, "end")
                    name.insert(0, "Кайто")
                    panel.astra_refresh_avatar_preview()
                    window.update()
                    self.assertEqual(panel.astra_avatar_preview_name.get(), "Кайто")
                    character.set("Сая · женский образ")
                    character.event_generate("<<ComboboxSelected>>")
                    window.update()
                    self.assertEqual(name.get(), "Юна")
                    character.set("Кай · мужской образ")
                    character.event_generate("<<ComboboxSelected>>")
                    window.update()
                    self.assertEqual(name.get(), "Кайто")
                    self.assertEqual(panel.astra_avatar_preview_name.get(), "Кайто")
                    unsaved = DesktopSettings().load()
                    self.assertEqual(unsaved.avatar_id, "female_miku")
                    self.assertNotIn("female_saya", unsaved.character_profiles)
                    buttons[0].invoke()
                    profile = DesktopSettings().load()
                    self.assertEqual((profile.avatar_id, profile.assistant_name), ("male_kai", "Кайто"))
                    self.assertEqual(profile.character_profiles["female_miku"], {"assistant_name": "Мику", "voice_id": "female-voice"})
                    self.assertEqual(profile.character_profiles["male_ren"], {"assistant_name": "Сова", "voice_id": "male-voice"})
                    self.assertEqual(profile.character_profiles["female_saya"], {"assistant_name": "Юна", "voice_id": ""})
                    self.assertEqual(profile.character_profiles["male_kai"], {"assistant_name": "Кайто", "voice_id": ""})
                    self.assertEqual(saved, [True])
                    panel.tk.call(panel.protocol("WM_DELETE_WINDOW"))
            finally:
                app.bridge.prevent_restart()
                app.bridge.stop()
                window.after_cancel(app.poll_timer)
                window.after_cancel(app.animation_timer)
                window.destroy()

    def test_3d_preview_uses_unsaved_avatar_and_name_and_prevents_duplicate_windows(self):
        import os
        from src.ai_settings_ui import open_ai_settings
        from src.desktop_settings import AIProfile, DesktopSettings
        with tempfile.TemporaryDirectory(prefix="astra-3d-preview-ui-") as temp:
            window = tk.Tk()
            window.withdraw()
            app = AstraDesktop(window)
            try:
                with patch.dict(os.environ, {"LOCALAPPDATA": temp}):
                    DesktopSettings().save(AIProfile(provider="disabled", avatar_id="female_miku", assistant_name="Мику"))
                    app.busy = False
                    for text, expected in (("Ожидаю команду", "idle"), ("Слушаю", "listening"),
                                           ("Распознаю речь", "recognizing"), ("Говорю", "speaking"),
                                           ("Ошибка микрофона", "error")):
                        app.status.set(text)
                        self.assertEqual(app.avatar_state(), expected)
                    app.status.set("Ожидаю команду")
                    panel = open_ai_settings(window, app.button, lambda: None, app=app)
                    tabs = next(item for item in panel.winfo_children() if isinstance(item, ttk.Notebook))
                    voice_tab = tabs.nametowidget(tabs.tabs()[1])
                    stack = list(voice_tab.winfo_children())
                    combos, entries = [], []
                    while stack:
                        item = stack.pop()
                        stack.extend(item.winfo_children())
                        if isinstance(item, ttk.Combobox):
                            combos.append(item)
                        if type(item) is tk.Entry:
                            entries.append(item)
                    character = next(item for item in combos if "Рэн · мужской образ" in item.cget("values"))
                    character.set("Рэн · мужской образ")
                    character.event_generate("<<ComboboxSelected>>")
                    window.update()
                    entries[0].delete(0, "end")
                    entries[0].insert(0, "Егорова Астра")
                    fake_process = type("FakeProcess", (), {"poll": lambda self: None})()
                    with patch("src.avatar_preview.launch_avatar_preview", return_value=fake_process) as launch, \
                            patch("src.ai_settings_ui.messagebox.showerror") as show_error:
                        panel.astra_preview_3d()
                        self.assertFalse(show_error.called, show_error.call_args)
                        launch.assert_called_once_with("male_ren", "Егорова Астра", initial_state="idle")
                        panel.astra_preview_3d()
                        self.assertEqual(launch.call_count, 1)
                    self.assertEqual(DesktopSettings().load().avatar_id, "female_miku")
                    panel.destroy()
            finally:
                app.bridge.prevent_restart()
                app.bridge.stop()
                window.after_cancel(app.poll_timer)
                window.after_cancel(app.animation_timer)
                window.destroy()

    def test_reminder_worker_delivers_to_chat_and_stops(self):
        from src.reminders import ReminderStore
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.sqlite")
            store.add("Синтетическое напоминание", time.time() - 1)
            window = tk.Tk()
            window.withdraw()
            app = AstraDesktop(window, reminder_store=store)
            try:
                self.pump(window, lambda: "Синтетическое напоминание" in app.chat.get("1.0", "end"))
                self.assertEqual(store.unread_count(), 1)
            finally:
                app.reminder_worker.stop()
                app.bridge.prevent_restart()
                app.bridge.stop()
                window.after_cancel(app.poll_timer)
                window.after_cancel(app.animation_timer)
                window.destroy()

    def test_voice_settings_controls_fit_and_do_not_capture_audio(self):
        from src.ai_settings_ui import open_ai_settings
        from src.desktop_settings import DesktopSettings
        window = tk.Tk()
        window.withdraw()
        app = AstraDesktop(window)
        try:
            panel = open_ai_settings(window, app.button, lambda: None)
            panel.geometry("780x668")
            tabs = next(item for item in panel.winfo_children() if isinstance(item, ttk.Notebook))
            tabs.select(1)
            self.pump(window, lambda: not app.busy)
            window.update()
            self.assertIn("image", {app.avatar.type(item) for item in app.avatar.find_all()})
            voice = tabs.nametowidget(tabs.tabs()[1])
            stack = list(voice.winfo_children())
            buttons = []
            while stack:
                item = stack.pop()
                stack.extend(item.winfo_children())
                if isinstance(item, tk.Button):
                    buttons.append(item)
            self.assertGreaterEqual(len(buttons), 3)
            for item in buttons:
                self.assertTrue(item.winfo_ismapped(), item.cget("text"))
                y = item.winfo_rooty() - panel.winfo_rooty()
                self.assertGreaterEqual(y, 0, item.cget("text"))
                self.assertLessEqual(y + item.winfo_height(), panel.winfo_height(), item.cget("text"))
            with patch.object(DesktopSettings, "save", side_effect=AssertionError("Opening settings cannot save")):
                self.assertTrue(panel.winfo_exists())
                self.assertEqual(app.bridge.mode, "text")
            panel.tk.call(panel.protocol("WM_DELETE_WINDOW"))
        finally:
            app.bridge.prevent_restart()
            app.bridge.stop()
            window.after_cancel(app.poll_timer)
            window.after_cancel(app.animation_timer)
            window.destroy()

    def test_each_character_switches_to_its_speaking_portrait_and_back(self):
        from src.desktop_settings import AVATAR_PROFILES
        window = tk.Tk()
        window.withdraw()
        app = AstraDesktop(window)
        try:
            self.pump(window, lambda: not app.busy)

            def render():
                if app.animation_timer is not None:
                    window.after_cancel(app.animation_timer)
                    app.animation_timer = None
                app.animate()
                window.update_idletasks()
                return app.avatar_photo

            sample = [(x, y) for y in range(105, 165, 3) for x in range(95, 160, 3)]
            for avatar_id, profile in AVATAR_PROFILES.items():
                with self.subTest(avatar_id=avatar_id):
                    app.avatar_id = avatar_id
                    app.status.set("Ожидаю команду")
                    idle = render()
                    self.assertIsNotNone(idle)
                    app.status.set("Говорю")
                    app.phase = 0.2
                    speaking = render()
                    self.assertIsNotNone(speaking)
                    self.assertTrue(any(idle.get(x, y) != speaking.get(x, y) for x, y in sample))
                    app.phase = 0.6
                    mid_speech_closed = render()
                    self.assertTrue(any(speaking.get(x, y) != mid_speech_closed.get(x, y) for x, y in sample))
                    app.status.set("Слушаю")
                    returned = render()
                    self.assertTrue(all(idle.get(x, y) == returned.get(x, y) for x, y in sample))
                    self.assertTrue(Path(ROOT / "assets" / "avatars" / profile["speaking_asset"]).is_file())
        finally:
            if app.animation_timer is not None:
                window.after_cancel(app.animation_timer)
            app.bridge.prevent_restart()
            app.bridge.stop()
            window.after_cancel(app.poll_timer)
            window.destroy()

    def test_first_run_onboarding_is_optional_and_never_enables_microphone(self):
        import os
        with tempfile.TemporaryDirectory(prefix="astra-first-run-") as temp:
            local_app_data = Path(temp) / "LocalAppData"
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}):
                window = tk.Tk()
                window.withdraw()
                app = AstraDesktop(window)
                try:
                    self.pump(window, lambda: not app.busy)
                    settings_path = local_app_data / "AstraVoiceAssistant" / "settings.dpapi"
                    self.assertTrue(app.onboarding_available)
                    self.assertIsNotNone(app.onboarding_banner)
                    self.assertEqual(app.bridge.mode, "text")
                    self.assertFalse(settings_path.exists())
                    self.assertEqual(app.onboarding_banner.winfo_manager(), "pack")
                    buttons = [
                        item for item in app.onboarding_banner.winfo_children()[1:]
                        if isinstance(item, tk.Button)
                    ]
                    self.assertEqual({button.cget("text") for button in buttons}, {"Настроить", "Пока пропустить"})
                    next(button for button in buttons if button.cget("text") == "Пока пропустить").invoke()
                    window.update_idletasks()
                    self.assertEqual(app.onboarding_banner.winfo_manager(), "")
                    self.assertFalse(settings_path.exists())
                    state_path = local_app_data / "AstraVoiceAssistant" / "onboarding.dpapi"
                    self.assertTrue(state_path.exists())
                    from src.onboarding_state import OnboardingState
                    self.assertTrue(OnboardingState(state_path).dismissed())
                    self.assertEqual(app.bridge.mode, "text")
                finally:
                    app.bridge.prevent_restart()
                    app.bridge.stop()
                    if app.onboarding_banner is not None:
                        app.onboarding_banner.destroy()
                    window.after_cancel(app.poll_timer)
                    window.after_cancel(app.animation_timer)
                    window.destroy()
                reopened = tk.Tk()
                reopened.withdraw()
                second_app = AstraDesktop(reopened)
                try:
                    self.pump(reopened, lambda: not second_app.busy)
                    self.assertFalse(second_app.onboarding_available)
                    self.assertIsNone(second_app.onboarding_banner)
                    self.assertFalse(settings_path.exists())
                    self.assertEqual(second_app.bridge.mode, "text")
                finally:
                    second_app.bridge.prevent_restart()
                    second_app.bridge.stop()
                    reopened.after_cancel(second_app.poll_timer)
                    reopened.after_cancel(second_app.animation_timer)
                    reopened.destroy()

    def test_onboarding_saves_selected_character_without_starting_voice_or_network(self):
        import os
        from src.desktop_settings import DesktopSettings
        with tempfile.TemporaryDirectory(prefix="astra-onboarding-save-") as temp:
            local_app_data = Path(temp) / "LocalAppData"
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}):
                window = tk.Tk()
                window.withdraw()
                app = AstraDesktop(window)
                setup = None
                try:
                    self.pump(window, lambda: not app.busy)
                    configure = next(
                        item for item in app.onboarding_banner.winfo_children()[1:]
                        if isinstance(item, tk.Button) and item.cget("text") == "Настроить"
                    )
                    configure.invoke()
                    setup = next(
                        item for item in window.winfo_children()
                        if isinstance(item, tk.Toplevel) and item is not window
                    )
                    setup.astra_avatar_choice.set("Кай · мужской образ")
                    setup.astra_avatar_choice.event_generate("<<ComboboxSelected>>")
                    window.update()
                    setup.astra_name_entry.delete(0, "end")
                    setup.astra_name_entry.insert(0, "Кайто")
                    setup.astra_next_button.invoke()
                    self.assertEqual(setup.astra_step(), 1)
                    setup.astra_provider_var.set("ollama")
                    setup.astra_next_button.invoke()
                    self.assertEqual(setup.astra_step(), 2)
                    self.assertIn("Кайто", setup.astra_summary.get())
                    setup.astra_next_button.invoke()
                    self.pump(window, lambda: not app.busy)

                    profile = DesktopSettings().load()
                    self.assertEqual((profile.assistant_name, profile.avatar_id), ("Кайто", "male_kai"))
                    self.assertEqual(profile.provider, "ollama")
                    self.assertEqual(profile.base_url, "http://127.0.0.1:11434")
                    self.assertEqual(app.bridge.mode, "text")
                    self.assertFalse(app.onboarding_available)
                    self.assertIsNone(app.onboarding_banner)
                finally:
                    if setup is not None:
                        try:
                            setup.destroy()
                        except tk.TclError:
                            pass
                    app.bridge.prevent_restart()
                    app.bridge.stop()
                    if app.onboarding_banner is not None:
                        app.onboarding_banner.destroy()
                    window.after_cancel(app.poll_timer)
                    window.after_cancel(app.animation_timer)
                    window.destroy()

    def test_tray_hide_restore_and_close(self):
        window = tk.Tk()
        app = AstraDesktop(window)
        try:
            self.pump(window, lambda: not app.busy)
            app.hide_to_tray()
            window.update()
            self.assertEqual(window.state(), "withdrawn")
            app.bridge.emit("tray_show", "")
            self.pump(window, lambda: window.state() == "normal")
            app.bridge.emit("tray_exit", "")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    window.update()
                    if not window.winfo_exists():
                        break
                except tk.TclError:
                    break
                time.sleep(.02)
            self.assertFalse(app.tray.thread.is_alive())
            self.assertFalse(app.bridge.running)
        finally:
            app.bridge.stop()
            if app.tray is not None:
                app.tray.stop()
            try:
                window.destroy()
            except tk.TclError:
                pass

    def test_primary_controls_fit_minimum_window(self):
        window = tk.Tk()
        app = AstraDesktop(window)
        try:
            window.geometry("840x680")
            self.pump(window, lambda: not app.busy)
            window.update()
            widgets = list(window.winfo_children())
            controls = []
            while widgets:
                item = widgets.pop()
                widgets.extend(item.winfo_children())
                if isinstance(item, (tk.Button, tk.Entry)):
                    controls.append(item)
            self.assertGreater(len(controls), 10)
            for item in controls:
                label = item.cget("text") if isinstance(item, tk.Button) else "entry"
                self.assertTrue(item.winfo_ismapped(), label)
                x = item.winfo_rootx() - window.winfo_rootx()
                y = item.winfo_rooty() - window.winfo_rooty()
                self.assertGreaterEqual(x, 0, label)
                self.assertGreaterEqual(y, 0, label)
                self.assertLessEqual(x + item.winfo_width(), window.winfo_width(), label)
                self.assertLessEqual(y + item.winfo_height(), window.winfo_height(), label)
        finally:
            app.bridge.prevent_restart()
            app.bridge.stop()
            window.after_cancel(app.poll_timer)
            window.after_cancel(app.animation_timer)
            window.destroy()

    def test_file_question_and_reminder_controls_are_visible(self):
        from unittest.mock import patch
        from src.file_workspace import FileWorkspace
        from src.file_rag_ui import open_file_questions
        from src.file_operations_ui import open_file_operations
        from src.reminders_ui import open_reminders
        from src.reminders import ReminderStore
        with tempfile.TemporaryDirectory(prefix="astra-panels-test-", dir=ROOT) as temp:
            directory = Path(temp)
            (directory / "test.txt").write_text("Тест", encoding="utf-8")
            window = tk.Tk()
            app = AstraDesktop(window)
            try:
                self.pump(window, lambda: not app.busy)
                with patch("tkinter.filedialog.askdirectory", return_value=temp):
                    app.open_files()
                panels = [child for child in window.winfo_children() if isinstance(child, tk.Toplevel)]
                panels.append(open_file_questions(window, FileWorkspace(directory), "test.txt", app.button))
                reminder_panel = open_reminders(window, ReminderStore(directory / "tasks.sqlite"), app.button)
                panels.append(reminder_panel)
                operations = open_file_operations(window, FileWorkspace(directory), app.button)
                panels.append(operations)
                self.pump(window, lambda: not operations.astra_file_busy[0])
                window.update()
                reminder_buttons = set()
                stack = list(reminder_panel.winfo_children())
                while stack:
                    widget = stack.pop()
                    stack.extend(widget.winfo_children())
                    if isinstance(widget, tk.Button):
                        reminder_buttons.add(widget.cget("text"))
                self.assertIn("Экспорт переносимой копии…", reminder_buttons)
                self.assertIn("Импорт переносимой копии…", reminder_buttons)
                for panel in panels:
                    stack = list(panel.winfo_children())
                    while stack:
                        widget = stack.pop()
                        stack.extend(widget.winfo_children())
                        if isinstance(widget, tk.Button):
                            label = widget.cget("text")
                            self.assertTrue(widget.winfo_ismapped(), label)
                            y = widget.winfo_rooty() - panel.winfo_rooty()
                            self.assertGreaterEqual(y, 0, label)
                            self.assertLessEqual(y + widget.winfo_height(), panel.winfo_height(), label)
                checkboxes = [widget for widget in operations.winfo_children() if isinstance(widget, tk.Checkbutton)]
                trash_grant = next(widget for widget in checkboxes if "Корзину Windows" in widget.cget("text"))
                self.assertEqual(int(trash_grant.getvar(trash_grant.cget("variable"))), 0)
            finally:
                app.bridge.prevent_restart()
                app.bridge.stop()
                window.after_cancel(app.poll_timer)
                window.after_cancel(app.animation_timer)
                window.destroy()

    def test_multi_file_question_requires_consent_and_shows_each_source(self):
        from src.desktop_settings import AIProfile
        from src.file_rag_ui import open_file_questions
        from src.file_workspace import FileWorkspace
        from src.ollama_client import OllamaClient
        with tempfile.TemporaryDirectory(prefix="astra-multi-file-ui-", dir=ROOT) as temp:
            root = Path(temp)
            (root / "alpha.txt").write_text("Бюджет Альфа: 900 рублей", encoding="utf-8")
            (root / "beta.txt").write_text("Бюджет Бета: 1200 рублей", encoding="utf-8")
            window = tk.Tk()
            window.withdraw()
            button = lambda parent, text, command: tk.Button(parent, text=text, command=command)
            panel = open_file_questions(window, FileWorkspace(root), ("alpha.txt", "beta.txt"), button)
            try:
                self.assertIn("до 5 файлов", panel.winfo_children()[1].cget("text"))
                panel.astra_question_entry.insert(0, "Сравни бюджет Альфа и Бета")
                with patch("src.file_rag_ui.DesktopSettings.load", return_value=AIProfile(provider="ollama")) as load_profile, \
                     patch.object(OllamaClient, "chat", return_value="Альфа 900, Бета 1200 [1] [2]") as chat:
                    panel.astra_ask()
                    self.assertEqual(load_profile.call_count, 0)
                    self.assertEqual(chat.call_count, 0)
                    panel.astra_question_allowed.set(True)
                    panel.astra_ask()
                    self.pump(window, lambda: "может ошибаться" in panel.astra_question_status.get())
                    self.assertEqual(load_profile.call_count, 1)
                    self.assertEqual(chat.call_count, 1)
                    rendered = panel.astra_question_content.get("1.0", "end")
                    self.assertIn("alpha.txt", rendered)
                    self.assertIn("beta.txt", rendered)
            finally:
                panel.destroy()
                window.destroy()

    def test_file_browser_opens_question_for_exactly_selected_files(self):
        from unittest.mock import Mock
        window = tk.Tk()
        window.withdraw()
        app = AstraDesktop(window)
        panel = None
        try:
            self.pump(window, lambda: not app.busy)
            with tempfile.TemporaryDirectory(prefix="astra-file-multiselect-", dir=ROOT) as temp:
                for index in range(6):
                    (Path(temp) / f"doc-{index}.txt").write_text(f"document {index}", encoding="utf-8")
                with patch("tkinter.filedialog.askdirectory", return_value=temp):
                    app.open_files()
                panel = next(child for child in window.winfo_children() if isinstance(child, tk.Toplevel))
                self.pump(window, lambda: panel.astra_file_results.size() == 6)
                self.assertEqual(panel.astra_file_results.cget("selectmode"), "extended")
                opener = Mock()
                with patch.dict(AstraDesktop.open_files.__globals__, {"open_file_questions": opener}):
                    panel.astra_file_results.selection_set(0, 5)
                    panel.astra_ask_selected_many()
                    opener.assert_not_called()
                    self.assertIn("не больше пяти", panel.astra_files_status.get())
                    panel.astra_file_results.selection_clear(0, tk.END)
                    panel.astra_file_results.selection_set(0, 1)
                    expected = tuple(panel.astra_file_results.get(index) for index in panel.astra_file_results.curselection())
                    panel.astra_ask_selected_many()
                opener.assert_called_once()
                args = opener.call_args.args
                self.assertIs(args[0], panel)
                self.assertEqual(args[1].root, Path(temp).resolve())
                self.assertEqual(args[2], expected)
                self.assertIs(args[3].__self__, app)
                self.assertIs(args[3].__func__, app.button.__func__)
        finally:
            if panel is not None:
                panel.destroy()
            app.bridge.prevent_restart()
            app.bridge.stop()
            if app.poll_timer is not None:
                window.after_cancel(app.poll_timer)
            if app.animation_timer is not None:
                window.after_cancel(app.animation_timer)
            window.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
