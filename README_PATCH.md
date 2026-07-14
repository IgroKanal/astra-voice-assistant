# Astra v1.0.1 patch

Version: **v1.0.1 — Beta Bugfix & Reliability Update**

This patch is applied on top of the v1.0 Beta RC source at commit `a26f624`.

## Confirmed fixes

- URL paths, query strings, case-sensitive values and percent-encoding remain
  unchanged in local `OPEN_URL` actions.
- Failed TTS prewarm attempts count toward the synchronous startup limit.
- Default prewarm is limited to one attempt with an 8-second timeout.
- Truncated `отправь нажми` is handled as an incomplete local key command and
  never presses Enter or reaches LLM conversation fallback.
- Terminal text/Enter guard covers `code-insiders`, `Code - Insiders.exe` and
  `powershell_ise` in addition to the previous protected processes.
- Short `ок/ак/аг` fragments are blocked from application fuzzy matching.
- Review/release packages use v1.0.1 names and are validated after creation.

## Install patch

Replace `C:\PATH\TO\astra-v1.0.1-patch.zip` with the downloaded ZIP path:

```powershell
$ProjectDir = "C:\Projects\astra-voice-assistant"
$PatchZip = "C:\PATH\TO\astra-v1.0.1-patch.zip"
$PatchDir = Join-Path $env:TEMP "astra-v1.0.1-patch"

if (Test-Path $PatchDir) {
    Remove-Item $PatchDir -Recurse -Force
}

Expand-Archive -Path $PatchZip -DestinationPath $PatchDir -Force
Copy-Item -Path (Join-Path $PatchDir "*") -Destination $ProjectDir -Recurse -Force

Set-Location $ProjectDir
.\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File .\tools\apply_v101_beta_env.ps1
```

The environment helper updates only known beta settings. It does not replace
the API key or copy `.env` into an archive.

## Automated verification

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

## Manual Windows verification

Run `python main.py`, then test:

```text
открой YouTube
открой youtube.com
закрой блокнот
нажми Enter
стоп
Астра
открой YouTube
Астра, открой YouTube
Астер, стоп
Астэр, стоп
Астры, стоп
Астра, закрой окно
Астра, закрой ок
Астра, закрой АК
Астра, закрой АГ
Астра, открой https://example.com/CaseSensitive?Token=AbC
Астра, открой сайт www.youtube.com/watch?v=dQw4w9WgXcQ
Астра, статус VPN
Астра, статус интер
```

In a foreground terminal-like process, also verify that `Астра, напиши whoami`
and `Астра, нажми Enter` are blocked.

## Build review package

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_review_package.ps1
```

Expected output:

```text
C:\Projects\astra-v1.0.1-beta-review-package.zip
```

The script runs `tools\validate_package.py` automatically.

## Files to stage after review verdict COMMIT

Do not stage or commit before all automated tests, manual Windows checks and
independent review have passed.

```text
.env.example
BETA_CHECKLIST.md
GITHUB_UPLOAD.md
KNOWN_LIMITATIONS.md
README.md
README_PATCH.md
RELEASE_NOTES_v1.0.1.md
src/audio_io.py
src/command_parser.py
src/config_loader.py
src/keyboard_controller.py
src/task_router.py
src/windows_app_manager.py
tools/apply_v101_beta_env.ps1
tools/astra_doctor.py
tools/build_beta_package.ps1
tools/build_review_package.ps1
tools/smoke_test_v101_beta.py
tools/validate_package.py
tools/validate_v10_config.py
```

Suggested commit message after the full gate: `Fix v1.0.1 beta reliability regressions`
