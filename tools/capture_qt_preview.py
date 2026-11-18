"""Capture deterministic Qt previews with no microphone, network or user data."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import queue
import sys
import tempfile
from unittest.mock import patch

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "visual_previews_qt"
import astra_desktop_qt as qt


class PreviewBridge:
    def __init__(self, _root):
        self.events = queue.Queue()
        self.running = False
        self.mode = "text"
        self.process = None
    def start(self, mode):
        self.mode = mode
        self.running = True
    def stop(self):
        self.running = False
    def emit(self, kind, text):
        self.events.put((kind, text))
    def send(self, _text):
        pass
    def reply_file_request(self, _result, expected_process=None):
        pass
    def prevent_restart(self):
        pass


def main():
    OUTPUT.mkdir(exist_ok=True)
    app = QApplication([])
    for filename in ("segoeui.ttf", "segoeuib.ttf"):
        candidates = [ROOT.parent.parent / "_fonts" / filename]
        if os.environ.get("WINDIR"):
            candidates.append(Path(os.environ["WINDIR"]) / "Fonts" / filename)
        font_path = next((path for path in candidates if path.is_file()), None)
        if font_path is None or QFontDatabase.addApplicationFont(str(font_path)) < 0:
            raise RuntimeError(f"Cannot load preview font: {filename}")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    with tempfile.TemporaryDirectory(prefix="astra-qt-preview-", dir=ROOT) as temp, patch.dict(os.environ, {"LOCALAPPDATA": temp}), patch.object(qt, "DesktopBridge", PreviewBridge):
        qt.LOCAL = Path(temp) / "AstraVoiceAssistant"
        window = qt.AstraQtDesktop()
        window.resize(1440, 900)
        window.show()
        import time
        intro_deadline = time.monotonic() + 0.5
        while getattr(window, "_intro_effect", None) is not None and time.monotonic() < intro_deadline:
            app.processEvents()
            time.sleep(0.01)
        deadline = time.monotonic() + 2
        while window.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        window.grab().save(str(OUTPUT / "home.png"))
        window.desktop_character.show()
        app.processEvents()
        window.desktop_character.grab().save(str(OUTPUT / "desktop-character.png"))
        window.desktop_character.hide()
        window._set_voice_status("Говорю ответ…")
        app.processEvents()
        window.character.grab().save(str(OUTPUT / "character-speaking.png"))
        window._set_voice_status("Микрофон выключен. Нажми кнопку, когда будешь готов говорить.")
        app.processEvents()
        window.show_page(1)
        app.processEvents()
        window.grab().save(str(OUTPUT / "tasks.png"))
        window.show_page(0)
        window.append_message("Ты", "Найди мои ближайшие задачи")
        window.append_message(window.assistant_name, "Можно посмотреть задачи в отдельном разделе. Микрофон при этом останется выключен.")
        app.processEvents()
        window.grab().save(str(OUTPUT / "dialogue.png"))
        window.show_page(4)
        app.processEvents()
        window.pages.currentWidget().grab().save(str(OUTPUT / "settings.png"))
        splash = qt.create_splash()
        splash.showFullScreen()
        app.processEvents()
        splash.grab().save(str(OUTPUT / "launch-animation.png"))
        splash.close()

        workspace = Path(temp) / "workspace"
        workspace.mkdir()
        (workspace / "План проекта.txt").write_text("Проверить Qt-оболочку\nОставить микрофон выключенным", encoding="utf-8")
        (workspace / "Заметки.md").write_text("# Локальные заметки\nФайл используется только для предпросмотра.", encoding="utf-8")
        with patch.object(qt.QFileDialog, "getExistingDirectory", return_value=str(workspace)):
            window.choose_workspace()
        deadline = time.monotonic() + 3
        while window.files_list.count() and window.files_list.item(0).text() == "Поиск…" and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        if window.files_list.count() != 2:
            raise RuntimeError("Synthetic file preview did not finish")
        window.show_page(2)
        app.processEvents()
        window.grab().save(str(OUTPUT / "files.png"))

        def capture_dialog(dialog, filename):
            dialog.show()
            app.processEvents()
            dialog.grab().save(str(OUTPUT / filename))
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

        capture_dialog(qt.FileOperationsDialog(window, window.workspace, window.transactions), "file-operations.png")
        capture_dialog(qt.OnboardingDialog(window), "onboarding.png")
        capture_dialog(qt.CommandCatalogDialog(window, window.fill_command), "command-catalog.png")
        window.poll_timer.stop()
        window.close()


if __name__ == "__main__":
    main()
