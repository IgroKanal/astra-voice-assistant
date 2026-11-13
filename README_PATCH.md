# Astra v1.3 R3 patch

Version: **v1.3 — Native Media Control & Safe App Actions (Beta)**

Base commit: `6b4eba3` (`Add v1.2 native Yandex Music integration`).

## Release goal

Stabilize voice recognition, Groove Music playback and safe window-state
continuity without weakening wake-only, application whitelist or terminal guards.

## Install patch

Extract the patch into `C:\Projects\astra-voice-assistant`, replacing files,
then run:

```powershell
cd C:\Projects\astra-voice-assistant
.\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File .\tools\apply_v13_beta_env.ps1
```

The environment helper changes only known beta settings. It does not modify API
keys, `ASTRA_YANDEX_MUSIC_PATH` or `ASTRA_LOCAL_MEDIA_PLAYER_PATH`.

For a non-standard local player, set its executable in the local `.env`:

```text
ASTRA_LOCAL_MEDIA_PLAYER_PATH=C:\Path\To\Player.exe
```

Do not put that path into `config/apps.json` or a voice command.

## Automated verification

```powershell
python -m compileall main.py src tools
python tools\smoke_test_v09_parser.py
python tools\smoke_test_v10_parser.py
python tools\smoke_test_v11_wake_runtime.py
python tools\smoke_test_v100_beta.py
python tools\smoke_test_v101_beta.py
python tools\smoke_test_v11_daily_workflow.py
python tools\smoke_test_v12_native_music.py
python tools\smoke_test_v13_media_control.py
python tools\smoke_test_v13_window_actions.py
python tools\validate_v10_config.py
python tools\validate_v11_config.py
python tools\validate_v12_config.py
python tools\validate_v13_config.py
python tools\astra_doctor.py
```

## Manual Windows verification

### Media

```text
выключи музыку
Астра, следующий трек
Астра, верни предыдущий трек
Астра, начни трек заново
Астра, останови музыку
Астра, выключи музыку
```

Expected:

- the no-wake command is ignored before actions and LLM routing;
- previous moves away from the current track using two bounded events;
- restart starts the current track again using one event;
- stop leaves the player open;
- shutdown closes only allowlisted Yandex Music.

### Local player

```text
Астра, открой локальный плеер
Астра, включи локальную музыку
Астра, включи локальный плеер
Астра, следующий трек в локальном плеере
Астра, предыдущий трек в локальном плеере
Астра, поставь локальный плеер на паузу
Астра, останови локальный плеер
```

Expected:

- Windows 10 Groove Music is preferred through the fixed `mswindowsmusic:` protocol;
- `включи...` opens the player and sends a fixed PLAY app-command;
- explicit commands target only fixed local-player process/title aliases;
- unsupported players return an honest failure;
- no speech text is used as an executable or process name.

### Windows

```text
Астра, сверни окно
Астра, разверни окно на весь экран
Астра, верни обычный размер окна
Астра, верни на обычный размер
Астра, сверни Telegram
Астра, разверни Яндекс Музыку
Астра, восстанови локальный плеер
```

Expected:

- commands use normal Windows minimize/maximize/restore states;
- maximize/restore after a minimize reuses the same recent window for 45 seconds;
- targeted commands affect an existing visible window only;
- browser F11 is not used by the maximize commands;
- no Alt+F4, shell or arbitrary keyboard input is introduced.

### Existing safety

```text
Астра, открой сайт Яндекс Музыки
Астра, открой cmd
Астра, открой powershell
Астра, открой Windows Terminal
```

The website remains a URL action. Terminal applications remain rejected and the
terminal typing/Enter guards remain active.

## Commit gate

Do not commit until automated checks, manual Windows verification, package
validation and independent review all pass. Suggested commit message:

```text
Add v1.3 native media control and safe app actions
```
