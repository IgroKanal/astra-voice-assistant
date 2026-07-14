# Astra v1.2 Beta known limitations

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
- `taskkill /F` is still used for some app closing and may lose unsaved data.

## Window/app control

- Active-window Alt+F4 closing is disabled.
- Targeted typing into a named app is disabled.
- Typing only works in the currently active safe foreground context.
- Terminal-like foreground windows block text input and Enter.
- Context is deliberately short-lived and only remembers the last successful
  app, site, folder or explicit window focus. It is not conversational memory.
- `закрой его` can close a whitelisted app with the existing `taskkill /F`
  behavior, so unsaved data can still be lost.
- Safe routines cannot type, press keys, control VPN/windows, call the LLM or
  run shell commands. They stop at eight allowlisted open steps.
- Media controls use global Windows media keys; the active media application
  decides whether it handles them.
- Yandex Music integration opens, closes or focuses the desktop client, but it
  does not select a playlist/track or read playback state from the app UI.
- Non-standard Yandex Music installations may require the local
  `ASTRA_YANDEX_MUSIC_PATH` override.
- `вернись обратно` is available only after Astra successfully focused another
  window during the current process lifetime.

## Not included in v1.2 Beta

- GUI/tray app.
- Real Windows service.
- Browser extension.
- pywinauto UI automation.
- Telegram contact/message automation.
- Shutdown/reboot/delete commands.
