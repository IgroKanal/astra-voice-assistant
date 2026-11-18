"""Safe temporary roots for workspace tests on Windows and CI."""
from pathlib import Path
import os
import tempfile

from src.file_workspace import FileWorkspace, WorkspaceDenied


def workspace_tempdir(prefix: str, project_root: Path) -> tempfile.TemporaryDirectory:
    """Prefer the user's D: scratch drive; fall back to a safe project root in CI."""
    candidates = []
    if os.name == "nt" and Path("D:/").exists():
        candidates.append(Path("D:/Astra-Work"))
    candidates.append(Path(project_root))
    for base in candidates:
        try:
            base.mkdir(parents=True, exist_ok=True)
            FileWorkspace._check_components(base)
            return tempfile.TemporaryDirectory(prefix=prefix, dir=str(base))
        except (OSError, WorkspaceDenied):
            continue
    raise RuntimeError("Не удалось выбрать безопасную временную папку для workspace-теста")
