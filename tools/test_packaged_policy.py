"""Frozen worker must enforce encrypted capability revocation before dispatch."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import sqlite3
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.desktop_settings import AIProfile, DesktopSettings
from src.runtime_events import parse_event


def main():
    root = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="astra-policy-eval-") as temp:
        store = DesktopSettings(Path(temp) / "AstraVoiceAssistant" / "settings.dpapi")
        store.save(AIProfile(provider="disabled", allowed_scopes=()))
        env = dict(os.environ, LOCALAPPDATA=temp, ASTRA_DESKTOP_EVENTS="1", ASTRA_IGNORE_DESKTOP_SETTINGS="0", TTS_ENABLED="false", VPN_ENABLED="false", PYTHONIOENCODING="utf-8")
        result = subprocess.run([str(root / "runtime" / "AstraRuntime" / "AstraRuntime.exe"), "--text"], input="Астра, какие окна открыты\nАстра, сколько времени\nАстра, стоп\n", cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        events = [event for line in result.stdout.splitlines() if (event := parse_event(line))]
        answers = [text for kind, text in events if kind == "assistant"]
        assert result.returncode == 0, "Worker failed"
        assert any("отключён в разрешениях" in answer for answer in answers), "Revoked window scope was not denied"
        assert any("Сейчас" in answer for answer in answers), "Harmless time query regressed"
        with closing(sqlite3.connect(Path(temp) / "AstraVoiceAssistant" / "actions.sqlite")) as db:
            audit_rows = db.execute("SELECT action,outcome FROM events").fetchall()
        assert ("window_control", "blocked") in audit_rows, "Revoked action was not audited as blocked"
        env["ASTRA_DESKTOP_EVENTS"] = "0"
        console = subprocess.run([str(root / "runtime" / "AstraRuntime" / "AstraRuntime.exe"), "--text"], input="Астра, какие окна открыты\nАстра, стоп\n", cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert console.returncode == 0 and "отключён в разрешениях" in console.stdout, "Console launcher bypassed persisted capability revocation"
        print("PACKAGED_POLICY_PASS: encrypted profile denied revoked action in desktop and console modes; time query allowed")


if __name__ == "__main__":
    main()
