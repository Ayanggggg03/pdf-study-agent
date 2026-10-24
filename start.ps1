param([switch]$KeyDialog)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}
if (-not (Test-Path -LiteralPath $taskPython)) {
    Write-Host 'Please install Python and follow README.md.'
    exit 1
}
if (-not (Test-Path -LiteralPath 'config.json')) {
    Copy-Item -LiteralPath 'config.example.json' -Destination 'config.json'
}
& $taskPython -c 'import pypdf'
if ($LASTEXITCODE -ne 0) {
    Write-Host "Install requirements: & '$taskPython' -m pip install -r requirements.txt"
    exit 1
}
if ($KeyDialog) {
    & $taskPython agent.py --key-dialog
} else {
    & $taskPython agent.py
}
exit $LASTEXITCODE
