# Astra v1.2 — Native Music App Integration & Workflow Reliability (Beta)

## Release goal

Open the installed Yandex Music desktop client for normal music commands while
keeping explicit website commands, wake-only isolation and the existing safety
gate unchanged.

## Added

- Allowlisted `яндекс музыка` application with narrow Russian/English aliases.
- Native executable resolution through `ASTRA_YANDEX_MUSIC_PATH`, standard
  `%LOCALAPPDATA%`/Program Files locations and the fixed StartApps ID
  `ru.yandex.desktop.music` when its Start Menu shortcut exists.
- Window aliases for focusing the visible Yandex Music Electron window.
- Optional `ASTRA_YANDEX_MUSIC_PATH` in `.env.example` for non-standard installs.
- `smoke_test_v12_native_music.py` and `validate_v12_config.py`.

## Behavior

- `Астра, открой Яндекс Музыку` opens the native client.
- The Yandex choice after `Астра, включи музыку` opens the native client.
- `Астра, закрой Яндекс Музыку` closes only its allowlisted process using the
  existing `taskkill /F` behavior.
- `Астра, переключись на Яндекс Музыку` focuses its existing window.
- `Астра, открой сайт Яндекс Музыки` opens `https://music.yandex.ru`.
- If the client cannot be resolved, Astra reports failure and does not claim
  that it opened successfully.

## Safety

- Recognized speech is never inserted into the launch command.
- No PowerShell/cmd wrapper, arbitrary shell execution or new LLM action was
  added.
- The generic alias `музыка` is not added to the app whitelist.
- `cmd`, PowerShell, pwsh and Windows Terminal remain outside the whitelist.
- No-wake music commands remain blocked before actions and LLM-router calls.
- Terminal typing/Enter guards and the v0.10.8.1 safety gate are unchanged.

## Deferred

- Selecting playlists, albums or tracks inside the app.
- Reading playback state or metadata from Yandex Music.
- Application-specific volume control and UI automation.
