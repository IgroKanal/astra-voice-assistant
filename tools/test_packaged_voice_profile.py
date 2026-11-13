"""Verify the frozen worker consumes DPAPI voice/name settings and extra wake phrase."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.desktop_settings import AIProfile, DesktopSettings
from src.runtime_events import parse_event


def main():
    root = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="astra-voice-eval-") as temp:
        settings = DesktopSettings(Path(temp) / "AstraVoiceAssistant" / "settings.dpapi")
        settings.save(AIProfile(provider="disabled", assistant_name="Мику", voice_id="synthetic-voice-id", microphone_index=2, voice_rate=210, voice_volume=.65))
        env = dict(os.environ, LOCALAPPDATA=temp, ASTRA_IGNORE_DESKTOP_SETTINGS="0", TTS_ENABLED="false", VPN_ENABLED="false", ASTRA_DESKTOP_EVENTS="1", PYTHONIOENCODING="utf-8")
        result = subprocess.run([str(root / "runtime" / "AstraRuntime" / "AstraRuntime.exe"), "--text"], input="Мику, сколько времени\nМику, стоп\n", cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        events = [event for line in result.stdout.splitlines() if (event := parse_event(line))]
        answers = [text for kind, text in events if kind == "assistant"]
        assert result.returncode == 0 and any("Сейчас" in answer for answer in answers), "Custom wake name failed in packaged runtime"
        applied = settings.apply(__import__("src.config_loader", fromlist=["Settings"]).Settings())
        assert applied.assistant_name == "Мику" and applied.tts_voice_name == "synthetic-voice-id"
        assert applied.stt_device_index == 2 and applied.tts_engine == "sapi"
        print("PACKAGED_VOICE_PASS: encrypted profile applied; custom wake phrase routed locally")


if __name__ == "__main__":
    main()
