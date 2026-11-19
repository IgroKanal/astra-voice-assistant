"""Construct a predictable Windows environment for frozen desktop builds."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Mapping


def isolated_pyinstaller_environment(
    environ: Mapping[str, str] | None = None,
    *,
    executable: Path | None = None,
    python_base: Path | None = None,
) -> dict[str, str]:
    """Keep unrelated PATH entries from supplying native DLLs to PyInstaller.

    The Codex desktop runtime and other developer tools can prepend native
    libraries to PATH. PyInstaller uses PATH while resolving binary imports,
    which can silently bundle a same-named but ABI-incompatible DLL. Retain
    only Windows system and the active Python runtime locations; all other
    environment values remain intact.
    """
    source = os.environ if environ is None else environ
    result = dict(source)
    system_root = Path(result.get("SystemRoot") or result.get("WINDIR") or r"C:\Windows")
    python_executable = Path(sys.executable if executable is None else executable)
    base = Path(sys.base_prefix if python_base is None else python_base)

    candidates = (
        system_root / "System32",
        system_root,
        python_executable.parent,
        base,
        base / "DLLs",
        base / "Scripts",
    )
    path_entries: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(os.fspath(candidate)))
        if normalized not in seen and candidate.is_dir():
            seen.add(normalized)
            path_entries.append(str(candidate))
    result["PATH"] = os.pathsep.join(path_entries)
    return result
