from pathlib import Path
import logging
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.media_controller import MediaController
from src.keyboard_controller import KeyboardController


class MediaPolicyTests(unittest.TestCase):
    def test_unknown_target_does_not_become_global_media(self):
        class Keyboard:
            def send_media_shortcut(self, *args, **kwargs):
                raise AssertionError("Unknown target must not execute")
        controller = MediaController(Keyboard(), SimpleNamespace(), logging.getLogger("test"))
        self.assertFalse(controller.execute("next:unknown").ok)

    def test_keyboard_unknown_target_fails_before_window_lookup(self):
        keyboard = object.__new__(KeyboardController)
        self.assertFalse(keyboard.send_media_shortcut("media_next", target="unknown").ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
