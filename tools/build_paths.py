"""Build paths that keep local Astra packaging work off the Windows drive."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
from typing import Iterator, Mapping


@dataclass(frozen=True)
class BuildPaths:
    output_root: Path
    temp_root: Path


def resolve_build_paths(
    project_root: Path,
    environ: Mapping[str, str] | None = None,
    *,
    is_windows: bool | None = None,
    d_drive_available: bool | None = None,
) -> BuildPaths:
    """Use D:\\AstraBuild locally; keep CI artifacts beside its checkout."""
    env = os.environ if environ is None else environ
    on_windows = os.name == "nt" if is_windows is None else is_windows
    d_available = (
        (on_windows and Path("D:/").is_dir())
        if d_drive_available is None
        else d_drive_available
    )
    root = Path(project_root).resolve()
    github_actions = env.get("GITHUB_ACTIONS", "").casefold() == "true"

    configured_output = env.get("ASTRA_BUILD_OUTPUT_ROOT", "").strip()
    if configured_output:
        output = Path(configured_output).expanduser().resolve()
    elif on_windows and not github_actions:
        if not d_available:
            raise RuntimeError(
                "D: is unavailable; set ASTRA_BUILD_OUTPUT_ROOT explicitly to keep builds off C:"
            )
        output = Path("D:/AstraBuild").resolve()
    else:
        output = root.parent

    configured_temp = env.get("ASTRA_BUILD_TEMP_ROOT", "").strip()
    temp = (
        Path(configured_temp).expanduser().resolve()
        if configured_temp
        else output / "_tmp"
    )
    return BuildPaths(output_root=output, temp_root=temp)


def configure_temp_directory(path: Path) -> Path:
    """Route Python and child-process temporary files to a chosen directory."""
    target = Path(path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    for name in ("TEMP", "TMP", "TMPDIR"):
        os.environ[name] = str(target)
    tempfile.tempdir = str(target)
    return target


@contextmanager
def using_temp_directory(path: Path) -> Iterator[Path]:
    """Temporarily route Python and child-process temporary files to ``path``."""
    names = ("TEMP", "TMP", "TMPDIR")
    previous_env = {name: os.environ.get(name) for name in names}
    previous_tempdir = tempfile.tempdir
    target = configure_temp_directory(path)
    try:
        yield target
    finally:
        for name, value in previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        tempfile.tempdir = previous_tempdir


def cleanup_build_work(path: Path, *, temp_root: Path) -> None:
    """Remove only this builder's unique workspace immediately under temp_root."""
    root = Path(temp_root).expanduser().resolve()
    target = Path(path).expanduser().resolve()
    if target.parent != root or not target.name.startswith("astra-desktop-build-"):
        raise ValueError("Refusing to remove a path outside the Astra build workspace")
    shutil.rmtree(target)
