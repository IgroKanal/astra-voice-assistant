"""Compile a per-user Astra installer from a verified portable preview."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def locate_iscc() -> Path:
    candidates = []
    configured = os.environ.get("ASTRA_ISCC", "").strip()
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        Path(value)
        for value in (
            r"C:\Projects\tools\InnoSetup-7.1.1\ISCC.exe",
            r"C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
            r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "Inno Setup Compiler not found. Set ASTRA_ISCC to its signed ISCC.exe path."
    )


def compile_installer(source_dir: Path, output_dir: Path, iscc: Path | None = None) -> Path:
    source = source_dir.resolve(strict=True)
    manifest_path = source / "build_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(manifest.get("version", ""))
    version_parts = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)-(?:dev|beta)\.(\d+)", version)
    if version_parts is None:
        raise ValueError("Preview manifest has an unsupported Astra version")
    if manifest.get("contains_personal_env") is not False:
        raise ValueError("Preview manifest does not explicitly exclude a personal .env")
    from src.version import PRODUCT_VERSION

    if version != PRODUCT_VERSION:
        raise ValueError(f"Preview is {version}, source is {PRODUCT_VERSION}")
    if not (source / "Astra.exe").is_file() or not (
        source / "runtime" / "AstraRuntime" / "AstraRuntime.exe"
    ).is_file():
        raise FileNotFoundError("The source directory is not a complete portable preview")
    if (source / ".env").exists():
        raise ValueError("Refusing to package a personal .env file")

    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    compiler = iscc or locate_iscc()
    script = ROOT / "installer" / "Astra.iss"
    args = [
        str(compiler),
        f"/DPreviewDir={source.as_posix()}",
        f"/DAstraVersion={version}",
        f"/DAstraBinaryVersion={'.'.join(version_parts.groups())}",
        f"/O{output}",
        str(script),
    ]
    subprocess.run(args, check=True, cwd=ROOT)
    installer = output / f"Astra-Setup-{version}.exe"
    if not installer.is_file() or installer.stat().st_size < 1024 * 1024:
        raise RuntimeError("ISCC returned successfully but the installer is missing or incomplete")
    print(f"ASTRA_INSTALLER={installer}")
    return installer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    compile_installer(args.source_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
