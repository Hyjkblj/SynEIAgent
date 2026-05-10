@echo off
setlocal

if not defined PROJECT_ROOT set "PROJECT_ROOT=D:\Develop\Project\SynEIAgent"
if not defined ROS2_ROOT set "ROS2_ROOT=D:\Develop\ros2-jazzy-20260128-windows-release-amd64\ros2-windows"
if not defined ROS2_PYTHON set "ROS2_PYTHON=C:\pixi_ws\.pixi\envs\default\python.exe"
set "ROS2_SETUP_BAT=%ROS2_ROOT%\setup.bat"

set "HOST=0.0.0.0"
set "PORT=8080"
set "CMD_VEL_TOPIC=/cmd_vel"
set "JOINT_COMMAND_TOPIC=/joint_command"
set "CONTROL_MODE=joint_gait"
set "CONTROL_HZ=50"
set "NODE_NAME=gateway_lite_bridge"
set "SET_MOTION_SERVICE=/set_motion_number"

set "PYTHONNOUSERSITE=1"
set "PYTHONPATH="
set "PYTHONHOME="

if not exist "%PROJECT_ROOT%" (
    echo [ERROR] PROJECT_ROOT not found: %PROJECT_ROOT%
    exit /b 1
)

if not exist "%ROS2_SETUP_BAT%" (
    echo [ERROR] ROS2 setup.bat not found: %ROS2_SETUP_BAT%
    exit /b 1
)

if not exist "%ROS2_PYTHON%" (
    echo [ERROR] ROS2_PYTHON not found: %ROS2_PYTHON%
    exit /b 1
)

set "EXISTING_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    set "EXISTING_PID=%%P"
    goto :found_ros_port
)
goto :no_ros_port

:found_ros_port
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:%PORT%/health' -TimeoutSec 2; if ($r.ok -eq $true) { exit 0 } else { exit 2 } } catch { exit 1 }" >nul 2>nul
if "%errorlevel%"=="0" (
    echo [INFO] ROS Bridge is already running on port %PORT%. PID=%EXISTING_PID%
    echo [INFO] Health: http://127.0.0.1:%PORT%/health
    exit /b 0
)
echo [ERROR] Port %PORT% is already in use by PID=%EXISTING_PID%, but health check failed.
echo [HINT] Stop the process or change ROS Bridge port.
exit /b 1

:no_ros_port

call "%ROS2_SETUP_BAT%"
if errorlevel 1 (
    echo [ERROR] Failed to load ROS2 env from: %ROS2_ROOT%
    exit /b 1
)

cd /d "%PROJECT_ROOT%"

echo [INFO] ROS bridge python:
"%ROS2_PYTHON%" -c "import sys; print(sys.executable)"
if errorlevel 1 exit /b 1

"%ROS2_PYTHON%" -c "import aiohttp, rclpy" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Missing aiohttp or rclpy in ROS2 python env.
    echo [HINT] First run:
    echo        "%ROS2_PYTHON%" -m pip install aiohttp
    echo [HINT] Then verify in CMD:
    echo        cd /d C:\pixi_ws
    echo        pixi shell
    echo        call "%ROS2_SETUP_BAT%"
    echo        ros2 topic list
    exit /b 1
)
echo [INFO] aiohttp+rclpy ok

echo [INFO] Starting ROS Bridge Lite on 8080 (mode=%CONTROL_MODE%)...
"%ROS2_PYTHON%" -m ros_bridge_lite.main --host %HOST% --port %PORT% --cmd-vel-topic %CMD_VEL_TOPIC% --joint-command-topic %JOINT_COMMAND_TOPIC% --control-mode %CONTROL_MODE% --control-hz %CONTROL_HZ% --node-name %NODE_NAME% --set-motion-service %SET_MOTION_SERVICE%
exit /b %errorlevel%
