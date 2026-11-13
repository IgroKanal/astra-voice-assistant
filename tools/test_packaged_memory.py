"""Opt-in frozen desktop profile + encrypted synthetic memory integration."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.desktop_settings import AIProfile, DesktopSettings
from src.personal_memory import PersonalMemory
from src.runtime_events import parse_event


def main():
    root = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="astra-frozen-memory-") as temp:
        private = Path(temp) / "AstraVoiceAssistant"
        DesktopSettings(private / "settings.dpapi").save(AIProfile(provider="ollama", memory_enabled=True))
        PersonalMemory(private / "memory.sqlite").add("Тестовое кодовое слово", "Моё тестовое кодовое слово — ЛИМОН.")
        env = dict(os.environ, LOCALAPPDATA=temp, ASTRA_DESKTOP_EVENTS="1", ASTRA_IGNORE_DESKTOP_SETTINGS="0", TTS_ENABLED="false", VPN_ENABLED="false", PYTHONIOENCODING="utf-8")
        runtime = root / "runtime" / "AstraRuntime" / "AstraRuntime.exe"
        start = time.monotonic()
        result = subprocess.run([str(runtime), "--text"], input="Астра, назови моё тестовое кодовое слово из сохранённой заметки. Ответь одним словом.\nАстра, стоп\n", cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=150, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        events = [event for line in result.stdout.splitlines() if (event := parse_event(line))]
        answers = [text for kind, text in events if kind == "assistant"]
        assert result.returncode == 0, "Frozen worker failed"
        assert any("лимон" in answer.casefold() for answer in answers), repr(answers)
        print(f"PACKAGED_MEMORY_PASS: encrypted profile + synthetic encrypted note -> local answer; elapsed={time.monotonic()-start:.2f}s; real user profile untouched")


if __name__ == "__main__":
    main()
