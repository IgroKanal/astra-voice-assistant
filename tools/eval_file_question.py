"""Opt-in local model evaluation using a synthetic temporary document only."""
from pathlib import Path
import json
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.desktop_settings import AIProfile
from src.file_rag import FileQuestionSession
from src.file_workspace import FileWorkspace


def main():
    with tempfile.TemporaryDirectory(prefix="astra-file-eval-", dir=ROOT) as temp:
        root = Path(temp)
        (root / "project.txt").write_text("Тестовый документ.\nНазвание спутника проекта — ОРБИТА.\nСтарт проекта в июле.\n", encoding="utf-8")
        session = FileQuestionSession(FileWorkspace(root), "project.txt")
        start = time.monotonic()
        result = session.answer("Как называется спутник проекта? Ответь одним словом.", AIProfile(provider="ollama"))
        assert "ОРБИТА" in result.text.upper(), "Synthetic fact was not retrieved"
        print(json.dumps({"status": "LOCAL_FILE_QA_PASS", "seconds": round(time.monotonic() - start, 2), "answer": result.text, "source_count": len(result.passages)}, ensure_ascii=True))
        session.revoke()


if __name__ == "__main__":
    main()
