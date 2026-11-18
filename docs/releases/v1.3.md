# Astra v1.3 — Native Media Control & Safe App Actions (Beta)

## Release goal

Expand practical media and window control while preserving wake-only execution,
fixed application allowlists, terminal guards and package safety.

## Added

- dedicated `MediaController` for fixed media actions;
- `Астра, выключи музыку` and `Астра, закрой музыку`;
- bounded shutdown sequence: media stop, then close only allowlisted Yandex Music;
- deterministic previous-track command using two bounded previous events;
- separate `начни трек заново` command using one previous event;
- explicit local-player commands through fixed process allowlists;
- safe local-player resolver with an optional
  `ASTRA_LOCAL_MEDIA_PLAYER_PATH` override;
- opening the local player after the `включи музыку → локальную` follow-up;
- active-window minimize, maximize and restore;
- targeted visible-window commands such as `сверни Telegram`,
  `разверни Яндекс Музыку` and `восстанови локальный плеер`;
- additional volume aliases: `прибавь громкость`, `убавь громкость`;
- dedicated media, local-player and window-action smoke tests.

## R3 reliability update

- Groove Music (`Музыка Groove`, process `Music.UI.exe`) is now the preferred
  Windows 10 local player through the fixed `mswindowsmusic:` protocol; legacy
  Windows Media Player remains a fallback.
- `включи музыку → локальную`, `включи локальную музыку` and
  `включи локальный плеер` now open the allowlisted local player and send the
  fixed Windows `PLAY` app-command.
- targeted media control can find UWP/local-player windows by fixed title aliases
  such as `Музыка Groove`, without using recognized speech as a process name.
- common STT corruptions observed in real logs (`вока`, `лока`,
  `вокальном пуэре`) are repaired only beside exact allowlisted media commands.
- `верни на обычный размер` is parsed locally instead of reaching the LLM.
- generic minimize/maximize/restore keeps a 45-second bounded reference to the
  last manipulated window, so maximizing after minimizing does not affect the
  newly foregrounded unrelated window.
- explicit targeted media commands no longer fall back to an unrelated global
  media session when the requested player window is missing.

## Previous-track behavior

Many Windows media applications interpret a single Previous Track event as
"restart the current track" after playback has advanced. Astra now separates:

- `предыдущий трек` / `верни предыдущий трек` — two fixed Previous Track events;
- `начни трек заново` / `перезапусти трек` — one fixed Previous Track event.

The sequence is bounded to at most two events. No loop or user-controlled repeat
count is available.

## Local-player safety

Astra may target only fixed, common local-player process names. Recognized speech
is never inserted into a process name, executable path, WinAPI command or shell
argument. A non-standard player can be configured locally through
`ASTRA_LOCAL_MEDIA_PLAYER_PATH`; the value is read from `.env`, not from speech.

## Window-state safety

Minimize, maximize and restore use WinAPI `ShowWindow` on an already visible
window. Target text is used only for window lookup. These actions do not execute
programs, type text, press Enter, invoke PowerShell or use Alt+F4.

`разверни окно на весь экран` means the normal Windows maximize-button state.
It is separate from browser F11 fullscreen.

## Preserved

- wake-only enforcement before actions and LLM routing;
- explicit Yandex Music website routing;
- native app whitelist resolution;
- terminal typing and Enter guards;
- no arbitrary shell, PowerShell or command execution;
- existing music-source follow-up for generic `включи музыку`;
- bounded recent-action context and previous-window switching.

## Deferred

- reading exact playback state from Windows media sessions;
- deterministic state-aware play versus pause for every player;
- per-application volume and exact volume percentages;
- playlist, album and track selection inside Yandex Music;
- automatic discovery of every third-party media player.
