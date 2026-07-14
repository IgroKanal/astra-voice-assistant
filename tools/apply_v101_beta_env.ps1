$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvPath = Join-Path $ProjectRoot ".env"

if (-not (Test-Path $EnvPath)) {
    throw ".env not found: $EnvPath"
}

$Utf8 = [System.Text.Encoding]::UTF8
$WakeResponseText = $Utf8.GetString([Convert]::FromBase64String("0KHQu9GD0YjQsNGOLg=="))
$WakePhrases = $Utf8.GetString([Convert]::FromBase64String("0LDRgdGC0YDQsCzRjdC5INCw0YHRgtGA0LAs0L/RgNC40LLQtdGCINCw0YHRgtGA0LAs0LDRgdGC0YDQvizQvtGB0YLRgNCwLNCwINGB0YLRgNCwLNCw0YHRgtC10YAs0LDRgdGC0Y3RgCzQsNGB0YLRgNGL"))

$updates = [ordered]@{
    "WAKE_PHRASES" = $WakePhrases
    "VOICE_RUNTIME_MODE" = "wake_only"
    "WAKE_ONLY_MODE" = "true"
    "WAKE_RESPONSE_ENABLED" = "true"
    "WAKE_RESPONSE_TEXT" = $WakeResponseText
    "WAKE_LISTEN_TIMEOUT_SECONDS" = "4"
    "WAKE_PHRASE_TIME_LIMIT_SECONDS" = "4"
    "COMMAND_LISTEN_TIMEOUT_SECONDS" = "10"
    "COMMAND_PHRASE_TIME_LIMIT_SECONDS" = "16"
    "WAKE_ALLOW_DIRECT_COMMAND" = "true"
    "ALLOW_COMMANDS_WITHOUT_WAKE" = "false"
    "ALLOW_VOICE_CONVERSATION_WITHOUT_WAKE" = "false"
    "TTS_CACHE_PREWARM_MAX_NEW_PHRASES" = "1"
    "TTS_CACHE_GENERATION_TIMEOUT_SECONDS" = "8"
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
Write-Host "Astra v1.0.1 Beta environment settings applied to .env"
