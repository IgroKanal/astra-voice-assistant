"""Own native tray lifecycle and message routing; no other apps are controlled."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import win32con
import win32gui
from src.desktop_tray import DesktopTray, microphone_tooltip


class TrayTests(unittest.TestCase):
    def test_tooltip_shows_only_mapped_voice_activity(self):
        self.assertEqual(microphone_tooltip("text", "Слушаю"), "Astra · микрофон выключен")
        cases = {
            "Слушаю · микрофон включён": "слушает",
            "Распознаю речь…": "распознаёт речь",
            "Думаю · локальная модель": "думает",
            "Говорю…": "говорит",
            "Голосовой режим · микрофон включён": "режим включён",
        }
        for state, expected in cases.items():
            with self.subTest(state=state):
                result = microphone_tooltip("voice", state)
                self.assertIn(expected, result)
        self.assertNotIn("секретный текст", microphone_tooltip("voice", "Слушаю · секретный текст"))

    def test_context_menu_explicitly_toggles_voice_from_current_state(self):
        scenarios = (("Astra · микрофон выключен", "Включить микрофон", "voice"),
                     ("Astra · микрофон включён", "Выключить микрофон", "text"))
        for tooltip, expected_label, expected_mode in scenarios:
            events = []
            tray = DesktopTray(lambda kind, text: events.append((kind, text)))
            tray.tooltip = tooltip
            tray.taskbar_created = 0xC123
            menu = object()
            labels = []
            with patch.object(win32gui, "CreatePopupMenu", return_value=menu), \
                 patch.object(win32gui, "AppendMenu", side_effect=lambda _menu, _flags, _ident, label: labels.append(label)), \
                 patch.object(win32gui, "SetForegroundWindow"), \
                 patch.object(win32gui, "GetCursorPos", return_value=(0, 0)), \
                 patch.object(win32gui, "TrackPopupMenu", return_value=2), \
                 patch.object(win32gui, "PostMessage"), \
                 patch.object(win32gui, "DestroyMenu"):
                tray.on_message(1, tray.CALLBACK, 0, win32con.WM_RBUTTONUP)
            self.assertIn(expected_label, labels)
            self.assertIn(("tray_mode", expected_mode), events)

    def test_native_lifecycle_and_open_event(self):
        events = []
        tray = DesktopTray(lambda kind, text: events.append((kind, text)))
        try:
            tray.start()
            self.assertTrue(win32gui.IsWindow(tray.hwnd))
            tray.set_tooltip("Astra · синтетический тест")
            win32gui.PostMessage(tray.hwnd, tray.CALLBACK, 0, win32con.WM_LBUTTONUP)
            deadline = time.monotonic() + 3
            while not events and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertIn(("tray_show", ""), events)
            self.assertTrue(hasattr(win32gui, "NIIF_INFO"))
        finally:
            tray.stop()
        self.assertFalse(tray.thread.is_alive())
        self.assertIsNone(tray.hwnd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
