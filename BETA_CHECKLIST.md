# Astra v1.2 Beta checklist

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
python tools\validate_v10_config.py
python tools\validate_v11_config.py
python tools\validate_v12_config.py
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

## Packaging

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_review_package.ps1
powershell -ExecutionPolicy Bypass -File .\tools\build_beta_package.ps1
```

Expected:

```text
C:\Projects\astra-v1.2-beta-review-package.zip
C:\Projects\astra-v1.2-beta-release.zip
```

Both scripts must finish with `Astra package validation passed`. Validation
must also compare packaged project files byte-for-byte with the current source
tree so a stale release ZIP cannot pass.
