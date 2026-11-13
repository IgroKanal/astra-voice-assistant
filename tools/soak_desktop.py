"""Real-runtime desktop responsiveness soak; no microphone or cloud calls."""
import argparse
import os
from pathlib import Path
import runpy
import sys
import time
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--runtime-root", type=Path)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 28800:
        parser.error("Choose 30–28800 seconds")
    os.environ.update(ASTRA_IGNORE_DESKTOP_SETTINGS="1", LLM_ENABLED="false", TTS_ENABLED="false", VPN_ENABLED="false")
    app_type = runpy.run_path(str(ROOT / "astra_desktop.pyw"))["AstraDesktop"]
    if args.runtime_root is not None:
        runtime_root = args.runtime_root.resolve(strict=True)
        if not (runtime_root / "runtime" / "AstraRuntime" / "AstraRuntime.exe").is_file():
            parser.error("Packaged runtime is missing")
        app_type.__init__.__globals__["ROOT"] = runtime_root
    root = tk.Tk()
    root.withdraw()
    app = app_type(root)
    response_count = [0]
    append = app.append
    def observed_append(who, text):
        if who == "Астра" and text.startswith("Сейчас"):
            response_count[0] += 1
        append(who, text)
    app.append = observed_append
    start = time.monotonic()
    previous = start
    last_send = start - 15
    maximum_gap = 0.0
    ticks = 0
    sent = 0
    last_report = start
    print(f"DESKTOP_SOAK_START: seconds={args.seconds} runtime={args.runtime_root or ROOT}", flush=True)
    try:
        while time.monotonic() - start < args.seconds:
            root.update()
            now = time.monotonic()
            maximum_gap = max(maximum_gap, now - previous)
            assert maximum_gap < 3, f"UI event loop stalled: {maximum_gap:.2f}s"
            previous = now
            ticks += 1
            if not app.busy and app.bridge.running and now - last_send >= 15:
                app.fill("Астра, сколько времени")
                app.send()
                sent += 1
                last_send = now
            if now - last_report >= 60:
                print(f"DESKTOP_SOAK_PROGRESS: elapsed={int(now-start)}s commands={sent} responses={response_count[0]} updates={ticks} maximum_gap={maximum_gap:.3f}s", flush=True)
                last_report = now
            time.sleep(0.02)
        responses = response_count[0]
        assert responses >= 2, f"Missing local responses: {responses}"
        assert responses >= sent - 1, f"Commands without replies: sent={sent} responses={responses}"
        assert maximum_gap < 3, f"UI event loop stalled: {maximum_gap:.2f}s"
        assert ticks > args.seconds * 10, f"Too few UI updates: {ticks}"
        print(f"DESKTOP_SOAK_PASS: duration={args.seconds}s commands={sent} responses={responses} updates={ticks} maximum_gap={maximum_gap:.3f}s", flush=True)
    finally:
        app.bridge.prevent_restart()
        app.bridge.stop()
        for timer in (app.poll_timer, app.animation_timer):
            root.after_cancel(timer)
        root.destroy()
        assert not app.bridge.running


if __name__ == "__main__":
    main()
