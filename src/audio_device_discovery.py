"""Read-only audio input discovery and stable, non-secret device identities."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import unicodedata
from typing import Any


_MAX_AUDIO_DEVICES = 512
_IDENTITY_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class AudioInputDevice:
    """A current PortAudio index paired with a stable metadata fingerprint."""

    index: int
    identity: str


def _normalize_label(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        value = str(value or "")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def audio_input_identity(name: Any, host_api_name: Any = "") -> str:
    """Hash stable device labels; never persist raw device names or indices."""
    clean_name = _normalize_label(name)
    if not clean_name:
        return ""
    clean_host = _normalize_label(host_api_name)
    payload = ("astra-audio-input-v1\0" + clean_name + "\0" + clean_host).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def discover_audio_inputs(pyaudio_module: Any | None = None) -> tuple[AudioInputDevice, ...]:
    """Enumerate input metadata without opening a recording stream.

    ``pyaudio_module`` is injectable so tests do not touch physical devices.
    Failures return an empty snapshot; callers then use the OS default input.
    """
    audio = None
    try:
        if pyaudio_module is None:
            from speech_recognition import Microphone

            pyaudio_module = Microphone.get_pyaudio()
        audio = pyaudio_module.PyAudio()
        count = max(0, min(int(audio.get_device_count()), _MAX_AUDIO_DEVICES))
    except Exception:
        if audio is not None:
            try:
                audio.terminate()
            except Exception:
                pass
        return ()

    devices: list[AudioInputDevice] = []
    try:
        for fallback_index in range(count):
            try:
                info = audio.get_device_info_by_index(fallback_index)
                if not isinstance(info, dict) or int(info.get("maxInputChannels", 0)) <= 0:
                    continue
                index = int(info.get("index", fallback_index))
                if not 0 <= index < _MAX_AUDIO_DEVICES:
                    continue
                host_api_name = ""
                host_api_index = info.get("hostApi")
                if host_api_index is not None:
                    try:
                        host_info = audio.get_host_api_info_by_index(int(host_api_index))
                        if isinstance(host_info, dict):
                            host_api_name = host_info.get("name", "")
                    except Exception:
                        pass
                identity = audio_input_identity(info.get("name", ""), host_api_name)
                if identity:
                    devices.append(AudioInputDevice(index=index, identity=identity))
            except (OSError, TypeError, ValueError, OverflowError):
                continue
    finally:
        try:
            audio.terminate()
        except Exception:
            pass
    return tuple(devices)


def resolve_audio_input_index(identity: str, devices: tuple[AudioInputDevice, ...]) -> int | None:
    """Resolve only a unique current match; never guess between identical devices."""
    if not isinstance(identity, str) or not _IDENTITY_RE.fullmatch(identity):
        return None
    matches = [device.index for device in devices if device.identity == identity]
    return matches[0] if len(matches) == 1 else None


def audio_input_identity_for_index(index: int | None, pyaudio_module: Any | None = None) -> str:
    """Capture a fingerprint for a user-selected index, if it is unambiguous."""
    if type(index) is not int or not 0 <= index < _MAX_AUDIO_DEVICES:
        return ""
    matches = [device.identity for device in discover_audio_inputs(pyaudio_module) if device.index == index]
    return matches[0] if len(matches) == 1 else ""
