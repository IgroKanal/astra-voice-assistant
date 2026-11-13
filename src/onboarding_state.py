"""Persist the user's first-run onboarding dismissal with Windows DPAPI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets

import win32crypt


class OnboardingState:
    """Store a minimal, user-bound first-run choice outside AI settings."""

    def __init__(self, path: Path | None = None):
        self.path = path or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AstraVoiceAssistant" / "onboarding.dpapi"

    def dismissed(self) -> bool:
        path = self.path
        if not path.exists():
            return False
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise ValueError("Недопустимый файл состояния первого запуска")
        raw = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 1)[1]
        data = json.loads(raw.decode("utf-8"))
        if data != {"version": 1, "dismissed": True}:
            raise ValueError("Неподдерживаемое состояние первого запуска")
        return True

    def dismiss(self) -> None:
        encrypted = win32crypt.CryptProtectData(
            json.dumps({"version": 1, "dismissed": True}, separators=(",", ":")).encode("utf-8"),
            "Astra onboarding state", None, None, None, 1,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + "." + secrets.token_hex(8) + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
