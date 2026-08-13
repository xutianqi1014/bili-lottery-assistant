$ErrorActionPreference = "Stop"

Set-Location (Resolve-Path "$PSScriptRoot\..\..")
python -m PyInstaller packaging/windows/app.spec --noconfirm --clean
Write-Host "PyInstaller output: dist/BiliLotteryAssistant"

