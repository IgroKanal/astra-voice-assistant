$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvPath = Join-Path $ProjectRoot ".env"

if (-not (Test-Path $EnvPath)) {
    throw ".env not found: $EnvPath"
}

$updates = [ordered]@{
    "ALLOW_COMMANDS_WITHOUT_WAKE" = "false"
}

$lines = New-Object System.Collections.Generic.List[string]
foreach ($line in Get-Content $EnvPath -Encoding UTF8) {
    $lines.Add($line)
}

foreach ($key in $updates.Keys) {
    $pattern = "^" + [Regex]::Escape($key) + "="
    $found = $false

    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match $pattern) {
            $lines[$i] = "$key=$($updates[$key])"
            $found = $true
            break
        }
    }

    if (-not $found) {
        $lines.Add("$key=$($updates[$key])")
    }
}

Set-Content -Path $EnvPath -Value $lines -Encoding UTF8
Write-Host "Astra v0.10.8 beta safety env settings applied to .env"
