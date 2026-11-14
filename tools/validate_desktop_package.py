"""Validate and optionally exercise a relocated portable desktop archive."""
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.validate_package import _secret_findings, _unsafe_path_reason, _forbidden_file_reason


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
        avatar_assets = ("anime_female.png", "anime_female_speaking.png", "anime_male.png", "anime_male_speaking.png",
                         "anime_female_saya.png", "anime_female_saya_speaking.png", "anime_male_kai.png", "anime_male_kai_speaking.png")
        required_files = ("Astra.exe", "runtime/AstraRuntime/AstraRuntime.exe", "config/apps.json", "config/routines.json",
                          "assets/branding/astra.ico", "assets/branding/astra.png", "assets/branding/astra.svg",
                          *("assets/avatars/" + name for name in avatar_assets), "assets/3d_avatar/project.godot",
                          "assets/3d_avatar/main.tscn", "assets/3d_avatar/scripts/avatar_viewer.gd",
                          "third_party/godot/Godot_v4.7.2-stable_win64.exe", "GODOT_LICENSE.txt", "GODOT_COPYRIGHT.txt",
                          "build_manifest.json", ".env.example", "THIRD_PARTY_NOTICES.md")
        for required in required_files:
            if folder + "/" + required not in names:
                raise ValueError("Missing package file: " + required)
        bad = archive.testzip()
        if bad:
            raise ValueError("CRC failure: " + bad)
        print(f"DESKTOP_PACKAGE_PASS: {len(entries)} entries, no forbidden files or known secret patterns")
        if args.test_relocated:
            destination = Path(tempfile.mkdtemp(prefix="astra relocated preview "))
            archive.extractall(destination)
            from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
            ui_exe = destination / folder / "Astra.exe"
            embedded = CArchiveReader(str(ui_exe))
            probe = destination / ".astra-package-pyz-check.pyz"
            probe.write_bytes(embedded.extract("PYZ.pyz"))
            modules = ZlibArchiveReader(str(probe)).toc
            probe.unlink()
            if ("pypdf" not in modules or "src.file_workspace" not in modules or
                    "src.plan_ui" not in modules or "src.plan_interpreter" not in modules or
                    "src.avatar_preview" not in modules or "src.onboarding_ui" not in modules or
                    "src.onboarding_state" not in modules or "src.profile_backup" not in modules or
                    "src.backup_crypto" not in modules or "src.portable_memory_backup" not in modules or
                    "src.portable_reminder_backup" not in modules or
                    "src.action_audit" not in modules or "src.action_audit_ui" not in modules or
                    "src.desktop_theme" not in modules or "src.scroll_section" not in modules or
                    "src.command_catalog" not in modules or "src.command_catalog_ui" not in modules or
                    "src.desktop_file_search" not in modules or
                    "PIL.Image" not in modules or "PIL.ImageOps" not in modules or "PIL.ImageTk" not in modules):
                raise ValueError("A file reader, plan interpreter, plan UI, avatar preview or onboarding module is missing from Astra.exe")
            runtime_exe = destination / folder / "runtime" / "AstraRuntime" / "AstraRuntime.exe"
            runtime_embedded = CArchiveReader(str(runtime_exe))
            runtime_probe = destination / ".astra-runtime-package-pyz-check.pyz"
            runtime_probe.write_bytes(runtime_embedded.extract("PYZ.pyz"))
            runtime_modules = ZlibArchiveReader(str(runtime_probe)).toc
            runtime_probe.unlink()
            if ("src.ai_client" not in runtime_modules or "src.llm_providers" not in runtime_modules or
                    "src.desktop_file_search" not in runtime_modules):
                raise ValueError("The runtime model client, provider adapter or voice file-access module is missing from AstraRuntime.exe")
            print("PACKAGED_LLM_PROVIDER_PASS: AIClient and the shared provider adapters are embedded in AstraRuntime.exe")
            print("PACKAGED_VOICE_FILE_ACCESS_PASS: bounded voice search/open IPC and workspace checks are embedded in AstraRuntime.exe")
            print("PACKAGED_DOCUMENT_READERS_PASS: file workspace, PDF and Office Open XML readers are embedded in Astra.exe")
            print("PACKAGED_PLAN_UI_PASS: local interpreter and bounded preview/execution UI are embedded in Astra.exe")
            print("PACKAGED_AVATAR_LAUNCHER_PASS: the packaged UI includes the isolated 3D preview launcher")
            print("PACKAGED_ONBOARDING_PASS: first-run setup wizard is embedded in Astra.exe")
            print("PACKAGED_ONBOARDING_STATE_PASS: DPAPI-backed first-run choice is embedded in Astra.exe")
            print("PACKAGED_PROFILE_BACKUP_PASS: encrypted portable profile migration is embedded in Astra.exe")
            print("PACKAGED_PORTABLE_MEMORY_BACKUP_PASS: encrypted cross-PC memory migration is embedded in Astra.exe")
            print("PACKAGED_PORTABLE_REMINDER_BACKUP_PASS: encrypted cross-PC reminder migration is embedded in Astra.exe")
            print("PACKAGED_IMAGE_PREVIEW_PASS: bounded local image decoder and Tk viewer are embedded in Astra.exe")
            for name in avatar_assets:
                internal = "assets\\avatars\\" + name
                payload = embedded.extract(internal)
                packaged = (destination / folder / "assets" / "avatars" / name).read_bytes()
                if hashlib.sha256(payload).digest() != hashlib.sha256(packaged).digest():
                    raise ValueError("Embedded and portable avatar assets differ: " + name)
            print("PACKAGED_AVATARS_PASS: four idle and four speaking character PNGs are embedded in Astra.exe and match portable assets")
            godot = destination / folder / "third_party" / "godot" / "Godot_v4.7.2-stable_win64.exe"
            project = destination / folder / "assets" / "3d_avatar"
            version = subprocess.run([str(godot), "--headless", "--version"], capture_output=True, text=True, timeout=30)
            if version.returncode != 0 or not version.stdout.strip().startswith("4.7.2."):
                raise ValueError("Relocated Godot runtime did not report the expected stable version")
            from tools.validate_3d_avatar import validate_runtime_ipc
            validate_runtime_ipc(godot, project)
            print("PACKAGED_3D_AVATAR_PASS: relocated Godot runtime receives authenticated live state")
            subprocess.run([sys.executable, str(ROOT / "tools" / "test_packaged_runtime.py"), str(destination / folder)], check=True)
            subprocess.run([sys.executable, str(ROOT / "tools" / "test_packaged_policy.py"), str(destination / folder)], check=True)
            print("RELOCATED_PREVIEW=" + str(destination / folder))


if __name__ == "__main__":
    main()
