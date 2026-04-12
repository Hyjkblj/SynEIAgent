param(
  [string]$OutputDir = "..\SynEIAgent_standalone"
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Resolve-Path (Join-Path $scriptRoot "..")

if ([System.IO.Path]::IsPathRooted($OutputDir)) {
  $resolvedOutputDir = $OutputDir
} else {
  $resolvedOutputDir = Join-Path $src $OutputDir
}

$dst = Resolve-Path $resolvedOutputDir -ErrorAction SilentlyContinue
if (-not $dst) {
  New-Item -ItemType Directory -Path $resolvedOutputDir | Out-Null
  $dst = Resolve-Path $resolvedOutputDir
}

Write-Host "Exporting from $src to $dst"

$items = @(
  "gateway_lite",
  "ros_bridge_lite",
  "scripts",
  "README.md",
  "config.example.json",
  "requirements.txt",
  "requirements-gateway.txt",
  "requirements-ros.txt",
  "pyproject.toml",
  ".gitignore"
)

foreach ($item in $items) {
  $srcPath = Join-Path $src $item
  if (-not (Test-Path $srcPath)) {
    continue
  }
  $dstPath = Join-Path $dst $item
  if (Test-Path $dstPath) {
    Remove-Item -Recurse -Force $dstPath
  }
  Copy-Item -Recurse -Force $srcPath $dstPath
}

Write-Host "Export complete. Standalone project at: $dst"

