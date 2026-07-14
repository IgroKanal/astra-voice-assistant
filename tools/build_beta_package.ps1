$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ProjectParent = Split-Path -Parent $ProjectRoot

$OutZip = Join-Path $ProjectParent "astra-v1.0.1-beta-release.zip"
$TempDir = Join-Path $ProjectParent "astra-v101-beta-release-clean"
$ContextDir = Join-Path $TempDir "_RELEASE_CONTEXT"

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
    "/XF",
    ".env",
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

New-Item -ItemType Directory -Path $ContextDir -Force | Out-Null

$EnvPath = Join-Path $ProjectRoot ".env"
$SanitizedEnvPath = Join-Path $TempDir ".env.sanitized"
$ContextEnvPath = Join-Path $ContextDir "env_sanitized.txt"

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
    "# Astra v1.0.1 Beta release package",
    "",
    "This package excludes .git, .venv, real .env, logs, caches, pyc and mp3 cache files.",
    "",
    "Before release, run:",
    "python -m compileall main.py src tools",
    "python tools\smoke_test_v09_parser.py",
    "python tools\smoke_test_v10_parser.py",
    "python tools\smoke_test_v11_wake_runtime.py",
    "python tools\smoke_test_v100_beta.py",
    "python tools\smoke_test_v101_beta.py",
    "python tools\validate_v10_config.py",
    "python tools\astra_doctor.py",
    "",
    "Use .env.example to create a local .env. Never publish a real .env with API keys."
)

Set-Content -Path (Join-Path $ContextDir "README_RELEASE_PACKAGE.md") -Value $ReadmeLines -Encoding UTF8

Compress-Archive -Path (Join-Path $TempDir "*") -DestinationPath $OutZip -Force

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

& $PythonExe (Join-Path $ProjectRoot "tools\validate_package.py") $OutZip
if ($LASTEXITCODE -ne 0) {
    throw "Release package validation failed with exit code $LASTEXITCODE"
}

Remove-Item $TempDir -Recurse -Force

Write-Host "Beta release package created:"
Write-Host $OutZip
