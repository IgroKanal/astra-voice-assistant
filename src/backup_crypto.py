"""Shared password derivation rules for portable Astra backups."""
from __future__ import annotations

import hashlib


MIN_PASSPHRASE_LENGTH = 12
MAX_PASSPHRASE_LENGTH = 1024
KDF_NAME = "PBKDF2-HMAC-SHA256"
KDF_ITERATIONS = 600_000


def validate_passphrase(passphrase: str) -> bytes:
    if not isinstance(passphrase, str) or not MIN_PASSPHRASE_LENGTH <= len(passphrase) <= MAX_PASSPHRASE_LENGTH:
        raise ValueError("Парольная фраза должна содержать от 12 до 1024 символов")
    return passphrase.encode("utf-8")


def derive_backup_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", validate_passphrase(passphrase), salt, KDF_ITERATIONS, dklen=32)
