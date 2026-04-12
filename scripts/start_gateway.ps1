param(
  [string]$Config = "config.json"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Config)) {
  Write-Host "Config '$Config' not found, creating from config.example.json"
  Copy-Item "config.example.json" $Config
}

python -m gateway_lite.main --config $Config
