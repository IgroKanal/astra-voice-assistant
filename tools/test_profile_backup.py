from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.desktop_settings import AIProfile
from src.profile_backup import decrypt_profile, encrypt_profile, export_profile, import_profile


class ProfileBackupTests(unittest.TestCase):
    def setUp(self):
        self.profile = AIProfile(
            provider="compatible", model="assistant-model",
            base_url="https://api.example.test/v1", api_key="SAMPLE-SECRET-DO-NOT-LEAK",
            assistant_name="Сая", avatar_id="female_saya",
            character_profiles={"female_saya": {"assistant_name": "Сая", "voice_id": "voice-123"}},
        ).validate()

    def test_encrypted_roundtrip_preserves_full_profile_without_plaintext(self):
        blob = encrypt_profile(self.profile, "correct horse battery staple")
        self.assertNotIn(self.profile.api_key.encode("ascii"), blob)
        self.assertEqual(decrypt_profile(blob, "correct horse battery staple"), self.profile)

    def test_wrong_passphrase_and_tampering_fail_closed(self):
        blob = encrypt_profile(self.profile, "correct horse battery staple")
        with self.assertRaisesRegex(ValueError, "Пароль неверный"):
            decrypt_profile(blob, "different horse battery staple")
        tampered = bytearray(blob)
        tampered[-4] = ord("A") if tampered[-4] != ord("A") else ord("B")
        with self.assertRaises(ValueError):
            decrypt_profile(bytes(tampered), "correct horse battery staple")

    def test_weak_password_unknown_schema_and_oversize_are_rejected(self):
        with self.assertRaises(ValueError):
            encrypt_profile(self.profile, "short")
        with self.assertRaises(ValueError):
            decrypt_profile(b"{}", "correct horse battery staple")
        with self.assertRaises(ValueError):
            decrypt_profile(b"x" * (64 * 1024 + 1), "correct horse battery staple")

    def test_file_roundtrip_and_symlink_import_are_checked(self):
        with tempfile.TemporaryDirectory(prefix="astra-profile-backup-") as temp:
            root = Path(temp)
            backup = root / "profile.astra-profile-backup"
            export_profile(backup, self.profile, "correct horse battery staple")
            self.assertEqual(import_profile(backup, "correct horse battery staple"), self.profile)
            link = root / "link.astra-profile-backup"
            try:
                link.symlink_to(backup)
            except OSError:
                self.skipTest("Symlink creation is unavailable")
            with self.assertRaises(ValueError):
                import_profile(link, "correct horse battery staple")


if __name__ == "__main__":
    unittest.main(verbosity=2)
