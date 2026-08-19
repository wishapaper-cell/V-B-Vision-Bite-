$ErrorActionPreference = "Stop"

function Get-AdventureWorkspaceRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Get-AdventurePython {
    param([string]$WorkspaceRoot)

    $candidates = @(
        (Join-Path $WorkspaceRoot "apps\user-web\.venv\Scripts\python.exe"),
        (Join-Path $WorkspaceRoot ".workspace\venvs\user-web\Scripts\python.exe")
    )
    $systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($systemPython) {
        $candidates += $systemPython.Source
    }
    return $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

function Initialize-AdventureEnvironment {
    param([string]$WorkspaceRoot)

    $dataRoot = Join-Path $WorkspaceRoot ".workspace\data"
    $runRoot = Join-Path $WorkspaceRoot ".workspace\run"
    New-Item -ItemType Directory -Force -Path `
        (Join-Path $dataRoot "user-web"), `
        (Join-Path $dataRoot "supervisor-web"), `
        (Join-Path $runRoot "user-web"), `
        (Join-Path $runRoot "supervisor-web") | Out-Null

    $env:PYTHONUTF8 = "1"
    $env:HEALTH_DB_PATH = Join-Path $dataRoot "user-web\health.db"
    $env:HEALTH_RUNTIME_DIR = Join-Path $runRoot "user-web"
    $env:HEALTH_UPLOAD_DIR = Join-Path $dataRoot "user-web\uploads"
    $env:RECOGNITION_ALGORITHM_DIR = Join-Path $WorkspaceRoot "services\recognition"
    $env:USER_APP_DB_PATH = $env:HEALTH_DB_PATH
    $env:ADMIN_DB_PATH = Join-Path $dataRoot "supervisor-web\admin.db"
    $env:ADMIN_RUNTIME_DIR = Join-Path $runRoot "supervisor-web"
    $env:ADMIN_BACKUP_DIR = Join-Path $dataRoot "supervisor-web\backups"
}
