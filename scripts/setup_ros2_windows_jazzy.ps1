param(
    [string]$RosRoot = "C:\pixi_ws",
    [switch]$SkipPixiInstall = $false,
    [switch]$SkipRosZipDownload = $false
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) {
    Write-Host "[STEP] $msg" -ForegroundColor Cyan
}

function Write-Info([string]$msg) {
    Write-Host "[INFO] $msg" -ForegroundColor Green
}

function Write-WarnMsg([string]$msg) {
    Write-Host "[WARN] $msg" -ForegroundColor Yellow
}

function Require-AdminIfNeeded {
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).
        IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-WarnMsg "You are not running as Administrator. Some install steps may fail."
    }
}

function Ensure-Pixi {
    if ($SkipPixiInstall) {
        Write-WarnMsg "Skipping pixi install as requested."
        return
    }

    $pixiCmd = Get-Command pixi -ErrorAction SilentlyContinue
    if ($pixiCmd) {
        Write-Info "pixi already available: $($pixiCmd.Source)"
        return
    }

    Write-Step "Installing pixi (official installer script)"
    powershell -ExecutionPolicy Bypass -c "irm -useb https://pixi.sh/install.ps1 | iex"

    $pixiBin = Join-Path $env:USERPROFILE ".pixi\bin"
    if (Test-Path $pixiBin) {
        $env:PATH = "$pixiBin;$env:PATH"
    }

    $pixiCmd = Get-Command pixi -ErrorAction SilentlyContinue
    if (-not $pixiCmd) {
        throw "pixi install did not complete correctly. Open a new terminal and rerun this script."
    }
    Write-Info "pixi installed: $($pixiCmd.Source)"
}

function Ensure-RosRoot([string]$path) {
    if (-not (Test-Path $path)) {
        Write-Step "Creating ROS root: $path"
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    } else {
        Write-Info "ROS root exists: $path"
    }
}

function Install-RosDepsWithPixi([string]$path) {
    Write-Step "Installing ROS Windows dependencies via pixi"
    Push-Location $path
    try {
        Invoke-WebRequest -Uri "https://raw.githubusercontent.com/ros2/ros2/refs/heads/jazzy/pixi.toml" -OutFile "pixi.toml"
        pixi install
    } finally {
        Pop-Location
    }
}

function Get-LatestJazzyWindowsAsset {
    $api = "https://api.github.com/repos/ros2/ros2/releases"
    $releases = Invoke-RestMethod -Uri $api
    foreach ($release in $releases) {
        foreach ($asset in $release.assets) {
            if ($asset.name -like "ros2-jazzy-*-windows-release-amd64.zip") {
                return $asset
            }
        }
    }
    return $null
}

function Download-And-Extract-RosZip([string]$path) {
    if ($SkipRosZipDownload) {
        Write-WarnMsg "Skipping ROS zip download as requested."
        return
    }

    Write-Step "Finding latest ROS 2 Jazzy Windows release asset"
    $asset = Get-LatestJazzyWindowsAsset
    if (-not $asset) {
        throw "Unable to find ros2-jazzy-*-windows-release-amd64.zip on GitHub releases."
    }

    $zipPath = Join-Path $path $asset.name
    $extractPath = Join-Path $path "ros2-windows"

    Write-Step "Downloading $($asset.name)"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath

    if (Test-Path $extractPath) {
        Write-WarnMsg "Existing extract path found, removing: $extractPath"
        Remove-Item -Recurse -Force $extractPath
    }

    Write-Step "Extracting ROS 2 to $extractPath"
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractPath -Force

    $localSetup = Join-Path $extractPath "local_setup.bat"
    if (-not (Test-Path $localSetup)) {
        throw "Extraction completed but local_setup.bat not found at $localSetup"
    }
    Write-Info "ROS local setup ready: $localSetup"
}

Require-AdminIfNeeded
Ensure-Pixi
Ensure-RosRoot -path $RosRoot
Install-RosDepsWithPixi -path $RosRoot
Download-And-Extract-RosZip -path $RosRoot

Write-Host ""
Write-Host "Done. Next terminal (cmd) test commands:" -ForegroundColor Cyan
Write-Host "  cd /d $RosRoot"
Write-Host "  pixi shell"
Write-Host "  call $RosRoot\ros2-windows\local_setup.bat"
Write-Host "  ros2 topic list"
