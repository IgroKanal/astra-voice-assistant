from pathlib import Path
import tempfile
import unittest
import logging
import sys

from src.logger_setup import default_log_directory, RedactingFormatter


class DefaultLogDirectoryTests(unittest.TestCase):
    def test_secrets_are_removed_after_interpolation_and_traceback_rendering(self):
        formatter = RedactingFormatter("%(message)s")
        record = logging.LogRecord("test", logging.ERROR, "", 1, "api_key=%s Authorization: Bearer abc.def.ghi", ("private-key-value",), None)
        rendered = formatter.format(record)
        self.assertNotIn("private-key-value", rendered)
        self.assertNotIn("abc.def.ghi", rendered)
        try:
            raise ValueError('password="exception secret"')
        except ValueError:
            record = logging.LogRecord("test", logging.ERROR, "", 1, "Request failed", (), sys.exc_info())
            self.assertNotIn("exception secret", formatter.format(record))

    def test_windows_user_data_is_outside_install_directory(self):
        result = default_log_directory(r"C:\Users\User\AppData\Local", Path(r"C:\Program Files\Astra"))
        self.assertEqual(
            result,
            Path(r"C:\Users\User\AppData\Local\AstraVoiceAssistant\logs"),
        )
        self.assertNotIn("Program Files", str(result))

    def test_home_fallback_is_used_when_local_app_data_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            result = default_log_directory("", Path(temp))
            self.assertEqual(result, Path(temp) / ".astra_voice_assistant" / "logs")
