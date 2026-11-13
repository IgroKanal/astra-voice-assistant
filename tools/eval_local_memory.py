"""Opt-in local memory eval using synthetic data, never user's real notes."""
from pathlib import Path
import json
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.ai_client import AIClient
from src.config_loader import Settings
from src.personal_memory import PersonalMemory


def main():
    with tempfile.TemporaryDirectory(prefix="astra-memory-eval-") as temp:
        path = Path(temp) / "synthetic.sqlite"
        PersonalMemory(path).add("Тестовое кодовое слово", "Моё тестовое кодовое слово — ЛИМОН.")
        settings = Settings(llm_provider="ollama", llm_base_url="http://127.0.0.1:11434", llm_model="qwen3:4b", llm_timeout_seconds=120, personal_memory_enabled=True, personal_memory_path=str(path), llm_router_enabled=False)
        start = time.monotonic()
        result = AIClient(settings).ask("Назови моё тестовое кодовое слово из сохранённой заметки. Ответь одним словом.")
        passed = result.ok and "лимон" in result.message.casefold()
        print(json.dumps({"passed": passed, "answer": result.message, "seconds": round(time.monotonic() - start, 2), "data": "synthetic only"}, ensure_ascii=True))
        if not passed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
