param(
    [string]$Python = "",
    [switch]$SkipFrontend
)
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $projectRoot
if (-not $Python) {
    $Python = Join-Path $projectRoot ".venv-stage123\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) {
        $Python = Join-Path $projectRoot ".venv\Scripts\python.exe"
    }
}
$Python = (Resolve-Path -LiteralPath $Python).Path
& $Python -c "import PyInstaller, sqlmodel, fastapi, playwright"
if ($LASTEXITCODE -ne 0) { throw "Python environment is not ready." }
$buildVersion = & $Python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
if ($LASTEXITCODE -ne 0 -or $buildVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "Invalid project version."
}
if (-not $SkipFrontend) {
    & pnpm --dir frontend run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "web_static\dist\index.html"))) {
    throw "Frontend output is missing."
}
& $Python -m PyInstaller packaging/windows/app.spec --noconfirm --clean --distpath "dist/v$buildVersion" --workpath "build/v$buildVersion"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
Write-Host "Executable: dist/v$buildVersion/BiliLotteryAssistant/BiliLotteryAssistant.exe"
Write-Host "Keep the entire directory, including _internal."

