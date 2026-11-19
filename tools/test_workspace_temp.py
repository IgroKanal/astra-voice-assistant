"""Safe temporary roots for workspace tests on Windows and CI."""
from pathlib import Path
import os
import tempfile

from src.file_workspace import FileWorkspace


def workspace_tempdir(prefix: str, project_root: Path) -> tempfile.TemporaryDirectory:
    """Use the configured scratch root or system temp, never the repository."""
    configured = os.environ.get("ASTRA_BUILD_TEMP_ROOT", "").strip()
    base = Path(configured) if configured else Path(tempfile.gettempdir())
    base.mkdir(parents=True, exist_ok=True)
    FileWorkspace._check_components(base)
    resolved = base.resolve()
    project = project_root.resolve()
    if resolved == project or project in resolved.parents:
        raise RuntimeError("Workspace-тесты не должны создавать временные данные в репозитории")
    return tempfile.TemporaryDirectory(prefix=prefix, dir=str(base))
