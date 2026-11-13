"""Headless validation for the optional Godot 3D avatar renderer spike."""
from __future__ import annotations

import argparse
import hmac
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "prototypes" / "3d_avatar"
AVATAR_IDS = ("female_miku", "male_ren", "female_saya", "male_kai")
AVATAR_STATES = ("idle", "listening", "recognizing", "speaking", "error")


def run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 or "ERROR:" in output:
        raise RuntimeError(f"Godot validation failed (exit={result.returncode}):\n{output[-6000:]}")
    return output


def validate_runtime_ipc(godot: Path, project: Path = PROJECT) -> None:
    token = secrets.token_hex(32)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(12)
        port = listener.getsockname()[1]
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen([
                str(godot), "--headless", "--path", str(project), "--quit-after", "120",
                "--", "--avatar=female_miku", "--name=Мику", "--port=" + str(port), "--token=" + token,
            ], stdout=log, stderr=subprocess.STDOUT)
            try:
                connection, address = listener.accept()
                with connection:
                    if address[0] != "127.0.0.1":
                        raise RuntimeError("3D renderer connected from a non-loopback address")
                    connection.settimeout(3)
                    received = bytearray()
                    while b"\n" not in received and len(received) <= 128:
                        chunk = connection.recv(128)
                        if not chunk:
                            break
                        received.extend(chunk)
                    candidate = bytes(received).split(b"\n", 1)[0].decode("ascii", errors="ignore")
                    if not hmac.compare_digest(candidate, token):
                        raise RuntimeError("3D renderer did not authenticate its state channel")
                    connection.sendall(b"STATE:speaking\nCLOSE\n")
                    code = process.wait(timeout=10)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3)
            log.seek(0)
            output = log.read().decode("utf-8", errors="replace")
            if code != 0 or "ASTRA_AVATAR_STATE:speaking" not in output:
                raise RuntimeError("Godot avatar did not apply loopback state:\n" + output[-3000:])
    print("AVATAR_LOOPBACK_STATE_PASS: authenticated speaking update and graceful close")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--godot", required=True, type=Path, help="Godot 4.7.2 stable executable")
    args = parser.parse_args()
    avatar_source = (PROJECT / "scripts" / "avatar_viewer.gd").read_text(encoding="utf-8")
    if (avatar_source.count('"gender": "female"') != 2 or
            avatar_source.count('"gender": "male"') != 2 or
            '"shoulder_width"' not in avatar_source or '"eye_scale"' not in avatar_source or
            "blink_weight := clampf" not in avatar_source or "astra_eye_base_y" not in avatar_source):
        raise ValueError("Expected four gender-profiled procedural models and bounded eye-blink animation")
    print("AVATAR_GENDER_VARIANTS_PASS: two male and two female silhouettes, eye proportions and blink animation")
    godot = args.godot.resolve(strict=True)
    if not godot.is_file():
        raise ValueError("--godot must point to the Godot executable")

    version = run([str(godot), "--headless", "--version"]).strip()
    if not version.startswith("4.7.2."):
        raise ValueError("Expected Godot 4.7.2 stable, found: " + version)
    run([str(godot), "--headless", "--editor", "--path", str(PROJECT), "--quit"])

    for avatar_id in (*AVATAR_IDS, "not_a_profile"):
        output = run([
            str(godot), "--headless", "--path", str(PROJECT), "--quit-after", "2",
            "--", "--avatar=" + avatar_id,
        ])
        expected = avatar_id if avatar_id in AVATAR_IDS else "female_saya"
        if "ASTRA_AVATAR_READY:" + expected + ":idle" not in output:
            raise RuntimeError("Avatar selection/fallback failed for " + avatar_id + ":\n" + output[-3000:])
        print("AVATAR_RUNTIME_PASS: " + avatar_id + " -> " + expected)

    for state in AVATAR_STATES:
        output = run([
            str(godot), "--headless", "--path", str(PROJECT), "--quit-after", "2",
            "--", "--avatar=female_miku", "--state=" + state,
        ])
        if "ASTRA_AVATAR_READY:female_miku:" + state not in output:
            raise RuntimeError("Avatar state selection failed for " + state + ":\n" + output[-3000:])
        print("AVATAR_STATE_PASS: " + state)

    output = run([
        str(godot), "--headless", "--path", str(PROJECT), "--quit-after", "2",
        "--", "--avatar=male_ren", "--name=Рэн-2",
    ])
    if "ASTRA_AVATAR_READY:male_ren:idle" not in output or "ASTRA_AVATAR_NAME:Рэн-2" not in output:
        raise RuntimeError("Custom avatar name was not reflected in the 3D preview:\n" + output[-3000:])
    print("AVATAR_CUSTOM_NAME_PASS: Рэн-2")

    output = run([
        str(godot), "--headless", "--path", str(PROJECT), "--quit-after", "2",
        "--", "--state=unknown",
    ])
    if "ASTRA_AVATAR_READY:female_saya:idle" not in output:
        raise RuntimeError("Unknown avatar state must fall back to idle:\n" + output[-3000:])
    print("AVATAR_STATE_FALLBACK_PASS: unknown -> idle")
    validate_runtime_ipc(godot)
    print("AVATAR_PROJECT_IMPORT_PASS: " + version)


if __name__ == "__main__":
    main()
