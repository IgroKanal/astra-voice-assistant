"""Build an isolated portable preview; never copy the user's .env or logs."""
from __future__ import annotations

import atexit
from datetime import datetime
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_desktop_environment import isolated_pyinstaller_environment
from tools.build_paths import cleanup_build_work, configure_temp_directory, resolve_build_paths


def build() -> Path:
    inputs = [ROOT / name for name in ("main.py", "astra_desktop_qt.py", "astra_runtime.py", "requirements.txt", "requirements-desktop.txt", "requirements-build.txt", "docs/DESKTOP_PREVIEW.md", "THIRD_PARTY_NOTICES.md", "licenses/QT_LGPL_LICENSE.txt", "licenses/QT_GPL_LICENSE.txt", ".env.example", "src/version.py", "tools/build_paths.py", "tools/build_desktop_environment.py", "tools/edge_tts_entry.py", "tools/edge_playback_entry.py")]
    inputs += list((ROOT / "src").glob("*.py")) + list((ROOT / "config").glob("*.json")) + list((ROOT / "assets" / "avatars").glob("*.png"))
    icon = ROOT / "assets" / "branding" / "astra.ico"
    inputs += list((ROOT / "assets" / "branding").glob("*"))
    pyside_version = importlib.metadata.version("PySide6-Essentials")
    pyside_parts = tuple(int(value) for value in pyside_version.split(".")[:2])
    if not (6, 9) <= pyside_parts < (7, 0):
        raise RuntimeError("The Qt desktop requires PySide6-Essentials 6.9 or newer within Qt 6")
    edge_tts_version = importlib.metadata.version("edge-tts")
    version_parts = tuple(int(value) for value in edge_tts_version.split(".")[:3])
    if version_parts < (7, 3, 1):
        raise RuntimeError("Portable Edge TTS requires edge-tts 7.3.1 or newer")
    license_entries = [
        entry
        for entry in (importlib.metadata.distribution("edge-tts").files or [])
        if str(entry).replace("\\", "/").lower().endswith(".dist-info/licenses/license")
    ]
    if not license_entries:
        raise RuntimeError("The edge-tts license file is missing from the build environment")
    edge_tts_license = Path(importlib.metadata.distribution("edge-tts").locate_file(license_entries[0]))
    edge_tts_package = Path(importlib.util.find_spec("edge_tts").origin).parent
    edge_playback_package = Path(importlib.util.find_spec("edge_playback").origin).parent
    def input_key(path: Path) -> str:
        try:
            return str(path.relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            return "external/" + path.name
    fingerprint = {input_key(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    paths = resolve_build_paths(ROOT)
    paths.output_root.mkdir(parents=True, exist_ok=True)
    paths.temp_root.mkdir(parents=True, exist_ok=True)
    output = paths.output_root / ("AstraDesktop-preview-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    archive_path = output.with_suffix(".zip")
    work = Path(tempfile.mkdtemp(prefix="astra-desktop-build-", dir=paths.temp_root))
    cleanup_state = {"output_created": False, "archive_created": False, "complete": False}

    def clean_work() -> None:
        try:
            cleanup_build_work(work, temp_root=paths.temp_root)
        except OSError as exc:
            print(f"BUILD_TEMP_RETAINED={work} ({exc})", flush=True)
        if cleanup_state["complete"]:
            return
        try:
            if cleanup_state["archive_created"]:
                archive_path.unlink(missing_ok=True)
            if cleanup_state["output_created"]:
                shutil.rmtree(output)
        except OSError as exc:
            print(f"INCOMPLETE_BUILD_RETAINED={output} ({exc})", flush=True)

    atexit.register(clean_work)
    output.mkdir(exist_ok=False)
    cleanup_state["output_created"] = True
    configure_temp_directory(work)
    pyinstaller_config = work / "pyinstaller-config"
    pyinstaller_config.mkdir()
    pyinstaller_env = isolated_pyinstaller_environment()
    pyinstaller_env["PYINSTALLER_CONFIG_DIR"] = str(pyinstaller_config)
    common = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--noupx", "--clean", "--specpath", str(work), "--icon", str(icon)]
    ui_stage = work / "ui-dist"
    subprocess.run(common + ["--name", "Astra", "--onedir", "--contents-directory", "_internal", "--windowed", "--distpath", str(ui_stage), "--workpath", str(work / "ui"), "--add-data", str(ROOT / "assets" / "avatars") + ":assets/avatars", str(ROOT / "astra_desktop_qt.py")], cwd=ROOT, env=pyinstaller_env, check=True)
    ui_payload = ui_stage / "Astra"
    if not (ui_payload / "Astra.exe").is_file():
        raise RuntimeError("PyInstaller did not produce the onedir desktop application")
    for path in ui_payload.iterdir():
        shutil.move(str(path), str(output / path.name))
    subprocess.run(common + ["--name", "AstraRuntime", "--onedir", "--console", "--distpath", str(output / "runtime"), "--workpath", str(work / "runtime"), "--collect-submodules", "pyttsx3.drivers", "--add-data", str(ROOT / "config") + ":config", str(ROOT / "astra_runtime.py")], cwd=ROOT, env=pyinstaller_env, check=True)
    runtime_dir = output / "runtime" / "AstraRuntime"
    subprocess.run(common + ["--name", "edge-tts", "--onefile", "--console", "--distpath", str(runtime_dir), "--workpath", str(work / "edge-tts"), "--collect-all", "edge_tts", str(ROOT / "tools" / "edge_tts_entry.py")], cwd=ROOT, env=pyinstaller_env, check=True)
    subprocess.run(common + ["--name", "edge-playback", "--onefile", "--console", "--distpath", str(runtime_dir), "--workpath", str(work / "edge-playback"), "--collect-all", "edge_playback", "--collect-all", "edge_tts", str(ROOT / "tools" / "edge_playback_entry.py")], cwd=ROOT, env=pyinstaller_env, check=True)

    edge_env = {**pyinstaller_env, "PATH": str(runtime_dir) + os.pathsep + pyinstaller_env.get("PATH", "")}
    edge_version = subprocess.run([str(runtime_dir / "edge-tts.exe"), "--version"], env=edge_env, capture_output=True, text=True, timeout=20)
    playback_help = subprocess.run([str(runtime_dir / "edge-playback.exe"), "--help"], env=edge_env, capture_output=True, text=True, timeout=20)
    if edge_version.returncode != 0 or not edge_version.stdout.strip().startswith("edge-tts 7.3."):
        raise RuntimeError("Bundled edge-tts executable failed its local version check")
    if playback_help.returncode != 0 or "Speak text" not in (playback_help.stdout + playback_help.stderr):
        raise RuntimeError("Bundled edge-playback executable failed its local help check")

    third_party_licenses = output / "third_party_licenses"
    third_party_sources = output / "third_party_sources" / ("edge-tts-" + edge_tts_version)
    third_party_licenses.mkdir(parents=True, exist_ok=True)
    third_party_sources.mkdir(parents=True, exist_ok=True)
    shutil.copy2(edge_tts_license, third_party_licenses / "edge-tts-LICENSE.txt")
    shutil.copy2(ROOT / "licenses/QT_LGPL_LICENSE.txt", third_party_licenses / "Qt-LGPL-3.0-only.txt")
    shutil.copy2(ROOT / "licenses/QT_GPL_LICENSE.txt", third_party_licenses / "Qt-GPL-3.0-only.txt")
    shutil.copytree(edge_tts_package, third_party_sources / "edge_tts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(edge_playback_package, third_party_sources / "edge_playback", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "config", output / "config")
    shutil.copytree(ROOT / "assets", output / "assets")
    shutil.copy2(ROOT / ".env.example", output / ".env.example")
    shutil.copy2(ROOT / "docs/DESKTOP_PREVIEW.md", output / "README.md")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", output / "THIRD_PARTY_NOTICES.md")
    for path in inputs:
        if hashlib.sha256(path.read_bytes()).hexdigest() != fingerprint[input_key(path)]:
            raise RuntimeError("Source changed during build; discard this preview and rebuild")
    from src.version import PRODUCT_VERSION
    manifest = {"product": "Astra Desktop", "version": PRODUCT_VERSION, "built_at": datetime.now().isoformat(), "python": sys.version.split()[0], "bundled_dependencies": {"edge-tts": edge_tts_version, "PySide6-Essentials": pyside_version}, "bundled_components": {"3d_avatar_preview": False}, "source_sha256": fingerprint, "contains_personal_env": False}
    (output / "build_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        cleanup_state["archive_created"] = True
        for path in sorted(output.rglob("*")):
            if path.is_file():
                archive.write(path, str(Path(output.name) / path.relative_to(output)))
    cleanup_state["complete"] = True
    print("DESKTOP_ZIP=" + str(archive_path), flush=True)
    print("DESKTOP_OUTPUT=" + str(output), flush=True)
    print("BUILD_TEMP_ROOT=" + str(paths.temp_root), flush=True)
    return output


if __name__ == "__main__":
    build()
