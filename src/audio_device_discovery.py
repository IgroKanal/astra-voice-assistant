"""Read-only audio input discovery and stable, non-secret device identities."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import unicodedata
from typing import Any, Callable

from src.windows_audio_endpoint import (
    WindowsAudioEndpoint,
    discover_windows_capture_endpoints,
)


_MAX_AUDIO_DEVICES = 512
_IDENTITY_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class AudioInputDevice:
    """Current PortAudio index and legacy plus Core Audio identities."""

    index: int
    identity: str
    endpoint_identity: str = ""


@dataclass(frozen=True)
class AudioOutputDevice:
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


def audio_input_endpoint_identity(endpoint_id: Any, host_api_name: Any = "") -> str:
    """Hash an opaque Core Audio endpoint ID without storing its raw value."""
    if (
        not isinstance(endpoint_id, str)
        or not endpoint_id
        or len(endpoint_id) > 1024
        or any(ord(character) < 32 for character in endpoint_id)
    ):
        return ""
    clean_host = _normalize_label(host_api_name)
    payload = (
        "astra-audio-input-endpoint-v1\0" + endpoint_id + "\0" + clean_host
    )
    try:
        encoded = payload.encode("utf-8")
    except UnicodeEncodeError:
        return ""
    return hashlib.sha256(encoded).hexdigest()


def audio_output_identity(name: Any, host_api_name: Any = "") -> str:
    """Hash output labels separately from input labels; never persist raw names."""
    clean_name = _normalize_label(name)
    if not clean_name:
        return ""
    clean_host = _normalize_label(host_api_name)
    payload = ("astra-audio-output-v1\0" + clean_name + "\0" + clean_host).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def discover_audio_inputs(
    pyaudio_module: Any | None = None,
    *,
    strict: bool = False,
    endpoint_discovery: Callable[[], object] | None = None,
) -> tuple[AudioInputDevice, ...]:
    """Enumerate input metadata without opening a recording stream.

    ``pyaudio_module`` is injectable so tests do not touch physical devices.
    Failures return an empty snapshot by default; callers then use the OS
    default input. Inventory callers may request strict errors to distinguish
    an unavailable backend from a computer with no input endpoints. On Windows,
    Core Audio endpoint IDs strengthen identity matching; the older hashed
    label identity remains as a unique-match fallback for existing profiles and
    when Core Audio metadata is unavailable.
    """
    if endpoint_discovery is None:
        endpoint_discovery = discover_windows_capture_endpoints
    endpoint_by_name: dict[str, list[str]] = {}
    try:
        endpoint_records = endpoint_discovery()
        if isinstance(endpoint_records, (tuple, list)) and len(endpoint_records) <= _MAX_AUDIO_DEVICES:
            for endpoint in endpoint_records:
                if not isinstance(endpoint, WindowsAudioEndpoint):
                    continue
                if (
                    not isinstance(endpoint.endpoint_id, str)
                    or not isinstance(endpoint.friendly_name, str)
                    or not endpoint.endpoint_id
                    or len(endpoint.endpoint_id) > 1024
                    or not endpoint.friendly_name
                    or len(endpoint.friendly_name) > 512
                    or any(ord(character) < 32 for character in endpoint.endpoint_id)
                    or any(ord(character) < 32 for character in endpoint.friendly_name)
                ):
                    continue
                key = _normalize_label(endpoint.friendly_name)
                endpoint_by_name.setdefault(key, []).append(endpoint.endpoint_id)
    except Exception:
        # Stable endpoint IDs are an optional enhancement. If Core Audio is
        # unavailable, retain the existing conservative fingerprint path.
        endpoint_by_name = {}

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
        if strict:
            raise
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
                name = info.get("name", "")
                identity = audio_input_identity(name, host_api_name)
                matching_endpoints = endpoint_by_name.get(_normalize_label(name), ())
                endpoint_identity = (
                    audio_input_endpoint_identity(matching_endpoints[0], host_api_name)
                    if len(matching_endpoints) == 1
                    else ""
                )
                if identity:
                    devices.append(
                        AudioInputDevice(
                            index=index,
                            identity=identity,
                            endpoint_identity=endpoint_identity,
                        )
                    )
            except (OSError, TypeError, ValueError, OverflowError):
                continue
    finally:
        try:
            audio.terminate()
        except Exception:
            pass
    return tuple(devices)


def discover_audio_outputs(
    pyaudio_module: Any | None = None, *, strict: bool = False
) -> tuple[AudioOutputDevice, ...]:
    """Enumerate output metadata without opening a playback stream."""
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
        if strict:
            raise
        return ()

    devices: list[AudioOutputDevice] = []
    try:
        for fallback_index in range(count):
            try:
                info = audio.get_device_info_by_index(fallback_index)
                if not isinstance(info, dict) or int(info.get("maxOutputChannels", 0)) <= 0:
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
                identity = audio_output_identity(info.get("name", ""), host_api_name)
                if identity:
                    devices.append(AudioOutputDevice(index=index, identity=identity))
            except (OSError, TypeError, ValueError, OverflowError):
                continue
    finally:
        try:
            audio.terminate()
        except Exception:
            pass
    return tuple(devices)


def resolve_audio_input_index(
    identity: str,
    devices: tuple[AudioInputDevice, ...],
    *,
    endpoint_identity: str = "",
) -> int | None:
    """Prefer a unique Core Audio ID, then a unique legacy label match."""
    if endpoint_identity:
        if not isinstance(endpoint_identity, str) or not _IDENTITY_RE.fullmatch(endpoint_identity):
            return None
        endpoint_matches = [
            device.index
            for device in devices
            if device.endpoint_identity == endpoint_identity
        ]
        if endpoint_matches:
            return endpoint_matches[0] if len(endpoint_matches) == 1 else None
    if not isinstance(identity, str) or not _IDENTITY_RE.fullmatch(identity):
        return None
    matches = [device.index for device in devices if device.identity == identity]
    return matches[0] if len(matches) == 1 else None


def audio_input_identities_for_index(
    index: int | None, pyaudio_module: Any | None = None
) -> tuple[str, str]:
    """Capture label and optional endpoint hashes in one metadata scan."""
    if type(index) is not int or not 0 <= index < _MAX_AUDIO_DEVICES:
        return "", ""
    matches = [
        device
        for device in discover_audio_inputs(pyaudio_module)
        if device.index == index
    ]
    if len(matches) != 1:
        return "", ""
    return matches[0].identity, matches[0].endpoint_identity


def audio_input_identity_for_index(
    index: int | None, pyaudio_module: Any | None = None
) -> str:
    """Capture a label fingerprint for a user-selected index."""
    return audio_input_identities_for_index(index, pyaudio_module)[0]


def audio_input_endpoint_identity_for_index(
    index: int | None, pyaudio_module: Any | None = None
) -> str:
    """Capture the optional Core Audio identity for a unique selected endpoint."""
    return audio_input_identities_for_index(index, pyaudio_module)[1]
