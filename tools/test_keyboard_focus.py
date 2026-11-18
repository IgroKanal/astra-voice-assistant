import unittest
from unittest.mock import Mock, patch

from src.keyboard_controller import KeyboardController


class KeyboardFocusFallbackTests(unittest.TestCase):
    def make_controller(self, native_focus=True):
        controller = KeyboardController.__new__(KeyboardController)
        controller.logger = Mock()
        controller._find_process_window = Mock(return_value=(123, 456))
        controller._force_foreground_window = Mock(return_value=native_focus)
        return controller

    def test_native_focus_path_does_not_launch_powershell(self):
        controller = self.make_controller(native_focus=True)
        with patch("src.keyboard_controller.subprocess.run", side_effect=AssertionError), \
             patch.object(controller, "_activate_process_by_pid") as fallback:
            result = controller.focus_process("notepad", attempts=1)

        self.assertTrue(result)
        fallback.assert_not_called()

    def test_missing_optional_powershell_fallback_returns_failure_without_raising(self):
        controller = self.make_controller(native_focus=False)
        with patch("src.keyboard_controller.time.sleep"), patch(
            "src.keyboard_controller.subprocess.run",
            side_effect=FileNotFoundError("powershell.exe is unavailable"),
        ) as run:
            result = controller.focus_process("notepad", attempts=1)

        self.assertFalse(result)
        self.assertEqual(run.call_args.args[0][0], "powershell.exe")
        self.assertIn("[int]123", run.call_args.args[0][-1])

    def test_non_numeric_or_out_of_range_pid_never_reaches_shell(self):
        controller = self.make_controller(native_focus=False)
        with patch("src.keyboard_controller.subprocess.run") as run:
            for pid in (0, -1, 0x1_0000_0000, True, "123; throw 'bad'"):
                with self.subTest(pid=pid):
                    self.assertFalse(controller._activate_process_by_pid(pid))

        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
