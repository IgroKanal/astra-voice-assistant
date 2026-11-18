"""Check primary controls at every supported in-app UI scale."""
import os
from pathlib import Path
import runpy
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
AstraDesktop = runpy.run_path(str(ROOT / "astra_desktop.pyw"))["AstraDesktop"]


class VisualLayoutTests(unittest.TestCase):
    def test_primary_controls_fit_scaled_minimum_windows(self):
        from src.desktop_settings import AIProfile, DesktopSettings
        for scale in (100, 125, 150):
            with self.subTest(scale=scale), tempfile.TemporaryDirectory(prefix="astra-scale-") as temp:
                with patch.dict(os.environ, {"LOCALAPPDATA": temp}):
                    DesktopSettings().save(AIProfile(provider="disabled", ui_scale=scale, reduced_motion=True))
                    window = tk.Tk()
                    app = AstraDesktop(window)
                    try:
                        window.geometry(f"{840 * scale // 100}x{680 * scale // 100}")
                        deadline = time.monotonic() + 15
                        while app.busy and time.monotonic() < deadline:
                            window.update()
                            time.sleep(0.02)
                        window.update()
                        widgets = list(window.winfo_children())
                        controls = []
                        while widgets:
                            item = widgets.pop()
                            widgets.extend(item.winfo_children())
                            if isinstance(item, (tk.Button, tk.Entry)):
                                controls.append(item)
                        for item in controls:
                            label = item.cget("text") if isinstance(item, tk.Button) else "entry"
                            self.assertTrue(item.winfo_ismapped(), label)
                            x = item.winfo_rootx() - window.winfo_rootx()
                            y = item.winfo_rooty() - window.winfo_rooty()
                            self.assertGreaterEqual(x, 0, label)
                            self.assertGreaterEqual(y, 0, label)
                            self.assertLessEqual(x + item.winfo_width(), window.winfo_width(), label)
                            self.assertLessEqual(y + item.winfo_height(), window.winfo_height(), label)
                    finally:
                        app.bridge.prevent_restart()
                        app.bridge.stop()
                        window.after_cancel(app.poll_timer)
                        window.after_cancel(app.animation_timer)
                        window.destroy()


if __name__ == "__main__":
    unittest.main()
