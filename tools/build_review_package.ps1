$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ProjectParent = Split-Path -Parent $ProjectRoot

$OutZip = Join-Path $ProjectParent "astra-v1.2-beta-review-package.zip"
$TempDir = Join-Path $ProjectParent "astra-v12-beta-review-clean"
$ReviewContextDir = Join-Path $TempDir "_REVIEW_CONTEXT"

if (Test-Path $OutZip) {
    Remove-Item $OutZip -Force
}

if (Test-Path $TempDir) {
    Remove-Item $TempDir -Recurse -Force
}

New-Item -ItemType Directory -Path $TempDir | Out-Null

$robocopyArgs = @(
    $ProjectRoot,
    $TempDir,
    "/E",
    "/XD",
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "logs",
    "cache",
    ".cache",
    "_REVIEW_CONTEXT",
    "_RELEASE_CONTEXT",
    "/XF",
    ".env",
    ".env.sanitized",
    "*-last-log.txt",
    "*.mp3",
    "*.pyc",
    "*.backup-*.json",
    "*.bak",
    "*.backup",
    "*.orig",
    "*~",
    "voice_test_log.txt"
)

& robocopy @robocopyArgs | Out-Null
$roboExit = $LASTEXITCODE

if ($roboExit -gt 7) {
    throw "robocopy failed with exit code $roboExit"
}

New-Item -ItemType Directory -Path $ReviewContextDir -Force | Out-Null

$EnvPath = Join-Path $ProjectRoot ".env"
$SanitizedEnvPath = Join-Path $TempDir ".env.sanitized"
$ContextEnvPath = Join-Path $ReviewContextDir "env_sanitized.txt"

if (Test-Path $EnvPath) {
    $sanitized = Get-Content $EnvPath -Encoding UTF8 |
        ForEach-Object {
            $_ -replace "^(GEMINI_API_KEY=).*", "GEMINI_API_KEY=REMOVED" `
               -replace "^(LLM_API_KEY=).*", "LLM_API_KEY=REMOVED" `
               -replace "^(OPENAI_API_KEY=).*", "OPENAI_API_KEY=REMOVED"
        }

    Set-Content -Path $SanitizedEnvPath -Value $sanitized -Encoding UTF8
    Set-Content -Path $ContextEnvPath -Value $sanitized -Encoding UTF8
}
else {
    Set-Content -Path $SanitizedEnvPath -Value "No .env file found in project root." -Encoding UTF8
    Set-Content -Path $ContextEnvPath -Value "No .env file found in project root." -Encoding UTF8
}

$ReadmeLines = @(
    "# Astra v1.2 Beta review package",
    "",
    "Purpose: independent code review for the v1.2 Native Music App Integration update.",
    "",
    "Included:",
    "- project source files",
    "- .env.example",
    "- .env.sanitized with API keys removed",
    "- _REVIEW_CONTEXT/env_sanitized.txt",
    "",
    "Excluded:",
    "- .git",
    "- .venv",
    "- real .env with API keys",
    "- logs",
    "- cache",
    "- mp3 files",
    "- __pycache__",
    "",
    "Recommended checks:",
    "python -m compileall main.py src tools",
    "python tools\smoke_test_v09_parser.py",
    "python tools\smoke_test_v10_parser.py",
    "python tools\smoke_test_v11_wake_runtime.py",
    "python tools\smoke_test_v100_beta.py",
    "python tools\smoke_test_v101_beta.py",
    "python tools\smoke_test_v11_daily_workflow.py",
    "python tools\smoke_test_v12_native_music.py",
    "python tools\validate_v10_config.py",
    "python tools\validate_v11_config.py",
    "python tools\validate_v12_config.py",
    "python tools\astra_doctor.py",
    "",
    "Review focus:",
    "- wake-only voice runtime",
    "- no-wake speech ignored in voice mode",
    "- no-wake command-like text not sent to LLM-router",
    "- v0.10.8.1 beta safety gate still active",
    "- safe routines allow only open_app/open_url/open_folder",
    "- bounded context cannot bypass wake or LLM safety gates",
    "- global media keys and previous-window behavior",
    "- local YouTube search query preservation",
    "- native Yandex Music resolver uses fixed whitelist data only",
    "- explicit Yandex Music website command remains a URL action",
    "- honest failure when the native client cannot be resolved",
    "- terminal typing/Enter guard",
    "- bounded TTS prewarm attempts",
    "- package secret/file validation"
)

Set-Content -Path (Join-Path $ReviewContextDir "README_REVIEW_PACKAGE.md") -Value $ReadmeLines -Encoding UTF8

Compress-Archive -Path (Join-Path $TempDir "*") -DestinationPath $OutZip -Force

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

& $PythonExe (Join-Path $ProjectRoot "tools\validate_package.py") $OutZip --source-root $ProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw "Review package validation failed with exit code $LASTEXITCODE"
}

Remove-Item $TempDir -Recurse -Force

Write-Host "Review package created:"
Write-Host $OutZip
