$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvPath = Join-Path $ProjectRoot ".env"

if (-not (Test-Path $EnvPath)) {
    throw ".env not found: $EnvPath"
}

$updates = [ordered]@{
    "LISTEN_TIMEOUT_SECONDS" = "10"
    "PHRASE_TIME_LIMIT_SECONDS" = "16"
    "AMBIENT_NOISE_DURATION_SECONDS" = "0.6"
    "STT_PAUSE_THRESHOLD" = "1.15"
    "STT_NON_SPEAKING_DURATION" = "0.8"
    "TTS_CACHE_PREWARM_MAX_NEW_PHRASES" = "4"
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

Write-Host "Astra v0.10.6 voice env settings applied to .env"
