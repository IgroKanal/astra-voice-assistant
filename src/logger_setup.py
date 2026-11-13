from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def redact_secrets(text: str) -> str:
    text = re.sub(r"(?is)-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "[REDACTED PRIVATE KEY]", text)
    text = re.sub(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", text)
    text = re.sub(r'''(?i)(["']?\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|authorization)["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s&,;}]+)''', r"\1[REDACTED]", text)
    return re.sub(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,})\b", "[REDACTED KEY]", text)


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        # Redact after interpolation and exception rendering, without mutating the shared record.
        return redact_secrets(super().format(record))


def default_log_directory(
    local_app_data: str | None = None,
    home: Path | None = None,
) -> Path:
    """Return a per-user log folder separate from install/update files."""
    app_data = local_app_data if local_app_data is not None else os.getenv("LOCALAPPDATA", "")
    if app_data.strip():
        return Path(app_data) / "AstraVoiceAssistant" / "logs"
    return (home or Path.home()) / ".astra_voice_assistant" / "logs"


def setup_logging(log_dir: str | Path | None = None) -> logging.Logger:
    """Configure console logging and a rotating per-user ``app.log``."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Защита от повторного добавления handlers при перезапуске в IDE.
    if root_logger.handlers:
        return logging.getLogger("astra")

    formatter = RedactingFormatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    resolved_log_dir = Path(log_dir) if log_dir is not None else default_log_directory()
    resolved_log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        resolved_log_dir / "app.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return logging.getLogger("astra")
