from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.validate_desktop_package import validate_voice_core_modules


class VoiceCorePackageTests(unittest.TestCase):
    def test_each_runtime_module_is_required(self):
        required = {
            "src.microphone_recovery",
            "src.assistant_persona",
            "src.runtime_events",
            "src.audio_device_discovery",
        }
        validate_voice_core_modules(required)
        for missing in required:
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                validate_voice_core_modules(required - {missing})


if __name__ == "__main__":
    unittest.main()
