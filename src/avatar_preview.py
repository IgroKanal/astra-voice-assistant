"""Launch the bundled, isolated Godot avatar preview without a command shell."""
from __future__ import annotations

import hmac
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading

from src.desktop_settings import AVATAR_PROFILES


GODOT_VERSION_PREFIX = "4.7.2."
GODOT_EXECUTABLE_NAME = "Godot_v4.7.2-stable_win64.exe"
PROJECT_DIRECTORY_NAME = "3d_avatar"
AVATAR_STATES = frozenset({"idle", "listening", "recognizing", "speaking", "error"})


class AvatarPreviewUnavailable(RuntimeError):
    """Raised when a portable 3D preview runtime is not present."""


class AvatarPreviewSession:
    """Keep one authenticated loopback channel for bounded avatar state updates."""

    def __init__(self, listener: socket.socket, process: subprocess.Popen, token: str, initial_state: str):
        self._listener = listener
        self.process = process
        self._token = token
        self._state = initial_state
        self._last_sent_state: str | None = None
        self._connection: socket.socket | None = None
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="astra-avatar-preview-ipc", daemon=True)
        self._thread.start()

    def poll(self):
        return self.process.poll()

    def set_state(self, state: str) -> None:
        if state not in AVATAR_STATES:
            raise ValueError("Неизвестное состояние 3D-персонажа")
        with self._lock:
            self._state = state

    def close(self) -> None:
        connection = self._connection
        if connection is not None:
            try:
                connection.sendall(b"CLOSE\n")
            except OSError:
                pass
        self._stopping.set()
        try:
            self._listener.close()
        except OSError:
            pass

    def _serve(self) -> None:
        connection = None
        try:
            self._listener.settimeout(0.2)
            while not self._stopping.is_set() and self.poll() is None:
                try:
                    connection, address = self._listener.accept()
                    if address[0] != "127.0.0.1":
                        connection.close()
                        connection = None
                        continue
                    connection.settimeout(1.0)
                    received = bytearray()
                    while b"\n" not in received and len(received) <= 128:
                        chunk = connection.recv(128)
                        if not chunk:
                            break
                        received.extend(chunk)
                    candidate = bytes(received).split(b"\n", 1)[0].decode("ascii", errors="ignore")
                    if not hmac.compare_digest(candidate, self._token):
                        connection.close()
                        connection = None
                        continue
                    self._connection = connection
                    connection.settimeout(0.2)
                    while not self._stopping.is_set() and self.poll() is None:
                        with self._lock:
                            state = self._state
                        if state != self._last_sent_state:
                            connection.sendall(("STATE:" + state + "\n").encode("ascii"))
                            self._last_sent_state = state
                        try:
                            if not connection.recv(1):
                                break
                        except socket.timeout:
                            pass
                        except OSError:
                            break
                    break
                except socket.timeout:
                    continue
                except OSError:
                    break
        finally:
            if connection is not None:
                try:
                    if not self._stopping.is_set() and self.poll() is None:
                        connection.sendall(b"CLOSE\n")
                except OSError:
                    pass
                connection.close()
                self._connection = None
            try:
                self._listener.close()
            except OSError:
                pass


def _resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()


def resolve_preview_files(resource_root: Path | None = None) -> tuple[Path, Path]:
    roots = [resource_root.resolve()] if resource_root else []
    if not resource_root and getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(_resource_root())
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        executable = root / "third_party" / "godot" / GODOT_EXECUTABLE_NAME
        project = root / "assets" / PROJECT_DIRECTORY_NAME
        if executable.is_file() and (project / "project.godot").is_file():
            return executable, project
    raise AvatarPreviewUnavailable("В переносимой сборке не найден runtime 3D-персонажа.")


def launch_avatar_preview(avatar_id: str, display_name: str, *, initial_state: str = "idle",
                          resource_root: Path | None = None, popen=None) -> AvatarPreviewSession:
    if avatar_id not in AVATAR_PROFILES:
        raise ValueError("Неизвестный профиль персонажа")
    if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 32:
        raise ValueError("Имя персонажа должно содержать от 1 до 32 символов")
    if any(ord(char) < 32 for char in display_name):
        raise ValueError("Имя персонажа содержит управляющие символы")
    if initial_state not in AVATAR_STATES:
        raise ValueError("Неизвестное состояние 3D-персонажа")
    executable, project = resolve_preview_files(resource_root)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    token = secrets.token_hex(32)
    command = [
        str(executable), "--path", str(project), "--", "--avatar=" + avatar_id,
        "--name=" + display_name.strip(), "--port=" + str(port), "--token=" + token,
    ]
    try:
        process = (popen or subprocess.Popen)(command, cwd=str(project), shell=False, close_fds=True,
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) |
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    except Exception:
        listener.close()
        raise
    return AvatarPreviewSession(listener, process, token, initial_state)
