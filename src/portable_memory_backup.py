"""Authenticated, passphrase-encrypted memory backup for cross-PC migration."""
from __future__ import annotations

import base64
import binascii
import json
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.backup_crypto import KDF_ITERATIONS, KDF_NAME, derive_backup_key, validate_passphrase


FORMAT = "astra-portable-memory"
VERSION = 1
MAX_NOTES = 1000
MAX_NOTE_TITLE = 200
MAX_NOTE_TEXT = 16000
MAX_BACKUP_BYTES = 32 * 1024 * 1024
AAD = b"Astra portable memory backup\x00v1"


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Резервная копия содержит повторяющиеся поля")
        result[key] = value
    return result


def _validate_notes(notes: object) -> list[dict[str, str]]:
    if not isinstance(notes, list) or len(notes) > MAX_NOTES:
        raise ValueError("Некорректное число записей переносимой памяти")
    result = []
    seen = set()
    for item in notes:
        if not isinstance(item, dict) or set(item) != {"id", "title", "text"}:
            raise ValueError("Некорректная запись переносимой памяти")
        identity, title, content = item["id"], item["title"], item["text"]
        if (not isinstance(identity, str) or len(identity) != 32 or
                any(char not in "0123456789abcdef" for char in identity) or identity in seen or
                not isinstance(title, str) or not title.strip() or len(title) > MAX_NOTE_TITLE or
                not isinstance(content, str) or not content.strip() or len(content) > MAX_NOTE_TEXT):
            raise ValueError("Некорректные поля записи переносимой памяти")
        seen.add(identity)
        result.append({"id": identity, "title": title, "text": content})
    return result


def encrypt_memory(notes: list[dict[str, str]], passphrase: str) -> bytes:
    validated = _validate_notes(notes)
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    plaintext = json.dumps({"notes": validated}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(derive_backup_key(passphrase, salt)).encrypt(nonce, plaintext, AAD)
    envelope = {
        "format": FORMAT, "version": VERSION, "kdf": KDF_NAME,
        "iterations": KDF_ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    encoded = json.dumps(envelope, separators=(",", ":")).encode("ascii")
    if len(encoded) > MAX_BACKUP_BYTES:
        raise ValueError("Переносимая резервная копия превышает 32 МБ")
    return encoded


def decrypt_memory(payload: bytes, passphrase: str) -> list[dict[str, str]]:
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_BACKUP_BYTES:
        raise ValueError("Размер переносимой резервной копии недопустим")
    # Validate before parsing, but derive the expensive key only once below.
    validate_passphrase(passphrase)
    try:
        envelope = json.loads(payload.decode("ascii"), object_pairs_hook=_no_duplicate_keys)
        if (not isinstance(envelope, dict) or
                set(envelope) != {"format", "version", "kdf", "iterations", "salt", "nonce", "ciphertext"} or
                envelope["format"] != FORMAT or type(envelope["version"]) is not int or envelope["version"] != VERSION or
                envelope["kdf"] != KDF_NAME or type(envelope["iterations"]) is not int or envelope["iterations"] != KDF_ITERATIONS):
            raise ValueError("Неизвестный формат переносимой памяти")
        salt = base64.b64decode(envelope["salt"], validate=True)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        if len(salt) != 16 or len(nonce) != 12 or not 16 <= len(ciphertext) <= MAX_BACKUP_BYTES:
            raise ValueError("Повреждённые параметры переносимой памяти")
        plaintext = AESGCM(derive_backup_key(passphrase, salt)).decrypt(nonce, ciphertext, AAD)
        document = json.loads(plaintext.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
        if not isinstance(document, dict) or set(document) != {"notes"}:
            raise ValueError("Неизвестная схема переносимой памяти")
        return _validate_notes(document["notes"])
    except InvalidTag as exc:
        raise ValueError("Пароль неверный или переносимая копия повреждена") from exc
    except (UnicodeError, json.JSONDecodeError, binascii.Error, TypeError, KeyError) as exc:
        raise ValueError("Не удалось прочитать переносимую копию памяти") from exc
