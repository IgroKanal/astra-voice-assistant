"""Passphrase-protected, portable Astra profile backup format."""
from __future__ import annotations

import base64
import binascii
from dataclasses import asdict
import json
import os
from pathlib import Path
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.backup_crypto import KDF_ITERATIONS, KDF_NAME, derive_backup_key, validate_passphrase
from src.desktop_settings import AIProfile


FORMAT = "astra-profile-backup"
VERSION = 1
KDF = KDF_NAME
ITERATIONS = KDF_ITERATIONS
MAX_BACKUP_BYTES = 64 * 1024
AAD = b"Astra profile backup\x00v1"


def _password_bytes(passphrase: str) -> bytes:
    return validate_passphrase(passphrase)


def _derive(passphrase: str, salt: bytes) -> bytes:
    return derive_backup_key(passphrase, salt)


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Резервная копия содержит повторяющиеся поля")
        result[key] = value
    return result


def encrypt_profile(profile: AIProfile, passphrase: str) -> bytes:
    profile.validate()
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    plaintext = json.dumps(asdict(profile), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(_derive(passphrase, salt)).encrypt(nonce, plaintext, AAD)
    envelope = {
        "format": FORMAT,
        "version": VERSION,
        "kdf": KDF,
        "iterations": ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    encoded = json.dumps(envelope, separators=(",", ":")).encode("ascii")
    if len(encoded) > MAX_BACKUP_BYTES:
        raise ValueError("Профиль слишком велик для резервной копии")
    return encoded


def decrypt_profile(payload: bytes, passphrase: str) -> AIProfile:
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_BACKUP_BYTES:
        raise ValueError("Размер резервной копии недопустим")
    _password_bytes(passphrase)
    try:
        envelope = json.loads(payload.decode("ascii"), object_pairs_hook=_no_duplicate_keys)
        if (not isinstance(envelope, dict) or
                set(envelope) != {"format", "version", "kdf", "iterations", "salt", "nonce", "ciphertext"} or
                envelope["format"] != FORMAT or type(envelope["version"]) is not int or envelope["version"] != VERSION or
                envelope["kdf"] != KDF or type(envelope["iterations"]) is not int or envelope["iterations"] != ITERATIONS):
            raise ValueError("Неизвестный формат или версия резервной копии")
        salt = base64.b64decode(envelope["salt"], validate=True)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        if len(salt) != 16 or len(nonce) != 12 or not 16 <= len(ciphertext) <= MAX_BACKUP_BYTES:
            raise ValueError("Повреждённые криптографические параметры резервной копии")
        plaintext = AESGCM(_derive(passphrase, salt)).decrypt(nonce, ciphertext, AAD)
        profile_data = json.loads(plaintext.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
        if not isinstance(profile_data, dict):
            raise ValueError("Некорректный профиль в резервной копии")
        if isinstance(profile_data.get("allowed_scopes"), list):
            profile_data["allowed_scopes"] = tuple(profile_data["allowed_scopes"])
        return AIProfile(**profile_data).validate()
    except InvalidTag as exc:
        raise ValueError("Пароль неверный или резервная копия повреждена") from exc
    except (UnicodeError, json.JSONDecodeError, binascii.Error, TypeError, KeyError) as exc:
        raise ValueError("Не удалось прочитать резервную копию профиля") from exc


def export_profile(path: Path, profile: AIProfile, passphrase: str) -> None:
    target = Path(path)
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise ValueError("Резервная копия должна быть обычным файлом")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        payload = encrypt_profile(profile, passphrase)
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def import_profile(path: Path, passphrase: str) -> AIProfile:
    target = Path(path)
    if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_BACKUP_BYTES:
        raise ValueError("Недопустимый файл резервной копии")
    return decrypt_profile(target.read_bytes(), passphrase)
