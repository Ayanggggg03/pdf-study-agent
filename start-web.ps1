param([int]$Port = 8765, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($taskCommand) { $taskPython = $taskCommand.Source }
}
if (-not $taskPython -or -not (Test-Path -LiteralPath $taskPython)) {
    Write-Host 'Please install Python 3.10+ and follow README.md.'
    exit 1
}
& $taskPython -c 'import pypdf'
if ($LASTEXITCODE -ne 0) {
    Write-Host "Install requirements: & '$taskPython' -m pip install -r requirements.txt"
    exit 1
}
if ($NoBrowser) {
    & $taskPython web_app.py --port $Port
} else {
    & $taskPython web_app.py --port $Port --open
}
exit $LASTEXITCODE
