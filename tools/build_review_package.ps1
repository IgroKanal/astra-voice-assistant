$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ProjectParent = Split-Path -Parent $ProjectRoot

$OutZip = Join-Path $ProjectParent "astra-v0.11.1-review-package.zip"
$TempDir = Join-Path $ProjectParent "astra-v0111-review-clean"
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
    ".cache",
    "/XF",
    ".env",
    "*.mp3",
    "*.pyc",
    "*.backup-*.json",
    "voice_test_log.txt",
    "README_PATCH.md"
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
    "# Astra v0.11.1 review package",
    "",
    "Purpose: code review package for Wake Runtime Polish.",
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
    "python tools\validate_v10_config.py",
    "python tools\astra_doctor.py",
    "",
    "Review focus:",
    "- wake-only voice runtime",
    "- no-wake speech ignored in voice mode",
    "- no-wake command-like text not sent to LLM-router",
    "- v0.10.8.1 beta safety gate still active",
    "- text mode and stt-test not broken"
)

Set-Content -Path (Join-Path $ReviewContextDir "README_REVIEW_PACKAGE.md") -Value $ReadmeLines -Encoding UTF8

Compress-Archive -Path (Join-Path $TempDir "*") -DestinationPath $OutZip -Force

Remove-Item $TempDir -Recurse -Force

Write-Host "Review package created:"
Write-Host $OutZip
