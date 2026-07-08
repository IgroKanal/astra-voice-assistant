# Astra v1.0 Beta checklist

## Automated checks

```powershell
python -m compileall main.py src tools
python tools\smoke_test_v09_parser.py
python tools\smoke_test_v10_parser.py
python tools\smoke_test_v11_wake_runtime.py
python tools\smoke_test_v100_beta.py
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
C:\Projects\astra-v1.0-beta-review-package.zip
C:\Projects\astra-v1.0-beta-release.zip
```
