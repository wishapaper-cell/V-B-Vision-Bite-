$ErrorActionPreference = "Stop"

$entrypoint = Join-Path $PSScriptRoot "scripts\dev\start-rokid-backend.ps1"
if (-not (Test-Path -LiteralPath $entrypoint)) {
    throw "Canonical Rokid backend launcher was not found: $entrypoint"
}
& $entrypoint @args
exit $LASTEXITCODE
