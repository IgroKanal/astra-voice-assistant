"""Regression tests for backward-compatible visual profile preferences."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.desktop_settings import AIProfile, DesktopSettings


class VisualPreferenceTests(unittest.TestCase):
    def test_defaults_preserve_existing_profile_behavior(self):
        profile = AIProfile().validate()
        self.assertEqual((profile.avatar_mode, profile.ui_scale, profile.reduced_motion), ("2d", 100, False))

    def test_visual_preferences_roundtrip_dpapi(self):
        with tempfile.TemporaryDirectory(prefix="astra-visual-profile-") as temp:
            with patch.dict(os.environ, {"LOCALAPPDATA": temp}):
                store = DesktopSettings()
                expected = AIProfile(provider="disabled", avatar_mode="3d", ui_scale=125, reduced_motion=True)
                store.save(expected)
                actual = store.load()
                self.assertEqual((actual.avatar_mode, actual.ui_scale, actual.reduced_motion), ("3d", 125, True))

    def test_invalid_visual_preferences_are_rejected(self):
        for changes in ({"avatar_mode": "web"}, {"ui_scale": 115}, {"reduced_motion": "yes"}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    AIProfile(**changes).validate()


if __name__ == "__main__":
    unittest.main()
