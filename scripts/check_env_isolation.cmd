@echo off
setlocal

if not defined ISAAC_ENV_PYTHON set "ISAAC_ENV_PYTHON=D:\isaaclab_env\python.exe"
if not defined ROS2_ROOT set "ROS2_ROOT=D:\Develop\ros2-jazzy-20260128-windows-release-amd64\ros2-windows"
if not defined ROS2_PYTHON set "ROS2_PYTHON=C:\pixi_ws\.pixi\envs\default\python.exe"
set "ROS2_SETUP_BAT=%ROS2_ROOT%\setup.bat"

echo ===== Check Gateway Env (Isaac/Conda) =====
if not exist "%ISAAC_ENV_PYTHON%" (
    echo [ERROR] Not found: %ISAAC_ENV_PYTHON%
    exit /b 1
)
"%ISAAC_ENV_PYTHON%" -c "import sys, aiohttp; print('python=' + sys.executable); print('aiohttp=' + aiohttp.__version__)"
if errorlevel 1 exit /b 1
echo.

echo ===== Check ROS2 Env (Pixi + ROS2 Jazzy) =====
if not exist "%ROS2_SETUP_BAT%" (
    echo [ERROR] Not found: %ROS2_SETUP_BAT%
    exit /b 1
)
if not exist "%ROS2_PYTHON%" (
    echo [ERROR] Not found: %ROS2_PYTHON%
    exit /b 1
)
call "%ROS2_SETUP_BAT%"
if errorlevel 1 exit /b 1
"%ROS2_PYTHON%" -c "import aiohttp, rclpy" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] ROS2 env check failed in %ROS2_PYTHON%
    echo [HINT] Verify in CMD:
    echo        cd /d C:\pixi_ws
    echo        pixi shell
    echo        call "%ROS2_SETUP_BAT%"
    echo        ros2 topic list
    exit /b 1
)
"%ROS2_PYTHON%" -c "import sys, aiohttp, rclpy; print('python=' + sys.executable); print('aiohttp=' + aiohttp.__version__); print('rclpy=ok')"
echo.

echo [OK] Environment isolation check passed.
echo      Gateway must use: %ISAAC_ENV_PYTHON%
echo      ROS Bridge must use: %ROS2_PYTHON%
