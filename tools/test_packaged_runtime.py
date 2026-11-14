"""Offline text regression against the actual frozen runtime executable."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import sqlite3
from contextlib import closing

def main():
    root = Path(sys.argv[1]).resolve()
    runtime = root / "runtime" / "AstraRuntime" / "AstraRuntime.exe"
    assert runtime.is_file(), "Packaged runtime missing"
    assert (root / "Astra.exe").is_file(), "Desktop executable missing"
    edge_tts = runtime.parent / "edge-tts.exe"
    edge_playback = runtime.parent / "edge-playback.exe"
    assert edge_tts.is_file(), "Portable Edge TTS helper missing"
    assert edge_playback.is_file(), "Portable Edge playback helper missing"
    helper_env = dict(os.environ, PATH=str(runtime.parent) + os.pathsep + os.environ.get("PATH", ""))
    tts_version = subprocess.run([str(edge_tts), "--version"], env=helper_env, capture_output=True, text=True, timeout=20)
    playback_help = subprocess.run([str(edge_playback), "--help"], env=helper_env, capture_output=True, text=True, timeout=20)
    assert tts_version.returncode == 0 and tts_version.stdout.strip().startswith("edge-tts 7.3."), "Packaged Edge TTS helper failed"
    assert playback_help.returncode == 0 and "Speak text" in (playback_help.stdout + playback_help.stderr), "Packaged Edge playback helper failed"
    assert (root / "third_party_licenses" / "edge-tts-LICENSE.txt").is_file(), "Bundled Edge TTS license missing"
    edge_source_root = root / "third_party_sources" / ("edge-tts-" + tts_version.stdout.strip().split()[-1])
    assert (edge_source_root / "edge_tts" / "__main__.py").is_file(), "Corresponding Edge TTS source missing"
    assert (edge_source_root / "edge_playback" / "__main__.py").is_file(), "Corresponding Edge playback source missing"
    assert not (root / ".env").exists(), "Personal .env must not be included"
    assert not (root / ".venv").exists(), "Portable package must not depend on .venv"
    env = dict(os.environ, LLM_ENABLED="false", VPN_ENABLED="false", TTS_ENABLED="false", PYTHONUTF8="1", PYTHONIOENCODING="utf-8", ASTRA_DESKTOP_EVENTS="1", ASTRA_IGNORE_DESKTOP_SETTINGS="1")
    with tempfile.TemporaryDirectory(prefix="astra-runtime-check-") as temp:
        env["LOCALAPPDATA"] = temp
        private_marker = "astra-package-private-value"
        result = subprocess.run([str(runtime), "--text"], input=f"Астра, сколько времени\nАстра, начни новый диалог\nАстра, что значит api_key={private_marker}\nАстра, стоп\n", cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        audit = Path(temp) / "AstraVoiceAssistant" / "actions.sqlite"
        assert audit.is_file(), "Frozen runtime did not create isolated action audit"
        with closing(sqlite3.connect(audit)) as db:
            rows = db.execute("SELECT action,outcome FROM events").fetchall()
        assert ("get_time", "dispatch_allowed") in rows, "Time query was not audited"
        logs = list((Path(temp) / "AstraVoiceAssistant" / "logs").glob("*.log*"))
        assert logs, "Isolated diagnostic log missing"
        assert all(private_marker not in path.read_text(encoding="utf-8") for path in logs), "User content leaked into diagnostic logs"
        assert private_marker.encode() not in audit.read_bytes(), "User content leaked into action audit"
        print("PACKAGED_LOG_PRIVACY_PASS: synthetic private input absent from diagnostic and action logs")
        print("PACKAGED_ACTION_AUDIT_PASS: frozen runtime persisted metadata in an isolated user profile")
    assert result.returncode == 0, result.stderr
    assert "Сейчас" in result.stdout, result.stdout + result.stderr
    assert '"type": "conversation_reset"' in result.stdout, "Frozen runtime did not confirm the new-dialogue reset"
    assert "Начала новый диалог" in result.stdout, "Frozen runtime did not acknowledge the new dialogue"
    assert "Traceback" not in result.stderr, result.stderr
    assert "@ASTRA_EVENT" in result.stdout, "Structured desktop protocol is missing"
    print("PACKAGED_RUNTIME_PASS: standalone executable answered a local command, reset dialogue and exited cleanly")


if __name__ == "__main__":
    main()
