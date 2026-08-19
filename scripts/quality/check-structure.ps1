$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

$required = @(
    "apps\user-web\app.py",
    "apps\supervisor-web\app.py",
    "apps\rokid-streamer\settings.gradle",
    "services\recognition\backend\models\schemas.py",
    "tools\camera-link\server.py",
    "docs\README.md",
    "CONTRIBUTING.md",
    "SECURITY.md"
)

$missing = @()
foreach ($relative in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $relative))) {
        $missing += $relative
    }
}
if ($missing.Count -gt 0) {
    throw "Required repository files are missing: $($missing -join ', ')"
}

$forbiddenRootEntries = @("health_diet_app", "recognition_algorithm", "rokid_camera_link_demo")
$unexpected = $forbiddenRootEntries | Where-Object { Test-Path -LiteralPath (Join-Path $root $_) }
if ($unexpected) {
    throw "Legacy top-level paths remain outside legacy/: $($unexpected -join ', ')"
}

Write-Host "Repository structure check passed." -ForegroundColor Green
