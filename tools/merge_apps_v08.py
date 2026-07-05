from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APPS_PATH = ROOT / "config" / "apps.json"
EXAMPLE_PATH = ROOT / "config" / "apps.v0.8.example.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    if not APPS_PATH.exists():
        print(f"Не найден {APPS_PATH}")
        return 1
    if not EXAMPLE_PATH.exists():
        print(f"Не найден {EXAMPLE_PATH}")
        return 1

    current = load_json(APPS_PATH)
    example = load_json(EXAMPLE_PATH)

    current_apps = current.setdefault("apps", {})
    example_apps = example.get("apps", {})

    backup = APPS_PATH.with_suffix(f".backup-{datetime.now():%Y%m%d-%H%M%S}.json")
    backup.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")

    added = 0
    updated_aliases = 0

    for name, app_data in example_apps.items():
        if name not in current_apps:
            current_apps[name] = app_data
            added += 1
            continue

        current_aliases = set(current_apps[name].get("aliases", []))
        for alias in app_data.get("aliases", []):
            if alias not in current_aliases:
                current_apps[name].setdefault("aliases", []).append(alias)
                current_aliases.add(alias)
                updated_aliases += 1

    APPS_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Готово. Backup: {backup}")
    print(f"Добавлено приложений: {added}")
    print(f"Добавлено aliases: {updated_aliases}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
