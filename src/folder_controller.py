from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from src.command_parser import normalize_text


@dataclass(frozen=True)
class FolderActionResult:
    ok: bool
    message: str


class FolderController:
    """Открывает только заранее разрешённые пользовательские папки."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.home = Path.home()
        # src/folder_controller.py -> project root.
        # Не используем Path.cwd(), чтобы автозапуск из другой папки не ломал команду
        # "открой папку проекта".
        self.project_dir = Path(__file__).resolve().parents[1]

    def open_folder(self, user_target: str) -> FolderActionResult:
        path = self._resolve_folder(user_target)
        if path is None:
            return FolderActionResult(False, "Не знаю такую папку.")

        if not path.exists():
            return FolderActionResult(False, f"Папка не найдена: {path}")

        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
            self.logger.info("Открытие папки: %s", path)
            return FolderActionResult(True, "Открываю папку.")
        except OSError as exc:
            self.logger.exception("Не удалось открыть папку: %s", path)
            return FolderActionResult(False, f"Не удалось открыть папку: {exc}")

    def _resolve_folder(self, user_target: str) -> Path | None:
        target = normalize_text(user_target)
        for word in ("папку", "папка", "папке"):
            if target.startswith(word + " "):
                target = target.removeprefix(word).strip()

        aliases: dict[str, Path] = {
            "загрузки": self.home / "Downloads",
            "загрузок": self.home / "Downloads",
            "скачанные": self.home / "Downloads",
            "downloads": self.home / "Downloads",
            "рабочий стол": self.home / "Desktop",
            "desktop": self.home / "Desktop",
            "документы": self.home / "Documents",
            "documents": self.home / "Documents",
            "изображения": self.home / "Pictures",
            "картинки": self.home / "Pictures",
            "pictures": self.home / "Pictures",
            "музыка": self.home / "Music",
            "music": self.home / "Music",
            "видео": self.home / "Videos",
            "videos": self.home / "Videos",
            "проект": self.project_dir,
            "проекта": self.project_dir,
            "проект астра": self.project_dir,
            "астра проект": self.project_dir,
            "папка проекта": self.project_dir,
            "папка астра": self.project_dir,
        }

        return aliases.get(target)
