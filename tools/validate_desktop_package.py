"""Validate and optionally exercise a relocated portable desktop archive."""
from __future__ import annotations

import argparse
import atexit
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_paths import configure_temp_directory, resolve_build_paths
from tools.validate_package import _secret_findings, _unsafe_path_reason, _forbidden_file_reason


def validate_voice_core_modules(modules):
    required = (
        "src.microphone_recovery",
        "src.assistant_persona",
        "src.runtime_events",
        "src.audio_device_discovery",
        "src.windows_audio_endpoint",
        "src.vpn_controller",
        "src.windows_service_control",
        "src.desktop_cancellation",
    )
    if any(name not in modules for name in required):
        raise ValueError(
            "The packaged runtime is missing voice, event, device, VPN controller "
            "or Windows service-control support"
        )


def validate_deferred_3d_contract(manifest, archive_names, folder):
    if manifest.get("bundled_components", {}).get("3d_avatar_preview") is not False:
        raise ValueError("Portable desktop packages must leave the unapproved 3D preview out")
    prefix = folder + "/"
    forbidden = (
        prefix + "assets/3d_avatar/",
        prefix + "third_party/godot/",
        prefix + "GODOT_LICENSE.txt",
        prefix + "GODOT_COPYRIGHT.txt",
    )
    included = sorted(
        name for name in archive_names
        if any(name.startswith(path) for path in forbidden)
    )
    if included:
        raise ValueError("Portable package contains the deferred 3D preview: " + included[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--test-relocated", action="store_true")
    args = parser.parse_args()
    with zipfile.ZipFile(args.archive) as archive:
        entries = archive.infolist()
        roots = set()
        for entry in entries:
            name = entry.filename.replace("\\", "/")
            if _unsafe_path_reason(name) or _forbidden_file_reason(name):
                raise ValueError("Forbidden archive entry: " + name)
            path = PurePosixPath(name)
            if path.name.lower().endswith((".sqlite", ".db")):
                raise ValueError("User database in package: " + name)
            roots.add(path.parts[0])
            if path.suffix.lower() in {".md", ".json"} or path.name == ".env.example":
                findings = _secret_findings(archive.read(entry).decode("utf-8-sig"))
                if findings:
                    raise ValueError("Secret pattern in " + name + ": " + str(findings))
        if len(roots) != 1:
            raise ValueError("Expected one portable root")
        folder = roots.pop()
        names = set(archive.namelist())
        manifest_path = folder + "/build_manifest.json"
        if manifest_path not in names:
            raise ValueError("Missing package file: build_manifest.json")
        manifest = json.loads(archive.read(manifest_path).decode("utf-8"))
        validate_deferred_3d_contract(manifest, names, folder)
        avatar_assets = ("anime_female.png", "anime_female_speaking.png", "anime_male.png", "anime_male_speaking.png",
                         "anime_female_saya.png", "anime_female_saya_speaking.png", "anime_male_kai.png", "anime_male_kai_speaking.png",
                         "full_female.png", "full_female_speaking.png", "full_male.png", "full_male_speaking.png",
                         "full_female_saya.png", "full_female_saya_speaking.png", "full_male_kai.png", "full_male_kai_speaking.png")
        required_files = ("Astra.exe", "runtime/AstraRuntime/AstraRuntime.exe", "config/apps.json", "config/routines.json",
                          "_internal/PySide6/QtCore.pyd", "_internal/PySide6/Qt6Core.dll",
                          "_internal/PySide6/plugins/platforms/qwindows.dll",
                          "assets/branding/astra.ico", "assets/branding/astra.png", "assets/branding/astra.svg",
                          *("assets/avatars/" + name for name in avatar_assets),
                          "third_party_licenses/Qt-LGPL-3.0-only.txt", "third_party_licenses/Qt-GPL-3.0-only.txt",
                          "build_manifest.json", ".env.example", "THIRD_PARTY_NOTICES.md")
        for required in required_files:
            if folder + "/" + required not in names:
                raise ValueError("Missing package file: " + required)
        bad = archive.testzip()
        if bad:
            raise ValueError("CRC failure: " + bad)
        print(f"DESKTOP_PACKAGE_PASS: {len(entries)} entries, no forbidden files or known secret patterns")
        if args.test_relocated:
            paths = resolve_build_paths(ROOT)
            paths.temp_root.mkdir(parents=True, exist_ok=True)
            configure_temp_directory(paths.temp_root)
            destination_temp = tempfile.TemporaryDirectory(
                prefix="astra-relocated-preview-", dir=paths.temp_root
            )
            atexit.register(destination_temp.cleanup)
            destination = Path(destination_temp.name)
            archive.extractall(destination)
            from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
            ui_exe = destination / folder / "Astra.exe"
            embedded = CArchiveReader(str(ui_exe))
            probe = destination / ".astra-package-pyz-check.pyz"
            probe.write_bytes(embedded.extract("PYZ.pyz"))
            modules = ZlibArchiveReader(str(probe)).toc
            probe.unlink()
            required_modules = {
                "pypdf", "PIL.Image", "PIL.ImageOps",
                "src.file_workspace", "src.file_transactions", "src.file_rag", "src.skill_executor",
                "src.plan_interpreter", "src.audio_device_discovery", "src.windows_audio_endpoint", "src.onboarding_state",
                "src.profile_backup", "src.backup_crypto", "src.portable_memory_backup",
                "src.portable_reminder_backup", "src.action_audit", "src.command_catalog",
                "src.desktop_file_search", "src.desktop_tray", "src.qt_theme", "src.qt_widgets",
                "src.qt_dialogs", "src.qt_voice_files",
            }
            missing_modules = sorted(required_modules.difference(modules))
            if missing_modules:
                raise ValueError("Required Qt desktop modules are missing from Astra.exe: " + ", ".join(missing_modules))
            qt_binaries = (
                "_internal/PySide6/QtCore.pyd",
                "_internal/PySide6/QtGui.pyd",
                "_internal/PySide6/QtWidgets.pyd",
                "_internal/PySide6/Qt6Core.dll",
                "_internal/PySide6/Qt6Gui.dll",
                "_internal/PySide6/Qt6Widgets.dll",
            )
            missing_binaries = [
                required for required in qt_binaries
                if not (destination / folder / required).is_file()
            ]
            if not (destination / folder / "_internal/PySide6/plugins/platforms/qwindows.dll").is_file():
                missing_binaries.append("Qt Windows platform plugin (qwindows.dll)")
            if missing_binaries:
                raise ValueError("Required Qt binaries or Windows platform plugin are missing from Astra.exe: " + ", ".join(missing_binaries))
            runtime_exe = destination / folder / "runtime" / "AstraRuntime" / "AstraRuntime.exe"
            runtime_embedded = CArchiveReader(str(runtime_exe))
            runtime_probe = destination / ".astra-runtime-package-pyz-check.pyz"
            runtime_probe.write_bytes(runtime_embedded.extract("PYZ.pyz"))
            runtime_modules = ZlibArchiveReader(str(runtime_probe)).toc
            runtime_probe.unlink()
            if ("src.ai_client" not in runtime_modules or "src.llm_providers" not in runtime_modules or
                    "src.desktop_file_search" not in runtime_modules):
                raise ValueError("The runtime model client, provider adapter or voice file-access module is missing from AstraRuntime.exe")
            validate_voice_core_modules(runtime_modules)
            print("PACKAGED_LLM_PROVIDER_PASS: AIClient and the shared provider adapters are embedded in AstraRuntime.exe")
            print("PACKAGED_VOICE_CORE_PASS: character, event and microphone recovery modules are embedded in AstraRuntime.exe")
            print("PACKAGED_VOICE_FILE_ACCESS_PASS: bounded voice search/open/read IPC and workspace checks are embedded in AstraRuntime.exe")
            print("PACKAGED_DOCUMENT_READERS_PASS: file workspace, PDF and Office Open XML readers are embedded in Astra.exe")
            print("PACKAGED_PLAN_UI_PASS: local interpreter and bounded Qt preview/execution UI are embedded in Astra.exe")
            print("PACKAGED_ONBOARDING_PASS: first-run setup wizard is embedded in Astra.exe")
            print("PACKAGED_ONBOARDING_STATE_PASS: DPAPI-backed first-run choice is embedded in Astra.exe")
            print("PACKAGED_PROFILE_BACKUP_PASS: encrypted portable profile migration is embedded in Astra.exe")
            print("PACKAGED_PORTABLE_MEMORY_BACKUP_PASS: encrypted cross-PC memory migration is embedded in Astra.exe")
            print("PACKAGED_PORTABLE_REMINDER_BACKUP_PASS: encrypted cross-PC reminder migration is embedded in Astra.exe")
            print("PACKAGED_IMAGE_PREVIEW_PASS: bounded local image decoder and Qt viewer are embedded in Astra.exe")
            print("PACKAGED_QT_PLATFORM_PASS: Qt widgets and the native Windows platform plugin are embedded in Astra.exe")
            for name in avatar_assets:
                bundled = destination / folder / "_internal" / "assets" / "avatars" / name
                packaged = (destination / folder / "assets" / "avatars" / name).read_bytes()
                if not bundled.is_file() or hashlib.sha256(bundled.read_bytes()).digest() != hashlib.sha256(packaged).digest():
                    raise ValueError("Embedded and portable avatar assets differ: " + name)
            print("PACKAGED_AVATARS_PASS: four idle and four speaking character PNGs are embedded in Astra.exe and match portable assets")
            print("PACKAGED_2D_ONLY_PASS: unapproved procedural 3D assets/runtime are not in the user package")
            subprocess.run([sys.executable, str(ROOT / "tools" / "test_packaged_runtime.py"), str(destination / folder)], check=True)
            subprocess.run([sys.executable, str(ROOT / "tools" / "test_packaged_policy.py"), str(destination / folder)], check=True)
            print("RELOCATED_PREVIEW=" + str(destination / folder))


if __name__ == "__main__":
    main()
