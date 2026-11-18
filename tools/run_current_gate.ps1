[CmdletBinding()]
param(
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Astra project directory not found: $ProjectRoot"
}

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtual-environment Python not found: $python"
}

Push-Location -LiteralPath $ProjectRoot
try {
    if (Test-Path -LiteralPath (Join-Path $ProjectRoot ".git")) {
        & git status --short --branch
        if ($LASTEXITCODE -ne 0) { throw "git status failed" }

        & git diff --check
        if ($LASTEXITCODE -ne 0) { throw "git diff --check failed" }
    }
    else {
        Write-Host "Git metadata is absent; repository-only checks are not applicable."
    }

    $buildTempRoot = & $python -c "from pathlib import Path; from tools.build_paths import resolve_build_paths; print(resolve_build_paths(Path.cwd()).temp_root)"
    if ($LASTEXITCODE -ne 0 -or -not $buildTempRoot) {
        throw "Could not resolve the safe temporary directory for the Astra gate"
    }
    $buildTempRoot = $buildTempRoot.Trim()
    New-Item -ItemType Directory -Path $buildTempRoot -Force | Out-Null
    $env:TEMP = $buildTempRoot
    $env:TMP = $buildTempRoot
    $env:TMPDIR = $buildTempRoot
    Write-Host "Python gate temporary directory: $buildTempRoot"

    & $python -m compileall main.py src tools
    if ($LASTEXITCODE -ne 0) { throw "compileall failed" }

    & $python -m py_compile astra_desktop.pyw astra_desktop_qt.py astra_runtime.py src/qt_theme.py src/qt_widgets.py src/qt_dialogs.py src/qt_voice_files.py
    if ($LASTEXITCODE -ne 0) { throw "Desktop compilation failed" }

    $tests = @(
        "tools\smoke_test_v09_parser.py",
        "tools\smoke_test_v10_parser.py",
        "tools\smoke_test_v11_wake_runtime.py",
        "tools\smoke_test_v100_beta.py",
        "tools\smoke_test_v101_beta.py",
        "tools\smoke_test_v11_daily_workflow.py",
        "tools\smoke_test_v12_native_music.py",
        "tools\smoke_test_v13_media_control.py",
        "tools\smoke_test_v13_window_actions.py",
        "tools\validate_v10_config.py",
        "tools\validate_v11_config.py",
        "tools\validate_v12_config.py",
        "tools\validate_v13_config.py",
        "tools\astra_doctor.py"
    )

    foreach ($test in $tests) {
        if (-not (Test-Path -LiteralPath $test -PathType Leaf)) {
            throw "Required gate file not found: $test"
        }
        Write-Host "Running $test"
        & $python $test
        if ($LASTEXITCODE -ne 0) {
            throw "Gate failed: $test"
        }
    }

    & $python -m unittest discover -s tools -p "test_*.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Desktop/skills unit and integration tests failed" }

    Write-Host "Astra current automatic gate passed. Manual Windows tests are still required."
}
finally {
    Pop-Location
}
