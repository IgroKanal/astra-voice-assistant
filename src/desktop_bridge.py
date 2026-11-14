"""Own a single isolated Astra runtime without blocking the desktop UI."""
from __future__ import annotations

import os
from pathlib import Path
import queue
import subprocess
import threading
from src.runtime_events import parse_event
from src.desktop_file_search import encode_search_result

_UNSET_PROCESS = object()


class DesktopBridge:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.events: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=2000)
        self.process: subprocess.Popen | None = None
        self.mode = "text"
        self._lock = threading.RLock()
        self._shutdown = threading.Event()

    def emit(self, kind: str, text: str) -> None:
        try:
            self.events.put_nowait((kind, text))
        except queue.Full:
            # Diagnostic overflow must never block the child pipe reader.
            pass

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, mode: str = "text") -> None:
        with self._lock:
            self._start(mode)

    def prevent_restart(self) -> None:
        self._shutdown.set()

    def _start(self, mode: str) -> None:
        if self._shutdown.is_set():
            raise RuntimeError("Приложение завершает работу")
        if mode not in {"text", "voice"}:
            raise ValueError("Unknown runtime mode")
        if self.running:
            raise RuntimeError("Runtime already running")
        runtime = self.root / "runtime" / "AstraRuntime" / "AstraRuntime.exe"
        if runtime.is_file():
            command = [str(runtime)]
        else:
            python = self.root / ".venv" / "Scripts" / "python.exe"
            if not python.is_file():
                raise FileNotFoundError("Не найден runtime Astra или Python в .venv.")
            command = [str(python), "-u", str(self.root / "main.py")]
        if mode == "text":
            command.append("--text")
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", ASTRA_DESKTOP_EVENTS="1")
        process = subprocess.Popen(
            command, cwd=self.root, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.process = process
        self.mode = mode
        threading.Thread(target=self._read, args=(process,), daemon=True).start()
        self.emit("status", "Запуск голоса · инициализация микрофона…" if mode == "voice" else "Текстовый режим · микрофон выключен")

    def _read(self, process: subprocess.Popen) -> None:
        try:
            assert process.stdout is not None
            for line in process.stdout:
                event = parse_event(line.rstrip())
                if event:
                    self.emit(*event)
                else:
                    self.emit("output", line.rstrip())
        finally:
            code = process.wait()
            self.emit("exit", str(code))
            if process.stdout:
                process.stdout.close()

    def send(self, text: str) -> None:
        if not self.running or self.mode != "text":
            raise RuntimeError("Сначала включи текстовый режим")
        if "\n" in text or "\r" in text or len(text) > 8000:
            raise ValueError("Отправляй одну команду за раз (до 8000 символов)")
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def reply_file_search(self, result: dict, *, expected_process=_UNSET_PROCESS) -> bool:
        line = encode_search_result(result)
        if len(line) > 8192:
            raise ValueError("Результат поиска слишком велик")
        with self._lock:
            process = self.process
            if (
                process is None
                or (expected_process is not _UNSET_PROCESS and process is not expected_process)
                or process.poll() is not None
                or process.stdin is None
                or self.mode != "voice"
            ):
                return False
            process.stdin.write(line)
            process.stdin.flush()
        return True

    def stop(self) -> None:
        with self._lock:
            self._stop()

    def _stop(self) -> None:
        process = self.process
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        if process.poll() is None:
            try:
                process.wait(timeout=0.8)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        self.process = None
