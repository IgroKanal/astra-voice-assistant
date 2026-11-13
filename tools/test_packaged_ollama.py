"""Opt-in live local-model test for the frozen runtime; never uses cloud."""
from pathlib import Path
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.runtime_events import parse_event


def main():
    root = Path(sys.argv[1]).resolve()
    model = sys.argv[2] if len(sys.argv) > 2 else "qwen3:4b"
    runtime = root / "runtime" / "AstraRuntime" / "AstraRuntime.exe"
    env = dict(os.environ, ASTRA_IGNORE_DESKTOP_SETTINGS="1", ASTRA_DESKTOP_EVENTS="1", LLM_ENABLED="true", LLM_PROVIDER="ollama", LLM_BASE_URL="http://127.0.0.1:11434", GEMINI_MODEL=model, LLM_MODEL=model, LLM_ROUTER_ENABLED="false", LLM_TIMEOUT_SECONDS="120", LLM_MAX_TOKENS="500", VPN_ENABLED="false", TTS_ENABLED="false", PYTHONIOENCODING="utf-8")
    start = time.monotonic()
    result = subprocess.run([str(runtime), "--text"], input="Астра, сколько будет 2 плюс 2? Ответь только числом.\nАстра, стоп\n", cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=150, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    events = [event for line in result.stdout.splitlines() if (event := parse_event(line))]
    answers = [text for kind, text in events if kind == "assistant"]
    assert result.returncode == 0, "Frozen local worker did not exit cleanly"
    assert any(answer.strip() == "4" for answer in answers), repr(answers)
    print(f"PACKAGED_OLLAMA_PASS: model={model} final_answer=4 elapsed={time.monotonic()-start:.2f}s; loopback-only, no cloud")


if __name__ == "__main__":
    main()
