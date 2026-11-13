"""Build an isolated portable preview; never copy the user's .env or logs."""
from __future__ import annotations

from datetime import datetime
import hashlib
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


def build() -> Path:
    inputs = [ROOT / name for name in ("main.py", "astra_desktop.pyw", "astra_runtime.py", "requirements.txt", "requirements-desktop.txt", "requirements-build.txt", "DESKTOP_PREVIEW.md", "THIRD_PARTY_NOTICES.md", ".env.example", "src/version.py")]
    inputs += list((ROOT / "src").glob("*.py")) + list((ROOT / "config").glob("*.json")) + list((ROOT / "assets" / "avatars").glob("*.png"))
    avatar_project = ROOT / "prototypes" / "3d_avatar"
    icon = ROOT / "assets" / "branding" / "astra.ico"
    inputs += list((ROOT / "assets" / "branding").glob("*"))
    inputs += [path for path in avatar_project.rglob("*") if path.is_file() and ".godot" not in path.parts]
    godot_value = os.environ.get("ASTRA_GODOT_EXECUTABLE", "").strip()
    if not godot_value:
        raise RuntimeError("Set ASTRA_GODOT_EXECUTABLE to the verified Godot 4.7.2 Windows binary before building the portable app")
    godot_executable = Path(godot_value).resolve(strict=True)
    version_result = subprocess.run([str(godot_executable), "--headless", "--version"], capture_output=True, text=True, timeout=20)
    if version_result.returncode != 0 or not version_result.stdout.strip().startswith("4.7.2."):
        raise RuntimeError("The packaged 3D preview requires Godot 4.7.2 stable")
    signature_script = "$sig = Get-AuthenticodeSignature -LiteralPath $env:ASTRA_GODOT_EXECUTABLE; if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notlike '*Prehensile Tales B.V.*') { exit 1 }; $sig.SignerCertificate.Subject"
    powershell_environment = {**os.environ, "ASTRA_GODOT_EXECUTABLE": str(godot_executable)}
    powershell_environment["PSModulePath"] = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "Modules")
    signature_result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", signature_script],
                                      env=powershell_environment,
                                      capture_output=True, text=True, timeout=30)
    if signature_result.returncode != 0:
        raise RuntimeError("Godot Authenticode signature is invalid or not from Prehensile Tales B.V.")
    inputs += [ROOT / "GODOT_LICENSE.txt", ROOT / "GODOT_COPYRIGHT.txt", godot_executable]
    def input_key(path: Path) -> str:
        try:
            return str(path.relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            return "third_party/godot/" + path.name
    fingerprint = {input_key(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    output_root = Path(os.environ.get("ASTRA_BUILD_OUTPUT_ROOT", str(ROOT.parent))).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / ("AstraDesktop-preview-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    output.mkdir(exist_ok=False)
    work = Path(tempfile.mkdtemp(prefix="astra-desktop-build-"))
    common = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--noupx", "--clean", "--specpath", str(work), "--icon", str(icon)]
    subprocess.run(common + ["--name", "Astra", "--onefile", "--windowed", "--distpath", str(output), "--workpath", str(work / "ui"), "--add-data", str(ROOT / "assets" / "avatars") + ":assets/avatars", str(ROOT / "astra_desktop.pyw")], cwd=ROOT, check=True)
    subprocess.run(common + ["--name", "AstraRuntime", "--onedir", "--console", "--distpath", str(output / "runtime"), "--workpath", str(work / "runtime"), "--collect-submodules", "pyttsx3.drivers", "--add-data", str(ROOT / "config") + ":config", str(ROOT / "astra_runtime.py")], cwd=ROOT, check=True)
    shutil.copytree(ROOT / "config", output / "config")
    shutil.copytree(ROOT / "assets", output / "assets")
    shutil.copytree(avatar_project, output / "assets" / "3d_avatar", ignore=shutil.ignore_patterns(".godot", "*.tmp"))
    godot_target = output / "third_party" / "godot" / "Godot_v4.7.2-stable_win64.exe"
    godot_target.parent.mkdir(parents=True)
    shutil.copy2(godot_executable, godot_target)
    shutil.copy2(ROOT / "GODOT_LICENSE.txt", output / "GODOT_LICENSE.txt")
    shutil.copy2(ROOT / "GODOT_COPYRIGHT.txt", output / "GODOT_COPYRIGHT.txt")
    shutil.copy2(ROOT / ".env.example", output / ".env.example")
    shutil.copy2(ROOT / "DESKTOP_PREVIEW.md", output / "README.md")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", output / "THIRD_PARTY_NOTICES.md")
    for path in inputs:
        if hashlib.sha256(path.read_bytes()).hexdigest() != fingerprint[input_key(path)]:
            raise RuntimeError("Source or Godot runtime changed during build; discard this preview and rebuild")
    from src.version import PRODUCT_VERSION
    manifest = {"product": "Astra Desktop", "version": PRODUCT_VERSION, "built_at": datetime.now().isoformat(), "python": sys.version.split()[0], "source_sha256": fingerprint, "contains_personal_env": False}
    (output / "build_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    archive_path = output.with_suffix(".zip")
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                archive.write(path, str(Path(output.name) / path.relative_to(output)))
    print("DESKTOP_ZIP=" + str(archive_path), flush=True)
    print("DESKTOP_OUTPUT=" + str(output), flush=True)
    print("BUILD_WORK=" + str(work), flush=True)
    return output


if __name__ == "__main__":
    build()
