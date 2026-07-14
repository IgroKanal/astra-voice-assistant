# Astra v1.0.1 Beta checklist

## Automated checks

```powershell
python -m compileall main.py src tools
python tools\smoke_test_v09_parser.py
python tools\smoke_test_v10_parser.py
python tools\smoke_test_v11_wake_runtime.py
python tools\smoke_test_v100_beta.py
python tools\smoke_test_v101_beta.py
python tools\validate_v10_config.py
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

## Packaging

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_review_package.ps1
powershell -ExecutionPolicy Bypass -File .\tools\build_beta_package.ps1
```

Expected:

```text
C:\Projects\astra-v1.0.1-beta-review-package.zip
C:\Projects\astra-v1.0.1-beta-release.zip
```

Both scripts must finish with `Astra package validation passed`.
