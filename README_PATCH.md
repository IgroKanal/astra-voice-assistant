# Astra v1.2 patch

Version: **v1.2 — Native Music App Integration & Workflow Reliability (Beta)**

Base commit: `1f6bfc3` (`Add v1.1 safe daily workflow and bounded context`).

## Confirmed fix

Normal Yandex Music commands now use the installed native Windows client.
The website remains available only through an explicit site/URL request. The
resolver does not hardcode a user profile path and gives an honest failure if
the application cannot be found.

## Install patch

The command automatically selects the newest v1.2 patch ZIP from Downloads:

```powershell
$ProjectDir = "C:\Projects\astra-voice-assistant"
$DownloadsDir = Join-Path $env:USERPROFILE "Downloads"
$PatchFile = Get-ChildItem -Path (Join-Path $DownloadsDir "astra-v1.2-patch*.zip") -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
$PatchDir = Join-Path $env:TEMP "astra-v1.2-patch"

if ($null -eq $PatchFile) {
    throw "astra-v1.2-patch*.zip не найден в $DownloadsDir"
}
$PatchZip = $PatchFile.FullName

if (Test-Path $PatchDir) {
    Remove-Item $PatchDir -Recurse -Force
}

Expand-Archive -LiteralPath $PatchZip -DestinationPath $PatchDir -Force
Get-ChildItem -LiteralPath $PatchDir -Force |
    Copy-Item -Destination $ProjectDir -Recurse -Force

Set-Location $ProjectDir
.\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File .\tools\apply_v12_beta_env.ps1
```

For a non-standard installation only, set a local path in `.env`:

```text
ASTRA_YANDEX_MUSIC_PATH=C:\Path\To\Яндекс Музыка.exe
```

The environment helper preserves this value and never changes API keys.

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
python tools\validate_v10_config.py
python tools\validate_v11_config.py
python tools\validate_v12_config.py
python tools\astra_doctor.py
```

## Manual Windows verification

Run `python main.py`, then check:

```text
открой Яндекс Музыку
Астра, открой Яндекс Музыку
Астра, включи музыку
Яндекс музыку
Астра, переключись на Яндекс Музыку
Астра, закрой Яндекс Музыку
Астра, открой сайт Яндекс Музыки
Астра, открой cmd
Астра, открой powershell
```

Expected:

- the first no-wake command is ignored and does not reach LLM-router;
- direct and follow-up commands open the desktop client without a console;
- focus targets the existing Yandex Music window;
- close targets only `Яндекс Музыка.exe` and may lose unsaved app state because
  the existing close implementation uses `taskkill /F`;
- the explicit site command opens `https://music.yandex.ru`;
- cmd and PowerShell remain rejected.

Also repeat the complete wake-only, terminal typing/Enter, VPN, window, URL and
TTS checklist from `BETA_CHECKLIST.md`.

## Build and validate review package

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_review_package.ps1
python .\tools\validate_package.py C:\Projects\astra-v1.2-beta-review-package.zip `
    --source-root C:\Projects\astra-voice-assistant
```

Expected archive: `C:\Projects\astra-v1.2-beta-review-package.zip`.

## Commit gate

Do not commit yet. Commit is allowed only after the complete automated gate,
manual Windows verification, package validation and an independent reviewer
verdict `COMMIT`.

Suggested message after that verdict:

```text
Add v1.2 native Yandex Music integration
```
