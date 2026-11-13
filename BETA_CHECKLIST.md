# Astra v1.3 Beta checklist

## Automated checks

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

## Voice runtime

Run:

```powershell
python main.py
```

Check:

```text
открой YouTube
```

Expected: ignored.

```text
Астра
открой YouTube
```

Expected: `Слушаю.` then YouTube opens.

```text
Астра, открой YouTube
```

Expected: YouTube opens immediately.

```text
Астер, стоп
Астэр, стоп
Астры, стоп
```

Expected: each configured wake alias is accepted as an exact wake phrase.

```text
Астра, открой https://example.com/CaseSensitive?Token=AbC
Астра, открой сайт www.youtube.com/watch?v=dQw4w9WgXcQ
```

Expected: path, query names/values and the case-sensitive YouTube ID are preserved.

```text
Астра, стоп
```

Expected: assistant exits.

## Safety

Check:

```text
Астра, открой cmd
Астра, открой powershell
Астра, напиши whoami
Астра, нажми enter
```

Expected:

- cmd/powershell are not opened from whitelist;
- typing and Enter are blocked in terminal-like foreground windows.

## Local skills

Check:

```text
Астра, статус VPN
Астра, включи VPN
Астра, выключи VPN
Астра, какие окна открыты
Астра, активное окно
Астра, переключись на Firefox
Астра, открой буфер up
Астра, статус интер
```

Expected: local parser actions, not LLM-router.

## Daily workflow and bounded context

Check:

```text
включи рабочий режим
следующий трек
вернись обратно
Астра, включи рабочий режим
Астра, найди на ютубе Python 3.12 C++
Астра, включи музыку
локальную
Астра, пауза
Астра, следующий трек
Астра, открой Telegram
Астра, закрой его
Астра, переключись на Firefox
Астра, вернись обратно
```

Expected:

- the first three no-wake phrases are ignored and never reach the LLM-router;
- the configured work routine opens/focuses only its allowlisted targets;
- YouTube search preserves punctuation in the query;
- ambiguous music asks for local or Yandex Music;
- media keys do not type text or start a shell;
- `закрой его` works only for fresh bounded context;
- previous-window switching never sends Alt+F4.

## Native Yandex Music

Check:

```text
открой Яндекс Музыку
Астра, открой Яндекс Музыку
Астра, включи музыку
Яндекс музыку
Астра, переключись на Яндекс Музыку
Астра, закрой Яндекс Музыку
Астра, открой сайт Яндекс Музыки
```

Expected:

- the no-wake phrase is ignored before actions and LLM-router;
- direct and follow-up forms open the native client without a console window;
- focus finds the visible `Яндекс Музыка.exe` window;
- close targets only the allowlisted Yandex Music process;
- the explicit site form opens `https://music.yandex.ru`;
- if the client is missing, Astra reports failure instead of saying it opened.

## v1.3 media and local player

Check with Yandex Music playing:

```text
Астра, следующий трек
Астра, верни предыдущий трек
Астра, начни трек заново
Астра, останови музыку
Астра, выключи музыку
```

Expected:

- next moves one track forward;
- previous sends the bounded two-event sequence needed to leave the current
  track instead of only restarting it;
- restart sends one previous event and starts the current track again;
- stop does not close the player;
- shutdown stops playback and closes only allowlisted Yandex Music.

Check the local player:

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

- the player is resolved only from a fixed path/shortcut/protocol or the local
  `ASTRA_LOCAL_MEDIA_PLAYER_PATH` override;
- explicit local-player commands target only fixed media process aliases;
- recognized speech is never used as an executable path or process name;
- absence of a supported player produces an honest failure.

## v1.3 safe window state actions

Check:

```text
Астра, сверни окно
Астра, разверни окно на весь экран
Астра, верни обычный размер окна
Астра, верни на обычный размер
Астра, сверни Telegram
Астра, разверни Яндекс Музыку
Астра, восстанови локальный плеер
Астра, сверни все окна
```

Expected:

- active and named visible windows use WinAPI `ShowWindow` only;
- generic maximize/restore reuses a recently minimized window instead of acting
  on the unrelated window that Windows brought to the foreground;
- maximize is the normal Windows maximize-button state, not browser F11;
- restore returns from minimized/maximized state to normal size;
- named targets are used only for visible-window lookup and never for shell or
  process execution;
- `сверни все окна` still shows the desktop.

## Packaging

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_review_package.ps1
powershell -ExecutionPolicy Bypass -File .\tools\build_beta_package.ps1
```

Expected:

```text
C:\Projects\astra-v1.3-beta-review-package-r3.zip
C:\Projects\astra-v1.3-beta-release-r3.zip
```

Both scripts must finish with `Astra package validation passed`. Validation
must also compare packaged project files byte-for-byte with the current source
tree so a stale release ZIP cannot pass.
