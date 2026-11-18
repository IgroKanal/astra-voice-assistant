import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.desktop_bridge import DesktopBridge


class SourceRuntimeFallbackTests(unittest.TestCase):
    def test_source_mode_uses_the_current_interpreter(self):
        with tempfile.TemporaryDirectory() as root, \
             patch('src.desktop_bridge.subprocess.Popen') as popen, \
             patch('src.desktop_bridge.threading.Thread'):
            process = Mock()
            popen.return_value = process
            bridge = DesktopBridge(Path(root))
            bridge.start('text')
            self.assertEqual(popen.call_args.args[0], [sys.executable, '-u', str(Path(root).resolve() / 'main.py'), '--text'])

    def test_frozen_app_does_not_use_itself_as_interpreter(self):
        with tempfile.TemporaryDirectory() as root, \
             patch.object(sys, 'frozen', True, create=True), \
             patch('src.desktop_bridge.subprocess.Popen') as popen:
            with self.assertRaises(FileNotFoundError):
                DesktopBridge(Path(root)).start('text')
            popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
