"""Authenticated, passphrase-encrypted reminder migration between Windows PCs."""
from __future__ import annotations

import base64
import binascii
import json
import math
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.backup_crypto import KDF_ITERATIONS, KDF_NAME, derive_backup_key, validate_passphrase


FORMAT = "astra-portable-reminders"
VERSION = 1
MAX_REMINDERS = 1000
MAX_TEXT = 4000
MAX_BACKUP_BYTES = 32 * 1024 * 1024
AAD = b"Astra portable reminder backup\x00v1"


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Резервная копия содержит повторяющиеся поля")
        result[key] = value
    return result


def _validate_reminders(reminders: object) -> list[dict]:
    if not isinstance(reminders, list) or len(reminders) > MAX_REMINDERS:
        raise ValueError("Некорректное число переносимых напоминаний")
    result, seen = [], set()
    for item in reminders:
        if not isinstance(item, dict) or set(item) != {"id", "text", "due", "state"}:
            raise ValueError("Некорректная запись переносимого напоминания")
        identity, text, due, state = item["id"], item["text"], item["due"], item["state"]
        if (not isinstance(identity, str) or len(identity) != 32 or
                any(char not in "0123456789abcdef" for char in identity) or identity in seen or
                not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or
                isinstance(due, bool) or not isinstance(due, (int, float)) or not math.isfinite(due) or due <= 0 or
                not isinstance(state, str) or state not in {"pending", "delivered"}):
            raise ValueError("Некорректные поля переносимого напоминания")
        seen.add(identity)
        result.append({"id": identity, "text": text, "due": float(due), "state": state})
    return result


def encrypt_reminders(reminders: list[dict], passphrase: str) -> bytes:
    validated = _validate_reminders(reminders)
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    plaintext = json.dumps({"reminders": validated}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(derive_backup_key(passphrase, salt)).encrypt(nonce, plaintext, AAD)
    envelope = {
        "format": FORMAT, "version": VERSION, "kdf": KDF_NAME, "iterations": KDF_ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"), "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    payload = json.dumps(envelope, separators=(",", ":")).encode("ascii")
    if len(payload) > MAX_BACKUP_BYTES:
        raise ValueError("Переносимая копия напоминаний превышает 32 МБ")
    return payload


def decrypt_reminders(payload: bytes, passphrase: str) -> list[dict]:
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_BACKUP_BYTES:
        raise ValueError("Размер переносимой копии напоминаний недопустим")
    validate_passphrase(passphrase)
    try:
        envelope = json.loads(payload.decode("ascii"), object_pairs_hook=_no_duplicate_keys)
        expected = {"format", "version", "kdf", "iterations", "salt", "nonce", "ciphertext"}
        if (not isinstance(envelope, dict) or set(envelope) != expected or envelope["format"] != FORMAT or
                type(envelope["version"]) is not int or envelope["version"] != VERSION or
                envelope["kdf"] != KDF_NAME or type(envelope["iterations"]) is not int or envelope["iterations"] != KDF_ITERATIONS):
            raise ValueError("Неизвестный формат переносимых напоминаний")
        salt = base64.b64decode(envelope["salt"], validate=True)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        if len(salt) != 16 or len(nonce) != 12 or not 16 <= len(ciphertext) <= MAX_BACKUP_BYTES:
            raise ValueError("Повреждённые параметры переносимых напоминаний")
        plaintext = AESGCM(derive_backup_key(passphrase, salt)).decrypt(nonce, ciphertext, AAD)
        document = json.loads(plaintext.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
        if not isinstance(document, dict) or set(document) != {"reminders"}:
            raise ValueError("Неизвестная схема переносимых напоминаний")
        return _validate_reminders(document["reminders"])
    except InvalidTag as exc:
        raise ValueError("Пароль неверный или копия напоминаний повреждена") from exc
    except (UnicodeError, json.JSONDecodeError, binascii.Error, TypeError, KeyError) as exc:
        raise ValueError("Не удалось прочитать копию напоминаний") from exc
