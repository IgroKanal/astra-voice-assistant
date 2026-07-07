$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "Astra Voice Assistant.lnk"
if (Test-Path $ShortcutPath) {
    Remove-Item $ShortcutPath -Force
    Write-Host "Автозапуск Astra удалён."
} else {
    Write-Host "Автозапуск Astra не найден."
}
