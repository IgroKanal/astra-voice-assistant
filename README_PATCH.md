# Astra v1.1 patch

Version: **v1.1 — Daily Workflow & Context Update (Beta)**

Apply this patch only to the final reviewed v1.0.1 source. The earlier attached
v1.0.1 release ZIP is stale and does not contain the final case-preserving URL
fix; use the reviewed/committed v1.0.1 tree as the base.

## Release goal

- reduce routine work with an exact-match `рабочий режим`;
- add safe global media controls and local YouTube search;
- remember one recent successful local target for `закрой его`;
- return to the previous Astra-focused window;
- preserve the wake-only and v0.10.8.1 safety gates.

Routines are limited to `open_app`, `open_url` and `open_folder`, with at most
eight validated steps. They cannot type, press keys, call the LLM, control VPN
or windows, or execute shell commands.

## Install patch

Replace the placeholder with the downloaded ZIP path:

```powershell
$ProjectDir = "C:\Projects\astra-voice-assistant"
$PatchZip = "C:\PATH\TO\astra-v1.1-patch.zip"
$PatchDir = Join-Path $env:TEMP "astra-v1.1-patch"

if (-not (Test-Path $PatchZip)) {
    throw "Patch ZIP not found: $PatchZip"
}
if (Test-Path $PatchDir) {
    Remove-Item $PatchDir -Recurse -Force
}

Expand-Archive -Path $PatchZip -DestinationPath $PatchDir -Force
Copy-Item -Path (Join-Path $PatchDir "*") -Destination $ProjectDir -Recurse -Force

Set-Location $ProjectDir
.\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File .\tools\apply_v11_beta_env.ps1
```

The environment helper updates only known beta settings and does not change an
API key. Review `config\routines.json` before running Astra.

## Automated verification

```powershell
python -m compileall main.py src tools
python tools\smoke_test_v09_parser.py
python tools\smoke_test_v10_parser.py
python tools\smoke_test_v11_wake_runtime.py
python tools\smoke_test_v100_beta.py
python tools\smoke_test_v101_beta.py
python tools\smoke_test_v11_daily_workflow.py
python tools\validate_v10_config.py
python tools\validate_v11_config.py
python tools\astra_doctor.py
```

## Manual Windows verification

Run `python main.py`, then test:

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
Астра, предыдущий трек
Астра, открой Telegram
Астра, закрой его
Астра, переключись на Firefox
Астра, вернись обратно
Астра, открой cmd
Астра, открой powershell
Астра, статус VPN
Астра, статус интер
```

Also repeat the v1.0.1 terminal-like foreground checks for typing and Enter.
No-wake commands must remain ignored and must not reach the router.

## Build review package

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_review_package.ps1
python .\tools\validate_package.py C:\Projects\astra-v1.1-beta-review-package.zip `
    --source-root C:\Projects\astra-voice-assistant
```

Expected archive: `C:\Projects\astra-v1.1-beta-review-package.zip`.

## Commit gate

Do not commit until the automated gate, manual Windows checks, package build,
independent review and staged-file secret check all pass. Suggested commit
message after a reviewer verdict `COMMIT`:

```text
Add v1.1 safe daily workflow and bounded context
```
