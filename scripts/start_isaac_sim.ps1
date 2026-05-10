# Isaac Sim 仿真启动脚本 (Windows PowerShell)
# 使用方法: .\start_isaac_sim.ps1

param(
    [string]$IsaacSimPath = "",
    [string]$UrdfPath = "",
    [switch]$Headless = $false,
    [switch]$NoVideo = $false,
    [string]$GatewayUrl = "http://localhost:8088"
)

# 项目根目录
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

# 默认 URDF 路径
if ([string]::IsNullOrEmpty($UrdfPath)) {
    $UrdfPath = Join-Path $RepoRoot "TGrobot4s\lite_urdf_publish\x_humanoid_0430_newfeet_newbody_publish\urdf\humanoid_publish.urdf"
}

# 检查 URDF 文件
if (-not (Test-Path $UrdfPath)) {
    Write-Host "[Error] URDF file not found: $UrdfPath" -ForegroundColor Red
    exit 1
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Isaac Sim Simulation Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "URDF: $UrdfPath" -ForegroundColor Green
Write-Host "Gateway: $GatewayUrl" -ForegroundColor Green
Write-Host "Headless: $Headless" -ForegroundColor Green
Write-Host ""

# 查找 Isaac Sim 安装路径
if ([string]::IsNullOrEmpty($IsaacSimPath)) {
    # 常见安装路径
    $PossiblePaths = @(
        "$env:LOCALAPPDATA\ov\pkg\isaac-sim-*",
        "$env:APPDATA\..\Local\ov\pkg\isaac-sim-*",
        "C:\Program Files\NVIDIA\Omniverse\isaac-sim-*"
    )
    
    foreach ($Pattern in $PossiblePaths) {
        $Found = Get-Item $Pattern -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($Found) {
            $IsaacSimPath = $Found.FullName
            break
        }
    }
}

if ([string]::IsNullOrEmpty($IsaacSimPath)) {
    Write-Host "[Error] Isaac Sim not found. Please specify --IsaacSimPath" -ForegroundColor Red
    Write-Host ""
    Write-Host "Example:" -ForegroundColor Yellow
    Write-Host "  .\start_isaac_sim.ps1 -IsaacSimPath 'C:\Users\<user>\AppData\Local\ov\pkg\isaac-sim-4.2.0'" -ForegroundColor Yellow
    exit 1
}

Write-Host "Isaac Sim: $IsaacSimPath" -ForegroundColor Green
Write-Host ""

# 构建 Python 命令
$PythonExe = Join-Path $IsaacSimPath "python.bat"
$LauncherScript = Join-Path $RepoRoot "TGrobot4s\isaac_sim\simulation_launcher.py")

# 构建参数
$Args = @(
    $LauncherScript,
    "--urdf", $UrdfPath,
    "--gateway-url", $GatewayUrl
)

if ($Headless) {
    $Args += "--headless"
}

if ($NoVideo) {
    $Args += "--no-video"
}

Write-Host "Starting simulation..." -ForegroundColor Cyan
Write-Host ""

# 启动仿真
& $PythonExe $Args
