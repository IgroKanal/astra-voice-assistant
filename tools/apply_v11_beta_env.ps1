$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvPath = Join-Path $ProjectRoot ".env"

if (-not (Test-Path $EnvPath)) {
    throw ".env not found: $EnvPath"
}

$Utf8 = [System.Text.Encoding]::UTF8
$WakeResponseText = $Utf8.GetString([Convert]::FromBase64String("0KHQu9GD0YjQsNGOLg=="))
$WakePhrases = $Utf8.GetString([Convert]::FromBase64String("0LDRgdGC0YDQsCzRjdC5INCw0YHRgtGA0LAs0L/RgNC40LLQtdGCINCw0YHRgtGA0LAs0LDRgdGC0YDQvizQvtGB0YLRgNCwLNCwINGB0YLRgNCwLNCw0YHRgtC10YAs0LDRgdGC0Y3RgCzQsNGB0YLRgNGL"))

$Updates = [ordered]@{
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
    "ROUTINES_ENABLED" = "true"
    "ROUTINES_CONFIG_PATH" = "config/routines.json"
    "CONTEXT_TTL_SECONDS" = "120"
}

$Lines = New-Object System.Collections.Generic.List[string]
foreach ($Line in Get-Content $EnvPath -Encoding UTF8) {
    $Lines.Add($Line)
}

foreach ($Key in $Updates.Keys) {
    $Pattern = "^" + [Regex]::Escape($Key) + "="
    $Found = $false

    for ($Index = 0; $Index -lt $Lines.Count; $Index++) {
        if ($Lines[$Index] -match $Pattern) {
            $Lines[$Index] = "$Key=$($Updates[$Key])"
            $Found = $true
            break
        }
    }

    if (-not $Found) {
        $Lines.Add("$Key=$($Updates[$Key])")
    }
}

Set-Content -Path $EnvPath -Value $Lines -Encoding UTF8
Write-Host "Astra v1.1 Beta environment settings applied to .env"
