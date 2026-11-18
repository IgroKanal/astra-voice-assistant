"""Capture deterministic, synthetic UI previews without microphone or network."""
from pathlib import Path
import os
import queue
import runpy
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "visual_previews"


class PreviewBridge:
    def __init__(self, _root):
        self.events = queue.Queue()
        self.running = False
        self.mode = "text"
        self.process = None

    def start(self, mode):
        self.mode = mode
        self.running = True

    def stop(self):
        self.running = False

    def emit(self, kind, text):
        self.events.put((kind, text))

    def send(self, _text):
        return None

    def prevent_restart(self):
        return None


def pump(window, seconds=1.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        window.update()
        time.sleep(0.02)


def capture(window, name):
    window.deiconify()
    window.lift()
    window.attributes("-topmost", True)
    window.focus_force()
    pump(window, 0.25)
    window.update_idletasks()
    x, y = window.winfo_rootx(), window.winfo_rooty()
    image = ImageGrab.grab((x, y, x + window.winfo_width(), y + window.winfo_height()), all_screens=True)
    image.save(OUTPUT / name)
    window.attributes("-topmost", False)


def main():
    OUTPUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="astra-visual-demo-") as temp, patch.dict(os.environ, {"LOCALAPPDATA": temp}):
        with patch("src.desktop_bridge.DesktopBridge", PreviewBridge):
            namespace = runpy.run_path(str(ROOT / "astra_desktop.pyw"))
            app_class = namespace["AstraDesktop"]
            window = tk.Tk()
            app = app_class(window)
            app.onboarding_available = False
            if app.onboarding_banner is not None:
                app.onboarding_banner.destroy()
                app.onboarding_banner = None
            window.geometry("1180x780+40+40")
            app.busy = False
            app.status.set("Текстовый режим · микрофон выключен")
            pump(window)
            capture(window, "main-window.png")

            studio = app.open_ai_settings()
            studio.geometry("960x780+100+60")
            tabs = next(child for child in studio.winfo_children() if isinstance(child, tk.ttk.Notebook)) if hasattr(tk, "ttk") else next(child for child in studio.winfo_children() if child.winfo_class() == "TNotebook")
            tabs.select(1)
            pump(window, 0.5)
            capture(studio, "character-studio.png")
            studio.tk.call(studio.protocol("WM_DELETE_WINDOW"))

            onboarding = app.open_onboarding()
            onboarding.geometry("860x650+120+50")
            pump(window, 0.5)
            capture(onboarding, "onboarding.png")
            onboarding.destroy()

            app.bridge.prevent_restart()
            app.bridge.stop()
            window.after_cancel(app.poll_timer)
            window.after_cancel(app.animation_timer)
            window.destroy()


if __name__ == "__main__":
    main()
