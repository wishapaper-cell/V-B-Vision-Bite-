$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$workspaceRoot = Get-AdventureWorkspaceRoot
$venvRoot = Join-Path $workspaceRoot "apps\user-web\.venv"
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw "Python 3.11 was not found on PATH."
}

if (-not (Test-Path -LiteralPath (Join-Path $venvRoot "Scripts\python.exe"))) {
    & $pythonCommand.Source -m venv $venvRoot
}

$python = Join-Path $venvRoot "Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $workspaceRoot "apps\user-web\requirements.txt")
& $python -m pip install -r (Join-Path $workspaceRoot "apps\user-web\requirements-recognition.txt")
& $python -m pip install -r (Join-Path $workspaceRoot "tools\camera-link\requirements.txt")
& $python -m pip install -r (Join-Path $workspaceRoot "services\recognition\requirements-dev.txt")

Write-Host "Python environment is ready: $venvRoot" -ForegroundColor Green
