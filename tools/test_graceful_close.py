from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.window_controller import WindowController, WindowInfo
from src.windows_app_manager import WindowsAppManager
from src.config_loader import AppConfig


class GracefulCloseTests(unittest.TestCase):
    def controller(self, windows, active=None, still_open=True):
        controller = object.__new__(WindowController)
        self.calls = []
        controller.list_windows = lambda **kwargs: windows
        controller.active_window = lambda: active
        controller._window_info = lambda hwnd: next((w for w in windows if w.hwnd == hwnd), None)
        controller.user32 = SimpleNamespace(PostMessageW=lambda hwnd, message, w, l: self.calls.append((hwnd.value, message)) or 1, IsWindow=lambda hwnd: still_open)
        return controller

    def test_exact_process_only_and_pending_close_is_honest(self):
        named_browser = WindowInfo(11, "notepad in browser", 1, "firefox")
        editor = WindowInfo(22, "document", 2, "notepad")
        result = self.controller([named_browser, editor], still_open=True).request_close_processes(["notepad.exe"], wait_seconds=0)
        self.assertTrue(result.ok)
        self.assertFalse(result.completed)
        self.assertEqual(self.calls, [(22, 0x0010)])

    def test_multiple_windows_need_active_target(self):
        first, second = WindowInfo(11, "same", 1, "notepad"), WindowInfo(22, "same", 2, "notepad")
        controller = self.controller([first, second])
        self.assertFalse(controller.request_close_processes(["notepad.exe"], 0).ok)
        self.assertEqual(self.calls, [])
        controller.active_window = lambda: second
        self.assertTrue(controller.request_close_processes(["notepad.exe"], 0).ok)
        self.assertEqual(self.calls, [(22, 0x0010)])

    def test_reused_handle_is_rejected(self):
        editor = WindowInfo(11, "doc", 1, "notepad")
        controller = self.controller([editor])
        controller._window_info = lambda hwnd: WindowInfo(hwnd, "other", 99, "other")
        self.assertFalse(controller.request_close_processes(["notepad.exe"], 0).ok)
        self.assertEqual(self.calls, [])

    def test_manager_never_force_kills(self):
        app = AppConfig("editor", ["editor"], ["notepad.exe"], "notepad.exe")
        manager = WindowsAppManager({"editor": app})
        result = SimpleNamespace(ok=True, message="request sent", completed=False)
        with patch("src.window_controller.WindowController") as windows, patch("src.windows_app_manager.subprocess.run", side_effect=AssertionError("No taskkill")):
            windows.return_value.request_close_processes.return_value = result
            close = manager.close_app("editor")
            self.assertTrue(close.ok)
            self.assertFalse(close.completed)
            windows.return_value.request_close_processes.assert_called_once_with(["notepad.exe"])

    def test_terminal_and_system_process_cannot_be_closed(self):
        manager = WindowsAppManager({})
        with patch("src.window_controller.WindowController", side_effect=AssertionError("Forbidden close")):
            self.assertFalse(manager._close_allowed_processes(["cmd.exe", "lsass.exe"]).ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
