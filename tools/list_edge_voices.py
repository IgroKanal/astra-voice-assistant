from __future__ import annotations

import subprocess
import sys


def main() -> int:
    command = ["edge-tts", "--list-voices"]
    if len(sys.argv) > 1:
        needle = sys.argv[1].lower()
    else:
        needle = "ru-RU".lower()

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(result.stderr.strip() or "edge-tts --list-voices failed")
        return result.returncode

    for line in result.stdout.splitlines():
        if needle in line.lower():
            print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
