$ErrorActionPreference = "Stop"
$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "Astra Voice Assistant.lnk"

if (Test-Path $ShortcutPath) {
    Remove-Item $ShortcutPath -Force
    Write-Host "Astra autostart removed."
} else {
    Write-Host "Astra autostart shortcut was not found."
}
