"""Install, launch the local runtime, and uninstall without losing user data."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_paths import resolve_build_paths


def run(
    args: list[str],
    env: dict[str, str],
    timeout: int = 180,
    cwd: Path | None = None,
    input_data: str | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_data,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def validate(installer: Path) -> None:
    installer = installer.resolve(strict=True)
    paths = resolve_build_paths(installer.parent)
    paths.temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="astra-installer-check-", dir=paths.temp_root
    ) as temp:
        root = Path(temp)
        child_temp = root / "temp"
        child_temp.mkdir()
        install_root = root / "Astra installed under a path with spaces"
        local_app_data = root / "User profile" / "AppData" / "Local"
        user_data = local_app_data / "AstraVoiceAssistant"
        user_data.mkdir(parents=True)
        sentinel = user_data / "user-data-preservation.txt"
        sentinel.write_text("keep this user data", encoding="utf-8")
        env = dict(
            os.environ,
            LOCALAPPDATA=str(local_app_data),
            TEMP=str(child_temp),
            TMP=str(child_temp),
            TMPDIR=str(child_temp),
        )

        setup = run(
            [
                str(installer),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/NOICONS",
                f"/DIR={install_root}",
            ],
            env,
        )
        if setup.returncode != 0:
            raise RuntimeError(f"Installer failed ({setup.returncode}): {setup.stderr}")

        runtime = install_root / "runtime" / "AstraRuntime" / "AstraRuntime.exe"
        app = install_root / "Astra.exe"
        if not app.is_file() or not runtime.is_file():
            raise RuntimeError("Installer did not place the desktop/runtime executables")
        edge_tts = runtime.parent / "edge-tts.exe"
        edge_playback = runtime.parent / "edge-playback.exe"
        if not edge_tts.is_file() or not edge_playback.is_file():
            raise RuntimeError("Installer did not place the portable Edge TTS helpers")
        helper_env = dict(env, PATH=str(runtime.parent) + os.pathsep + os.environ.get("PATH", ""))
        tts_version = run([str(edge_tts), "--version"], helper_env, timeout=20)
        playback_help = run([str(edge_playback), "--help"], helper_env, timeout=20)
        if tts_version.returncode != 0 or not tts_version.stdout.strip().startswith("edge-tts 7.3."):
            raise RuntimeError("Installed Edge TTS helper failed its local version check")
        if playback_help.returncode != 0 or "Speak text" not in playback_help.stdout + playback_help.stderr:
            raise RuntimeError("Installed Edge playback helper failed its local help check")
        if not (install_root / "third_party_licenses" / "edge-tts-LICENSE.txt").is_file():
            raise RuntimeError("Installer did not place the bundled Edge TTS license")

        runtime_env = dict(
            env,
            ASTRA_DESKTOP_EVENTS="1",
            ASTRA_IGNORE_DESKTOP_SETTINGS="1",
            LLM_ENABLED="false",
            VPN_ENABLED="false",
            TTS_ENABLED="false",
            PYTHONUTF8="1",
            PYTHONIOENCODING="utf-8",
        )
        launch = run(
            [str(runtime), "--text"],
            env=runtime_env,
            timeout=60,
            cwd=install_root,
            input_data="Астра, сколько времени\nАстра, начни новый диалог\nАстра, стоп\n",
        )
        if (
            launch.returncode != 0
            or "Сейчас" not in launch.stdout
            or '"type": "conversation_reset"' not in launch.stdout
            or "Начала новый диалог" not in launch.stdout
            or "Traceback" in launch.stderr
        ):
            raise RuntimeError(
                "Installed runtime smoke failed: "
                f"returncode={launch.returncode}, stdout={launch.stdout[-1000:]!r}, "
                f"stderr={launch.stderr[-1000:]!r}"
            )
        app_log = user_data / "logs" / "app.log"
        if not app_log.is_file():
            raise RuntimeError("Runtime did not place logs in per-user LocalAppData")
        if (install_root / "logs").exists():
            raise RuntimeError("Runtime created logs inside the install directory")

        uninstaller = install_root / "unins000.exe"
        if not uninstaller.is_file():
            raise RuntimeError("Inno Setup uninstaller is missing")
        uninstall = run(
            [
                str(uninstaller),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
            ],
            env,
        )
        if uninstall.returncode != 0:
            raise RuntimeError(f"Uninstaller failed ({uninstall.returncode}): {uninstall.stderr}")
        if app.exists() or runtime.exists():
            raise RuntimeError("Uninstall left application binaries in its install directory")
        if sentinel.read_text(encoding="utf-8") != "keep this user data":
            raise RuntimeError("Uninstall changed user data")
        if app_log.read_text(encoding="utf-8").strip() == "":
            raise RuntimeError("Expected user log data was removed or emptied")
    print("ASTRA_INSTALLER_PASS: install, runtime, LocalAppData logs and data-preserving uninstall")


def main() -> int:
    if os.name != "nt":
        raise SystemExit("Installer integration validation requires Windows")
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_installer.py <installer.exe>")
    validate(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
