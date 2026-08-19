$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\dev\common.ps1")

$workspaceRoot = Get-AdventureWorkspaceRoot
Initialize-AdventureEnvironment -WorkspaceRoot $workspaceRoot
$python = Get-AdventurePython -WorkspaceRoot $workspaceRoot
if (-not $python) {
    throw "Python environment was not found. Run scripts/dev/setup-python.ps1 first."
}

& (Join-Path $PSScriptRoot "check-structure.ps1")

$pythonFiles = @(
    (Join-Path $workspaceRoot "apps\user-web\app.py"),
    (Join-Path $workspaceRoot "apps\user-web\database.py"),
    (Join-Path $workspaceRoot "apps\user-web\recognition_adapter.py"),
    (Join-Path $workspaceRoot "apps\supervisor-web\app.py"),
    (Join-Path $workspaceRoot "apps\supervisor-web\admin_database.py"),
    (Join-Path $workspaceRoot "tools\camera-link\server.py")
)
& $python -m py_compile @pythonFiles

Push-Location (Join-Path $workspaceRoot "tools\camera-link")
try {
    & $python -m pytest tests -q
} finally {
    Pop-Location
}

Push-Location (Join-Path $workspaceRoot "services\recognition")
try {
    & $python -m pytest tests -q
} finally {
    Pop-Location
}

Write-Host "All configured checks passed." -ForegroundColor Green
