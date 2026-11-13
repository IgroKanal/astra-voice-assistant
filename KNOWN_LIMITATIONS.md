# Astra v1.3 Beta known limitations

This beta is intentionally conservative.

## Voice/STT

- Wake detection uses the current STT flow, not a dedicated offline wake-word engine.
- The microphone is still sampled so Astra can hear the wake phrase.
- STT may occasionally recognize `Астра` as `астер`, `астэр` or `астры`; these variants are included as wake aliases.
- The exact alias `астры` may still produce a false wake in natural speech; substring matches such as `Австрия` are not accepted.
- Very long or noisy phrases may be cut off by STT.

## TTS

- First-time cache generation for one prewarm phrase can still take several seconds.
- The current beta limits synchronous prewarm to one attempted generation with an 8-second timeout by default.
- Run beta environment scripts and warm up common phrases before hidden/autostart testing.

## Safety

- `cmd.exe` and PowerShell are not whitelisted as user-openable apps.
- Fixed `cmd /c start` wrappers may still exist in `config/apps.json` for protocol/browser launching. They do not use user-provided shell text.
- Desktop development replaces process termination with bounded, exact-process WM_CLOSE requests. Pending save dialogs require user interaction; no force-kill fallback is used.

## Window/app control

- Active-window Alt+F4 closing is disabled.
- Targeted typing into a named app is disabled.
- Typing only works in the currently active safe foreground context.
- Terminal-like foreground windows block text input and Enter.
- Context is deliberately short-lived and only remembers the last successful
  app, site, folder or explicit window focus. It is not conversational memory.
- `закрой его` requests normal close of an exact allowlisted process window.
  The application may keep running in its tray or display a save dialog.
- Safe routines cannot type, press keys, control VPN/windows, call the LLM or
  run shell commands. They stop at eight allowlisted open steps.
- Generic media controls still depend on the active Windows media session when
  no known player window is active.
- Previous-track uses two bounded Previous Track events because many players use
  the first event to restart the current track. A player with unusual semantics
  may still behave differently near the beginning of a track.
- Explicit local-player targeting supports a fixed set of common process names
  and fixed window-title aliases. Groove Music must expose its registered
  `mswindowsmusic:` protocol and a visible window for targeted playback.
- A PLAY command cannot choose a track when the local library/queue is empty.
  Other players may require `ASTRA_LOCAL_MEDIA_PLAYER_PATH` for opening and may
  still ignore Windows `WM_APPCOMMAND` media messages.
- Astra does not read the exact current play/pause state, track position or
  metadata from Windows media sessions.
- Yandex Music integration opens, closes or focuses the desktop client, but it
  does not select a playlist/track or read playback state from the app UI.
- Non-standard Yandex Music installations may require the local
  `ASTRA_YANDEX_MUSIC_PATH` override.
- Minimize/maximize/restore works only for visible top-level windows that can be
  found by process/title aliases. Generic state continuity expires after 45
  seconds and does not manipulate hidden child windows.
- `разверни окно на весь экран` is normal Windows maximization, not application
  fullscreen or browser F11.
- `вернись обратно` is available only after Astra successfully focused another
  window during the current process lifetime.

## Not included in v1.3 Beta

- GUI/tray app.
- Real Windows service.
- Browser extension.
- pywinauto UI automation.
- Telegram contact/message automation.
- Shutdown/reboot/delete commands.
