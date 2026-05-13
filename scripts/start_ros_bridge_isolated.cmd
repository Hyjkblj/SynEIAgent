@echo off
setlocal

if not defined PROJECT_ROOT set "PROJECT_ROOT=D:\Develop\Project\SynEIAgent"
set "DEFAULT_CONDA_BASE="
for /f "usebackq delims=" %%I in (`conda info --base 2^>nul`) do if not defined DEFAULT_CONDA_BASE set "DEFAULT_CONDA_BASE=%%I"
if not defined CONDA_BASE if defined DEFAULT_CONDA_BASE set "CONDA_BASE=%DEFAULT_CONDA_BASE%"
if not defined CONDA_BASE set "CONDA_BASE=D:\Develop\anaconda3"
set "DEFAULT_CONDA_ENVS_DIR="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$j = conda info --json ^| ConvertFrom-Json; if ($j.envs_dirs.Count -gt 0) { $j.envs_dirs[0] }" 2^>nul`) do if not defined DEFAULT_CONDA_ENVS_DIR set "DEFAULT_CONDA_ENVS_DIR=%%I"
if not defined CONDA_ENVS_DIR if defined DEFAULT_CONDA_ENVS_DIR set "CONDA_ENVS_DIR=%DEFAULT_CONDA_ENVS_DIR%"
if not defined CONDA_ENVS_DIR set "CONDA_ENVS_DIR=%CONDA_BASE%\envs"
if not defined HTTP_RL_ENV_NAME set "HTTP_RL_ENV_NAME=syn-ei-http-rl"
if not defined HTTP_RL_PYTHON set "HTTP_RL_PYTHON=%CONDA_ENVS_DIR%\%HTTP_RL_ENV_NAME%\python.exe"
if not defined ROS2_ROOT set "ROS2_ROOT=C:\pixi_ws\ros2-windows"
if not defined ROS2_ENV_ROOT set "ROS2_ENV_ROOT=C:\pixi_ws\.pixi\envs\default"
if not defined ROS2_PYTHON set "ROS2_PYTHON=%ROS2_ENV_ROOT%\python.exe"
if not defined COLCON_PYTHON_EXECUTABLE set "COLCON_PYTHON_EXECUTABLE=%ROS2_PYTHON%"
if not defined BRIDGE_PYTHON set "BRIDGE_PYTHON=%HTTP_RL_PYTHON%"
if not defined FORCE_ROS2_HTTP_RL set "FORCE_ROS2_HTTP_RL=0"
set "ROS2_SETUP_BAT=%ROS2_ROOT%\setup.bat"
set "ROS2_BASELINE_PATH=%ROS2_ENV_ROOT%;%ROS2_ENV_ROOT%\Library\mingw-w64\bin;%ROS2_ENV_ROOT%\Library\usr\bin;%ROS2_ENV_ROOT%\Library\bin;%ROS2_ENV_ROOT%\Scripts;%ROS2_ENV_ROOT%\bin;C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem"

set "HOST=0.0.0.0"
set "PORT=8080"
set "CMD_VEL_TOPIC=/cmd_vel"
set "JOINT_COMMAND_TOPIC=/joint_command"
set "SBUS_DATA_TOPIC=/sbus_data"
if not defined CONTROL_MODE set "CONTROL_MODE=rl_policy"
if not defined CONTROL_HZ set "CONTROL_HZ=400"
set "NODE_NAME=gateway_lite_bridge"
set "SET_MOTION_SERVICE=/set_motion_number"
if not defined POLICY_MODEL_XML set "POLICY_MODEL_XML=%PROJECT_ROOT%\DeployTienkug\Deploy_Tienkung\rl_control_new\config\policy\policy1107.xml"
if not defined POLICY_MODEL_BIN set "POLICY_MODEL_BIN=%PROJECT_ROOT%\DeployTienkug\Deploy_Tienkung\rl_control_new\config\policy\policy1107.bin"
if not defined POLICY_CONFIG set "POLICY_CONFIG=%PROJECT_ROOT%\DeployTienkug\Deploy_Tienkung\rl_control_new\config\tg22_http_sim.yaml"
if not defined ISAAC_SIM_URL set "ISAAC_SIM_URL=http://127.0.0.1:9200"
set "USE_HTTP_RL_NO_ROS2=0"
if /I "%CONTROL_MODE%"=="rl_policy" if not "%ISAAC_SIM_URL%"=="" if not "%FORCE_ROS2_HTTP_RL%"=="1" set "USE_HTTP_RL_NO_ROS2=1"

set "PYTHONNOUSERSITE=1"
set "PYTHONPATH="
set "PYTHONHOME="

if not exist "%PROJECT_ROOT%" (
    echo [ERROR] PROJECT_ROOT not found: %PROJECT_ROOT%
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

set "RL_ARGS="
if "%CONTROL_MODE%"=="rl_policy" (
    set "RL_ARGS=--policy-model-xml %POLICY_MODEL_XML% --policy-model-bin %POLICY_MODEL_BIN% --policy-config %POLICY_CONFIG% --simulation --isaac-sim-url %ISAAC_SIM_URL%"
)

if "%USE_HTTP_RL_NO_ROS2%"=="1" goto :start_http_rl_no_ros2

if not exist "%ROS2_SETUP_BAT%" (
    echo [ERROR] ROS2 setup.bat not found: %ROS2_SETUP_BAT%
    exit /b 1
)

if not exist "%ROS2_PYTHON%" (
    echo [ERROR] ROS2_PYTHON not found: %ROS2_PYTHON%
    exit /b 1
)

call "%ROS2_SETUP_BAT%"
if errorlevel 1 (
    echo [ERROR] Failed to load ROS2 env from: %ROS2_ROOT%
    exit /b 1
)
set "PATH=%ROS2_BASELINE_PATH%"
call "%ROS2_SETUP_BAT%"
if errorlevel 1 (
    echo [ERROR] Failed to reload sanitized ROS2 env from: %ROS2_ROOT%
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
"%ROS2_PYTHON%" -m ros_bridge_lite.main --host %HOST% --port %PORT% --cmd-vel-topic %CMD_VEL_TOPIC% --joint-command-topic %JOINT_COMMAND_TOPIC% --sbus-data-topic %SBUS_DATA_TOPIC% --control-mode %CONTROL_MODE% --control-hz %CONTROL_HZ% --node-name %NODE_NAME% --set-motion-service %SET_MOTION_SERVICE% %RL_ARGS%
exit /b %errorlevel%

:start_http_rl_no_ros2
cd /d "%PROJECT_ROOT%"

if /I not "%BRIDGE_PYTHON%"=="python" if not exist "%BRIDGE_PYTHON%" (
    echo [WARN] HTTP RL env python not found: %BRIDGE_PYTHON%
    echo [INFO] Falling back to PATH python for ROS Bridge HTTP RL mode.
    set "BRIDGE_PYTHON=python"
)

echo [INFO] HTTP RL no-ROS2 mode enabled. Set FORCE_ROS2_HTTP_RL=1 to keep the old ROS2 path.
echo [INFO] Bridge python:
"%BRIDGE_PYTHON%" -c "import sys; print(sys.executable)"
if errorlevel 1 exit /b 1

"%BRIDGE_PYTHON%" -c "import aiohttp, httpx, openvino, yaml, numpy" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Missing aiohttp, httpx, openvino, PyYAML, or numpy in %BRIDGE_PYTHON%.
    echo [HINT] Verify in CMD:
    echo        scripts\create_http_rl_conda_env.cmd
    echo [HINT] Or install directly:
    echo        "%BRIDGE_PYTHON%" -m pip install -r requirements-rl.txt
    exit /b 1
)
echo [INFO] aiohttp+httpx+openvino+yaml+numpy ok
echo [INFO] Starting ROS Bridge Lite on 8080 via HTTP RL transport...
"%BRIDGE_PYTHON%" -m ros_bridge_lite.main --host %HOST% --port %PORT% --cmd-vel-topic %CMD_VEL_TOPIC% --joint-command-topic %JOINT_COMMAND_TOPIC% --sbus-data-topic %SBUS_DATA_TOPIC% --control-mode %CONTROL_MODE% --control-hz %CONTROL_HZ% --node-name %NODE_NAME% --set-motion-service %SET_MOTION_SERVICE% %RL_ARGS%
exit /b %errorlevel%
