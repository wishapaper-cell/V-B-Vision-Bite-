$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$workspaceRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$appUrl = "http://127.0.0.1:5000"
$runtimeDir = Join-Path $workspaceRoot ".workspace\run\user-web"
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$pidFile = Join-Path $runtimeDir ".health-server.pid"
$stampFile = Join-Path $runtimeDir ".health-server-source-stamp"
$pythonCandidates = @(
    (Join-Path $projectRoot ".venv\Scripts\python.exe"),
    (Join-Path $workspaceRoot ".workspace\venvs\user-web\Scripts\python.exe")
)
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCommand) { $pythonCandidates += $pythonCommand.Source }
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

function Test-AppReady {
    try {
        $response = Invoke-WebRequest -Uri $appUrl -UseBasicParsing -TimeoutSec 1 -MaximumRedirection 0 -ErrorAction SilentlyContinue
        return $null -ne $response
    } catch {
        if ($_.Exception.Response) { return $true }
        return $false
    }
}

function Get-SourceStamp {
    $sourceFiles = @(
        (Join-Path $projectRoot "app.py"),
        (Join-Path $projectRoot "database.py"),
        (Join-Path $projectRoot "food_db.py"),
        (Join-Path $projectRoot "recognition_adapter.py")
    )
    $sourceFiles += Get-ChildItem -LiteralPath (Join-Path $projectRoot "templates") -File -Recurse | Select-Object -ExpandProperty FullName
    $sourceFiles += Get-ChildItem -LiteralPath (Join-Path $projectRoot "static") -File -Recurse |
        Where-Object { $_.FullName -notlike "*\uploads\*" } |
        Select-Object -ExpandProperty FullName
    return ($sourceFiles | Get-Item | Measure-Object -Property LastWriteTimeUtc -Maximum).Maximum.Ticks.ToString()
}

$sourceStamp = Get-SourceStamp
if (Test-AppReady) {
    $runningStamp = if (Test-Path -LiteralPath $stampFile) { (Get-Content -LiteralPath $stampFile -Raw).Trim() } else { "" }
    if ($runningStamp -eq $sourceStamp) {
        Start-Process $appUrl
        exit 0
    }
    if (-not (Test-Path -LiteralPath $pidFile)) {
        Write-Error "检测到旧版服务，但找不到进程记录。请关闭旧服务后重新打开应用。"
        exit 1
    }
    $pidText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    try {
        [int]$serviceProcessId = $pidText
    } catch {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        Write-Error "服务进程记录无效，已清理旧记录，请重新打开应用。"
        exit 1
    }
    if ($serviceProcessId -le 0) {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        Write-Error "服务进程记录无效，已清理旧记录，请重新打开应用。"
        exit 1
    }
    $runningProcess = Get-Process -Id $serviceProcessId -ErrorAction SilentlyContinue
    if ($null -ne $runningProcess) {
        Stop-Process -Id $serviceProcessId -Force -ErrorAction SilentlyContinue
    } else {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }
    for ($attempt = 0; $attempt -lt 20 -and (Test-AppReady); $attempt++) {
        Start-Sleep -Milliseconds 150
    }
}

if (-not $python) {
    Write-Error "找不到 Python 运行环境，请安装 Python 3 或在项目中创建 .venv"
    exit 1
}

$appFile = Join-Path $projectRoot "app.py"
if (-not (Test-Path -LiteralPath $appFile)) {
    Write-Error "找不到 app.py"
    exit 1
}

$env:PYTHONUTF8 = "1"
$env:HEALTH_DB_PATH = Join-Path $workspaceRoot ".workspace\data\user-web\health.db"
$env:HEALTH_RUNTIME_DIR = $runtimeDir
$env:RECOGNITION_ALGORITHM_DIR = Join-Path $workspaceRoot "services\recognition"
$startOptions = @{
    FilePath = $python
    ArgumentList = @($appFile)
    WorkingDirectory = $projectRoot
    WindowStyle = "Hidden"
    PassThru = $true
}
$server = Start-Process @startOptions

for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 250
    if (Test-AppReady) {
        Set-Content -LiteralPath $stampFile -Value $sourceStamp -Encoding ASCII
        Start-Process $appUrl
        exit 0
    }
    if ($server.HasExited) {
        Write-Error "应用服务异常退出，退出代码：$($server.ExitCode)"
        exit 1
    }
}

Write-Error "等待应用服务启动超时"
exit 1
