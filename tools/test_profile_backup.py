from pathlib import Path
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
import base64
import json
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.desktop_settings import AIProfile
from src.backup_crypto import derive_backup_key
from src.profile_backup import (
    AAD,
    FORMAT,
    ITERATIONS,
    KDF,
    VERSION,
    decrypt_profile,
    encrypt_profile,
    export_profile,
    import_profile,
)


class ProfileBackupTests(unittest.TestCase):
    def test_cloud_dialogue_opt_in_survives_encrypted_backup(self):
        profile = AIProfile(provider="compatible", model="model", base_url="https://example.invalid/v1", cloud_dialogue_enabled=True)
        backup = encrypt_profile(profile, "correct horse battery staple")
        self.assertEqual(decrypt_profile(backup, "correct horse battery staple"), profile)

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

    def test_portable_backup_drops_computer_specific_microphone_selection(self):
        profile = AIProfile(
            provider="disabled",
            microphone_index=41,
            microphone_identity="a" * 64,
        )

        restored = decrypt_profile(
            encrypt_profile(profile, "correct horse battery staple"),
            "correct horse battery staple",
        )

        self.assertEqual(
            restored,
            replace(profile, microphone_index=None, microphone_identity=""),
        )

    def test_legacy_portable_backup_discards_stale_microphone_values(self):
        passphrase = "correct horse battery staple"
        profile = AIProfile(
            provider="disabled",
            microphone_index=41,
            microphone_identity="a" * 64,
        )
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(asdict(profile), separators=(",", ":")).encode("utf-8")
        ciphertext = AESGCM(derive_backup_key(passphrase, salt)).encrypt(
            nonce, plaintext, AAD
        )
        legacy_payload = json.dumps(
            {
                "format": FORMAT,
                "version": VERSION,
                "kdf": KDF,
                "iterations": ITERATIONS,
                "salt": base64.b64encode(salt).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            },
            separators=(",", ":"),
        ).encode("ascii")

        restored = decrypt_profile(legacy_payload, passphrase)

        self.assertEqual(
            restored,
            replace(profile, microphone_index=None, microphone_identity=""),
        )

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
