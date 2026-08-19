$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$workspaceRoot = Get-AdventureWorkspaceRoot
Initialize-AdventureEnvironment -WorkspaceRoot $workspaceRoot
$python = Get-AdventurePython -WorkspaceRoot $workspaceRoot
if (-not $python) {
    throw "Python environment was not found. Run scripts/dev/setup-python.ps1 first."
}

$serverRoot = Join-Path $workspaceRoot "tools\camera-link"
$server = Join-Path $serverRoot "server.py"
& $python -c "import av, PIL, cv2, numpy, ultralytics"
if ($LASTEXITCODE -ne 0) {
    throw "Video or recognition dependencies are missing. Run scripts/dev/setup-python.ps1."
}

Write-Host "Rokid backend: http://127.0.0.1:9088" -ForegroundColor Green
Write-Host "Glasses UDP stream target: udp://<computer-ip>:5000"
Set-Location -LiteralPath $serverRoot
& $python $server `
    --host 0.0.0.0 `
    --port 9088 `
    --udp-host 0.0.0.0 `
    --udp-port 5000 `
    --preview-fps 10 `
    --recognition-fps 1.5
