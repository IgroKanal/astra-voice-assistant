"""Offline Qt interaction tests with a synthetic runtime bridge."""
import json
import os
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import astra_desktop_qt as qt
from src.desktop_file_search import make_search_request
from src.desktop_settings import AIProfile, AVATAR_PROFILES
from src.file_workspace import FileWorkspace
from src.qt_dialogs import (
    ActionAuditDialog, CommandCatalogDialog, FileOperationsDialog,
    FilePlanDialog, FileQuestionDialog, OnboardingDialog,
)
from src.qt_voice_files import QtVoiceFileController


class FakeBridge:
    def __init__(self, _root):
        self.events = queue.Queue()
        self.running = False
        self.mode = "text"
        self.process = None
        self.sent = []
        self.replies = []
        self.cancel_calls = 0

    def start(self, mode):
        self.mode = mode
        self.running = True

    def stop(self):
        self.running = False

    def emit(self, kind, text):
        self.events.put((kind, text))

    def send(self, text):
        self.sent.append(text)

    @property
    def cancel_response_available(self):
        return self.running

    def cancel_response(self):
        self.cancel_calls += 1
        return self.running

    def reply_file_request(self, result, expected_process=None):
        self.replies.append((result, expected_process))

    def prevent_restart(self):
        pass


class QtDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="astra-qt-test-")
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name})
        self.env.start()
        qt.LOCAL = Path(self.temp.name) / "AstraVoiceAssistant"
        self.bridge_patch = patch.object(qt, "DesktopBridge", FakeBridge)
        self.bridge_patch.start()
        self.window = qt.AstraQtDesktop()
        self.wait_until(lambda: not self.window.busy)

    def tearDown(self):
        self.window.poll_timer.stop()
        self.window.exit_application()
        self.app.processEvents()
        self.window.deleteLater()
        self.app.processEvents()
        self.bridge_patch.stop()
        self.env.stop()
        self.temp.cleanup()

    def wait_until(self, predicate):
        for _ in range(100):
            if predicate():
                return
            QTest.qWait(10)
        self.fail("Timed out waiting for the Qt operation")

    def test_core_pages_default_to_voice_and_explicit_microphone(self):
        self.assertEqual(self.window.pages.count(), 5)
        self.assertEqual(self.window.pages.currentIndex(), 0)
        self.assertEqual(self.window.nav_buttons[0].text(), "Голос")
        self.assertEqual(self.window.nav_buttons[1].text(), "Задачи")
        self.assertEqual(self.window.bridge.mode, "text")
        self.window.switch_mode("voice")
        self.wait_until(lambda: self.window.bridge.mode == "voice" and not self.window.busy)
        self.assertTrue(self.window.bridge.running)
        self.assertEqual(self.window.bridge.mode, "voice")
        self.window.switch_mode(None)

    def test_clipboard_shortcuts_and_plain_text_messages(self):
        QApplication.clipboard().setText("проверка вставки")
        self.window.entry.setFocus()
        QTest.keyClick(self.window.entry, Qt.Key_V, Qt.ControlModifier)
        self.assertEqual(self.window.entry.text(), "проверка вставки")
        QTest.keyClick(self.window.entry, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClick(self.window.entry, Qt.Key_C, Qt.ControlModifier)
        self.assertEqual(QApplication.clipboard().text(), "проверка вставки")
        self.window.append_message("Ты", "<b>не HTML</b>")
        self.assertIn("<b>не HTML</b>", self.window.chat.toPlainText())

    def test_stop_response_button_appears_only_while_ai_is_thinking(self):
        button = self.window.cancel_response_button
        self.assertTrue(button.isHidden())
        self.window.bridge.emit("activity", "thinking:start")
        self.window._poll()
        self.assertFalse(button.isHidden())
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(self.window.bridge.cancel_calls, 1)
        self.assertFalse(button.isEnabled())
        self.window.bridge.emit("activity", "thinking:stop")
        self.window._poll()
        self.assertTrue(button.isHidden())
        self.assertTrue(button.isEnabled())

    def test_text_send_auto_starts_text_channel_without_manual_mode(self):
        self.window.entry.setText("Мику, сколько времени")
        self.window.send_text()
        self.assertEqual(self.window.entry.text(), "")
        self.assertIn("Мику, сколько времени", self.window.chat.toPlainText())
        self.assertNotIn("Сначала включи текстовый режим", self.window.chat.toPlainText())
        self.wait_until(lambda: self.window.bridge.sent == ["Мику, сколько времени"] and not self.window.busy)

    def test_settings_validate_and_save_existing_dpapi_profile(self):
        self.window.avatar_choice.setCurrentText("Кай · мужской образ")
        self.window.name_edit.setText("Кайто")
        self.window.scale_choice.setCurrentIndex(2)
        with patch("src.desktop_settings.audio_input_identities_for_index", return_value=("a" * 64, "b" * 64)):
            self.window.save_settings()
        self.wait_until(lambda: not self.window.busy)
        self.assertEqual(self.window.bridge.mode, "text")
        saved = qt.DesktopSettings().load()
        self.assertEqual((saved.avatar_id, saved.assistant_name, saved.ui_scale), ("male_kai", "Кайто", 125))
        self.assertEqual(self.window.character.name, "Кайто")

    def test_avatar_selection_previews_immediately_and_save_stays_visible(self):
        self.assertTrue(self.window.header_save_button.isVisibleTo(self.window))
        self.window.avatar_choice.setCurrentText("Рэн · мужской образ")
        self.assertTrue(self.window.desktop_character.stage.image_path.endswith("full_male.png"))
        self.assertTrue(self.window.character.image_path.endswith("full_male.png"))
        self.assertEqual(self.window.profile.avatar_id, "female_miku")
        self.window.save_settings()
        self.assertEqual(qt.DesktopSettings().load().avatar_id, "male_ren")
        self.assertTrue(self.window.desktop_character.stage.image_path.endswith("full_male.png"))

    def test_ai_connection_details_are_collapsed_by_default(self):
        self.assertFalse(self.window.ai_advanced.isVisibleTo(self.window))
        self.assertIn("Показать подключение", self.window.ai_toggle_button.text())
        self.window._toggle_ai_advanced()
        self.assertTrue(self.window.ai_advanced_visible)
        self.assertFalse(self.window.ai_advanced.isHidden())
        self.assertIn("Скрыть подключение", self.window.ai_toggle_button.text())
        self.window._toggle_ai_advanced()

    def test_audio_and_human_readable_scopes_are_saved(self):
        self.window.microphone_map["Тестовый микрофон"] = 3
        self.window.microphone_choice.addItem("Тестовый микрофон")
        self.window.microphone_choice.setCurrentText("Тестовый микрофон")
        self.window.voice_map["Тестовый голос"] = "synthetic-voice-id"
        self.window.voice_choice.addItem("Тестовый голос")
        self.window.voice_choice.setCurrentText("Тестовый голос")
        self.window.voice_rate.setValue(183)
        self.window.voice_volume.setValue(37)
        for scope, check in self.window.scope_checks.items():
            self.assertNotEqual(check.text(), scope)
            check.setChecked(scope in {"read_files", "ask_files"})
        with patch("src.desktop_settings.audio_input_identities_for_index", return_value=("a" * 64, "b" * 64)):
            self.window.save_settings()
        saved = qt.DesktopSettings().load()
        self.assertEqual(saved.microphone_index, 3)
        self.assertEqual(saved.voice_id, "synthetic-voice-id")
        self.assertEqual((saved.voice_rate, saved.voice_volume), (183, 0.37))
        self.assertEqual(set(saved.allowed_scopes), {"read_files", "ask_files"})

    def test_onboarding_saves_only_at_finish_and_keeps_text_mode(self):
        store = Mock()
        store.load.return_value = AIProfile(provider="disabled")
        dialog = OnboardingDialog(self.window, store)
        dialog.name_edit.setText("Локальная Астра")
        dialog.next_step()
        dialog.next_step()
        store.save.assert_not_called()
        self.assertEqual(self.window.bridge.mode, "text")
        dialog.finish()
        store.save.assert_called_once()
        self.assertEqual(dialog.saved_profile.assistant_name, "Локальная Астра")
        self.assertEqual(self.window.bridge.mode, "text")
        dialog.deleteLater()

    def test_command_catalog_filters_and_only_fills_chat(self):
        dialog = CommandCatalogDialog(self.window, self.window.fill_command)
        dialog.search.setText("сколько времени")
        self.assertEqual(dialog.listing.count(), 1)
        dialog.listing.setCurrentRow(0)
        dialog.insert_selected()
        self.assertEqual(self.window.entry.text(), f"{self.window.assistant_name}, сколько времени")
        self.assertEqual(self.window.bridge.sent, [])
        dialog.deleteLater()

    def test_action_audit_displays_existing_metadata(self):
        audit = Mock()
        audit.recent.return_value = [(1.0, "files.create", "succeeded", "a" * 32)]
        with patch("src.qt_dialogs.default_audit", return_value=audit):
            dialog = ActionAuditDialog(self.window)
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 1).text(), "Создание файла")
        self.assertEqual(dialog.table.item(0, 2).text(), "Выполнено")
        dialog.deleteLater()

    def test_file_operations_require_grant_and_revoke_it_on_close(self):
        root = Path(self.temp.name) / "workspace"
        root.mkdir()
        dialog = FileOperationsDialog(self.window, FileWorkspace(root))
        dialog.destination.setText("created.txt")
        dialog.content.setPlainText("безопасная проверка")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            dialog.perform("create")
            self.assertFalse((root / "created.txt").exists())
            dialog.write_grant.setChecked(True)
            dialog.perform("create")
            self.wait_until(lambda: not dialog.busy)
        self.assertEqual((root / "created.txt").read_text(encoding="utf-8"), "безопасная проверка")
        dialog.close()
        self.assertFalse(dialog.transactions.writable)
        self.assertFalse(dialog.transactions.trash_enabled)
        dialog.deleteLater()

    def test_file_plan_simulates_search_without_reading_or_executing(self):
        root = Path(self.temp.name) / "workspace"
        root.mkdir()
        workspace = FileWorkspace(root)
        workspace.search = Mock(side_effect=AssertionError("Simulation must not read files"))
        dialog = FilePlanDialog(self.window, workspace)
        dialog.argument.setText("отчёт")
        dialog.add_step()
        self.assertEqual(len(dialog.plan_steps), 1)
        dialog.simulate()
        self.assertIn("файлы не читались и не изменялись", dialog.output.toPlainText())
        self.assertTrue(dialog.run_button.isEnabled())
        workspace.search.assert_not_called()
        dialog.close()
        dialog.deleteLater()

    def test_file_question_consent_is_off_and_close_revokes_session(self):
        root = Path(self.temp.name) / "workspace"
        root.mkdir()
        (root / "note.txt").write_text("Локальная заметка", encoding="utf-8")
        dialog = FileQuestionDialog(self.window, FileWorkspace(root), ("note.txt",))
        self.assertFalse(dialog.allowed.isChecked())
        dialog.session.revoke = Mock()
        dialog.reject()
        dialog.session.revoke.assert_called_once()
        dialog.deleteLater()

    def test_preview_uses_explicit_success_flag_not_document_text(self):
        root = Path(self.temp.name) / "workspace"
        root.mkdir()
        self.window.workspace = FileWorkspace(root)
        value = "Не удалось найти слово в этом обычном документе"
        with patch.object(qt, "FilePreviewDialog") as preview:
            self.window._show_file_preview((self.window.file_search_generation, "note.txt", True, value))
        preview.assert_called_once_with(self.window, "note.txt", value)
        self.assertEqual(self.window.files_status.text(), "Локальный preview открыт")

    def test_voice_file_request_without_workspace_is_rejected(self):
        bridge = FakeBridge(None)
        controller = QtVoiceFileController(bridge)
        request = make_search_request("a" * 32, "note")
        controller.handle("search", json.dumps(request))
        self.assertEqual(len(bridge.replies), 1)
        result, expected_process = bridge.replies[0]
        self.assertEqual(result["status"], "no_workspace")
        self.assertIsNone(expected_process)

    def test_profile_import_requires_confirmation(self):
        restored = AIProfile(provider="disabled", assistant_name="Восстановленная")
        original = self.window.profile
        self.window.store.save = Mock()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            self.window._profile_backup_finished(("import", True, restored))
        self.window.store.save.assert_not_called()
        self.assertIs(self.window.profile, original)
        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
            patch.object(self.window, "reset_settings"),
            patch.object(self.window, "_load_character"),
            patch.object(self.window, "switch_mode"),
        ):
            self.window._profile_backup_finished(("import", True, restored))
        self.window.store.save.assert_called_once_with(restored)
        self.assertIs(self.window.profile, restored)

    def test_splash_uses_original_brand_asset_and_boot_sequence(self):
        splash = qt.create_splash()
        self.assertTrue(splash.windowFlags() & Qt.FramelessWindowHint)
        self.assertIn("Astra", splash.stage_text)
        splash.set_stage(2, "Запуск runtime…")
        self.assertEqual(splash.stage_index, 2)
        self.assertEqual(splash.stage_text, "Запуск runtime…")
        splash.timer.stop()
        splash.deleteLater()

    def test_character_stage_maps_states_and_swaps_speaking_frame(self):
        stage = self.window.character
        self.assertEqual(stage.avatar_state, "idle")
        stage.set_state("Слушаю команду…")
        self.assertEqual(stage.avatar_state, "listening")
        stage.set_state("Распознаю речь…")
        self.assertEqual(stage.avatar_state, "recognizing")
        stage.set_state("Говорю ответ")
        self.assertEqual(stage.avatar_state, "speaking")
        self.assertIs(stage._active_pixmap(), stage._speaking_pixmap)
        stage.set_state("Ошибка · микрофон выключен")
        self.assertEqual(stage.avatar_state, "error")
        self.assertIs(stage._active_pixmap(), stage._idle_pixmap)
        self.assertFalse(stage._idle_pixmap.isNull())
        self.assertFalse(stage._speaking_pixmap.isNull())

    def test_avatar_profiles_use_transparent_full_body_assets(self):
        from PIL import Image
        assets = Path(__file__).resolve().parents[1] / "assets" / "avatars"
        for profile in AVATAR_PROFILES.values():
            for key in ("asset", "speaking_asset"):
                with Image.open(assets / profile[key]) as image:
                    self.assertEqual(image.mode, "RGBA")
                    self.assertGreater(image.height / image.width, 1.3)
                    self.assertEqual(image.getchannel("A").getextrema()[0], 0)

    def test_character_full_body_uses_head_and_body_animation_layers(self):
        stage = self.window.character
        self.assertIsNotNone(stage._idle_layers)
        self.assertIsNotNone(stage._speaking_layers)
        self.assertFalse(stage._idle_layers["head"].isNull())
        self.assertFalse(stage._idle_layers["body"].isNull())
        self.assertGreater(stage._idle_layers["head_ratio"], 0.2)
        self.assertGreater(stage._idle_layers["body_offset"], 0.15)
        stage.set_state("Говорю ответ")
        self.assertIs(stage._active_layers(), stage._speaking_layers)

    def test_close_request_enters_background_before_explicit_exit(self):
        self.assertFalse(self.window.closing)
        with patch.object(self.window, "_move_to_background", return_value=True) as move:
            self.window.close()
            move.assert_called_once()
        self.assertFalse(self.window.closing)
        self.window.exit_application()
        self.assertTrue(self.window.force_exit)

    def test_desktop_character_is_transparent_layered_and_synced(self):
        desktop = self.window.desktop_character
        self.assertIsNotNone(desktop)
        self.assertTrue(desktop.stage.desktop_mode)
        self.assertTrue(desktop.stage.transparent_background)
        self.assertIsNone(desktop.stage.name_label)
        self.assertIsNone(desktop.stage.state_label)
        self.assertEqual(desktop.stage.image_path, self.window.character.image_path)
        self.window._set_voice_status("Слушаю команду…")
        self.assertEqual(desktop.stage.avatar_state, "listening")
        self.window.toggle_desktop_character()
        self.assertFalse(desktop.isHidden())
        self.window.toggle_desktop_character()

    def test_character_fullscreen_syncs_and_esc_closes(self):
        self.window.character.set_state("Говорю ответ")
        self.window.show_character_fullscreen()
        self.wait_until(lambda: self.window.character_fullscreen is not None and self.window.character_fullscreen.isVisible())
        dialog = self.window.character_fullscreen
        self.assertEqual(dialog.stage.image_path, self.window.character.image_path)
        self.assertEqual(dialog.stage.speaking_path, self.window.character.speaking_path)
        self.assertEqual(dialog.stage.avatar_state, "speaking")
        QTest.keyClick(dialog, Qt.Key_Escape)
        self.wait_until(lambda: self.window.character_fullscreen is None)

    def test_character_stage_honors_reduced_motion(self):
        stage = self.window.character
        self.assertFalse(stage.reduced_motion)
        self.window.reduced_motion.setChecked(True)
        self.window.save_settings()
        self.assertTrue(self.window.character.reduced_motion)
        self.window.reduced_motion.setChecked(False)
        self.window.save_settings()

    def test_voice_label_adds_language_and_gender(self):
        from types import SimpleNamespace
        voice = SimpleNamespace(name="Microsoft Irina Desktop - Russian", languages=["ru-RU"], gender="Female", id="token")
        self.assertEqual(qt._voice_label(voice), "Microsoft Irina Desktop - Russian — ru-RU, женский")
        plain = SimpleNamespace(name="Custom Voice", languages=[], gender=None, id="token")
        self.assertEqual(qt._voice_label(plain), "Custom Voice")


if __name__ == "__main__":
    unittest.main()
