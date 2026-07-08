$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvPath = Join-Path $ProjectRoot ".env"

if (-not (Test-Path $EnvPath)) {
    throw ".env not found: $EnvPath"
}

$updates = [ordered]@{
    "VOICE_RUNTIME_MODE" = "wake_only"
    "WAKE_ONLY_MODE" = "true"
    "WAKE_RESPONSE_ENABLED" = "true"
    "WAKE_RESPONSE_TEXT" = "Слушаю."
    "WAKE_LISTEN_TIMEOUT_SECONDS" = "4"
    "WAKE_PHRASE_TIME_LIMIT_SECONDS" = "4"
    "COMMAND_LISTEN_TIMEOUT_SECONDS" = "10"
    "COMMAND_PHRASE_TIME_LIMIT_SECONDS" = "16"
    "WAKE_ALLOW_DIRECT_COMMAND" = "true"
    "ALLOW_COMMANDS_WITHOUT_WAKE" = "false"
    "ALLOW_VOICE_CONVERSATION_WITHOUT_WAKE" = "false"
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
Write-Host "Astra v0.11 wake-only env settings applied to .env"
