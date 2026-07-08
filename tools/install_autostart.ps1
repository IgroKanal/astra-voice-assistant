$ErrorActionPreference = "Stop"
$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$VbsPath = Join-Path $ProjectDir "start_astra_hidden.vbs"

if (-not (Test-Path $VbsPath)) {
    throw "start_astra_hidden.vbs not found: $VbsPath"
}

$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "Astra Voice Assistant.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "wscript.exe"
$Shortcut.Arguments = "`"$VbsPath`""
$Shortcut.WorkingDirectory = $ProjectDir
$Shortcut.WindowStyle = 7
$Shortcut.Description = "Astra Voice Assistant background startup"
$Shortcut.Save()

Write-Host "Astra autostart installed: $ShortcutPath"
