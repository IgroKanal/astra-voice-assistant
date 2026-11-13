"""Packaged console worker, owned and hidden by the desktop process."""
import os
import sys

for stream in (sys.stdin, sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# Frozen installations have no edge-tts console scripts. Keep voice offline
# with the installed Windows SAPI voice until a bundled edge adapter exists.
os.environ.setdefault("TTS_ENGINE", "sapi")
os.environ.setdefault("TTS_DEBUG_VOICES", "false")

from main import main

if __name__ == "__main__":
    sys.exit(main())
