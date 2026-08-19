$ErrorActionPreference = "Stop"
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$processes = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*$workspaceRoot*apps\user-web*" -or
    $_.CommandLine -like "*$workspaceRoot*apps\supervisor-web*" -or
    $_.CommandLine -like "*$workspaceRoot*tools\camera-link*"
}

foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped $($process.Name) ($($process.ProcessId))"
}
