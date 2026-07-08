from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import ConfigError, load_apps_config, load_settings


REQUIRED_FILES = (
    "main.py",
    ".env.example",
    "requirements.txt",
    "config/apps.json",
    "src/command_parser.py",
    "src/audio_io.py",
    "src/config_loader.py",
    "src/task_router.py",
    "src/vpn_controller.py",
    "src/window_controller.py",
    "start_astra_debug.bat",
    "start_astra_text.bat",
    "start_astra_hidden.vbs",
    "tools/install_autostart.ps1",
    "tools/uninstall_autostart.ps1",
)


def ok(message: str) -> None:
    print(f"[OK] {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def fail(message: str) -> None:
    print(f"[FAIL] {message}")


def check_files() -> int:
    problems = 0
    for relative in REQUIRED_FILES:
        path = PROJECT_ROOT / relative
        if path.exists():
            ok(f"file exists: {relative}")
        else:
            fail(f"missing file: {relative}")
            problems += 1
    return problems


def check_python() -> int:
    problems = 0
    version = sys.version_info
    print(f"Python: {sys.version.split()[0]} | executable={sys.executable}")
    if version.major == 3 and version.minor >= 10:
        ok("Python version is supported")
    else:
        fail("Python 3.10+ is required")
        problems += 1

    if ".venv" in str(Path(sys.executable)).lower():
        ok("running from project virtual environment")
    else:
        warn("not running from .venv; this may be okay for CI, but local app should use .venv")

    return problems


def check_settings() -> int:
    problems = 0
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        ok(".env exists")
    else:
        warn(".env is missing; defaults/.env.example will be used")

    try:
        settings = load_settings(env_path if env_path.exists() else PROJECT_ROOT / ".env.example")
    except Exception as exc:
        fail(f"settings load failed: {exc}")
        return 1

    print(f"assistant_name={settings.assistant_name}")
    print(f"llm_provider={settings.llm_provider}")
    print(f"llm_model={settings.llm_model}")
    print(f"llm_fallback_model={settings.llm_fallback_model}")
    print(f"browser_preferred={settings.browser_preferred or '<not set>'}")
    print(f"vpn_enabled={settings.vpn_enabled}")
    print(f"vpn_tunnel_service_name={settings.vpn_tunnel_service_name}")
    print(f"tts_cache_prewarm_max_new_phrases={settings.tts_cache_prewarm_max_new_phrases}")
    print(f"tts_cache_generation_timeout_seconds={settings.tts_cache_generation_timeout_seconds}")

    if settings.llm_enabled and not settings.llm_api_key:
        warn("LLM is enabled but API key is not configured")
    else:
        ok("LLM key configuration is acceptable")

    if settings.tts_cache_generation_timeout_seconds < 5:
        fail("TTS_CACHE_GENERATION_TIMEOUT_SECONDS must be at least 5")
        problems += 1

    return problems


def check_apps() -> int:
    try:
        apps = load_apps_config(PROJECT_ROOT / "config" / "apps.json")
    except ConfigError as exc:
        fail(f"apps config invalid: {exc}")
        return 1

    ok(f"apps loaded: {len(apps)}")
    for required in ("firefox", "vscode", "telegram", "блокнот"):
        if required in apps:
            ok(f"app configured: {required}")
        else:
            warn(f"app not configured by key: {required}")
    return 0


def _service_status(service_name: str) -> str:
    if platform.system().lower() != "windows":
        return "not_windows"

    script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$svc = Get-Service -Name '{service_name.replace("'", "''")}' -ErrorAction SilentlyContinue
if ($null -eq $svc) {{ [Console]::Write('not_found') }} else {{ [Console]::Write($svc.Status.ToString()) }}
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return (result.stdout or result.stderr or "unknown").strip()
    except Exception as exc:
        return f"error: {exc}"


def check_windows_integrations() -> int:
    problems = 0
    settings = load_settings(PROJECT_ROOT / ".env" if (PROJECT_ROOT / ".env").exists() else PROJECT_ROOT / ".env.example")

    if platform.system().lower() != "windows":
        warn("Windows integration checks skipped: not running on Windows")
        return 0

    for command in ("powershell.exe", "wscript.exe"):
        if shutil.which(command):
            ok(f"available: {command}")
        else:
            fail(f"missing command: {command}")
            problems += 1

    if settings.vpn_enabled:
        status = _service_status(settings.vpn_tunnel_service_name)
        if status.lower() in {"running", "stopped", "startpending", "stoppending"}:
            ok(f"VPN service found: {settings.vpn_tunnel_service_name} status={status}")
        else:
            warn(f"VPN service status check: {settings.vpn_tunnel_service_name} -> {status}")

    return problems


def main() -> None:
    print("Astra doctor")
    print(f"project_root={PROJECT_ROOT}")
    print("-" * 60)

    problems = 0
    problems += check_python()
    print("-" * 60)
    problems += check_files()
    print("-" * 60)
    problems += check_settings()
    print("-" * 60)
    problems += check_apps()
    print("-" * 60)
    problems += check_windows_integrations()
    print("-" * 60)

    if problems:
        print(f"Astra doctor finished with {problems} blocking problem(s).")
        raise SystemExit(1)

    print("Astra doctor passed. Non-blocking warnings may still need manual review.")


if __name__ == "__main__":
    main()
