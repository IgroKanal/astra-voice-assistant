"""Real packaged runtime creates encrypted reminders under an isolated profile."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.desktop_settings import AIProfile, DesktopSettings
from src.reminders import ReminderStore


def main():
    root = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="astra-reminders-eval-") as temp:
        profile = DesktopSettings(Path(temp) / "AstraVoiceAssistant" / "settings.dpapi")
        profile.save(AIProfile(provider="disabled"))
        env = dict(os.environ, LOCALAPPDATA=temp, ASTRA_IGNORE_DESKTOP_SETTINGS="0", TTS_ENABLED="false", VPN_ENABLED="false", ASTRA_DESKTOP_EVENTS="1", PYTHONIOENCODING="utf-8")
        command = [str(root / "runtime" / "AstraRuntime" / "AstraRuntime.exe"), "--text"]
        result = subprocess.run(command, input="Астра, напомни через одну минуту СИНТЕТИЧЕСКАЯЗАДАЧА\nАстра, стоп\n", cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0 and "Напоминание сохранено" in result.stdout, "Reminder runtime path failed"
        database = Path(temp) / "AstraVoiceAssistant" / "reminders.sqlite"
        store = ReminderStore(database)
        rows = store.list()
        assert len(rows) == 1 and "синтетическаязадача" in rows[0].text.lower()
        assert rows[0].text.encode("utf-8") not in database.read_bytes(), "Reminder payload is plaintext"
        profile.save(AIProfile(provider="disabled", allowed_scopes=()))
        denied = subprocess.run(command, input="Астра, напомни через одну минуту ЗАПРЕЩЕНО\nАстра, стоп\n", cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert denied.returncode == 0 and "отключён в разрешениях" in denied.stdout
        assert len(store.list()) == 1, "Revoked permission still created a reminder"
        print("PACKAGED_REMINDERS_PASS: local parser, persistence, DPAPI and revoked permission")


if __name__ == "__main__":
    main()
