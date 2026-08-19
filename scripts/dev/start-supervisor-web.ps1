$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$workspaceRoot = Get-AdventureWorkspaceRoot
Initialize-AdventureEnvironment -WorkspaceRoot $workspaceRoot
$python = Get-AdventurePython -WorkspaceRoot $workspaceRoot
if (-not $python) {
    throw "Python environment was not found. Run scripts/dev/setup-python.ps1 first."
}

$appRoot = Join-Path $workspaceRoot "apps\supervisor-web"
Set-Location -LiteralPath $appRoot
& $python .\app.py
