@echo off
setlocal

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
set "ROS2_SETUP_BAT=%ROS2_ROOT%\setup.bat"
set "ROS2_BASELINE_PATH=%ROS2_ENV_ROOT%;%ROS2_ENV_ROOT%\Library\mingw-w64\bin;%ROS2_ENV_ROOT%\Library\usr\bin;%ROS2_ENV_ROOT%\Library\bin;%ROS2_ENV_ROOT%\Scripts;%ROS2_ENV_ROOT%\bin;C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem"

echo ===== Recommended Runtime Split =====
echo [INFO] 9200 Isaac Sim should keep using its own kit/python runtime.
echo [INFO] 8080/9100 default HTTP RL env: %HTTP_RL_PYTHON%
echo [INFO] Legacy ROS2 path (only when FORCE_ROS2_HTTP_RL=1): %ROS2_PYTHON%
echo.

echo ===== Check HTTP RL Env (Conda) =====
if not exist "%HTTP_RL_PYTHON%" (
    echo [ERROR] Not found: %HTTP_RL_PYTHON%
    echo [HINT] Create it with:
    echo        scripts\create_http_rl_conda_env.cmd
    exit /b 1
)
"%HTTP_RL_PYTHON%" -c "import sys, aiohttp, aiortc, httpx, numpy, openvino, yaml, OpenSSL, cryptography; from PIL import Image; print('python=' + sys.executable); print('aiohttp=' + aiohttp.__version__); print('aiortc=' + aiortc.__version__); print('httpx=' + httpx.__version__); print('openvino=' + openvino.__version__); print('yaml=ok'); print('OpenSSL=ok'); print('cryptography=' + cryptography.__version__); print('Pillow=ok'); print('numpy=' + numpy.__version__)"
if errorlevel 1 exit /b 1
echo.

echo ===== Check Legacy ROS2 Env (Optional) =====
if not exist "%ROS2_SETUP_BAT%" (
    echo [WARN] ROS2 setup not found, skip legacy ROS2 check: %ROS2_SETUP_BAT%
    goto :done
)
if not exist "%ROS2_PYTHON%" (
    echo [WARN] ROS2 python not found, skip legacy ROS2 check: %ROS2_PYTHON%
    goto :done
)
call "%ROS2_SETUP_BAT%"
if errorlevel 1 (
    echo [WARN] Failed to load ROS2 env from: %ROS2_ROOT%
    goto :done
)
set "PATH=%ROS2_BASELINE_PATH%"
call "%ROS2_SETUP_BAT%"
if errorlevel 1 (
    echo [WARN] Failed to reload sanitized ROS2 env from: %ROS2_ROOT%
    goto :done
)
"%ROS2_PYTHON%" -c "import aiohttp, rclpy" >nul 2>nul
if errorlevel 1 (
    echo [WARN] ROS2 env check failed in %ROS2_PYTHON%
    echo [HINT] Verify in CMD:
    echo        cd /d C:\pixi_ws
    echo        pixi shell
    echo        call "%ROS2_SETUP_BAT%"
    echo        ros2 topic list
    goto :done
)
"%ROS2_PYTHON%" -c "import sys, aiohttp, rclpy; print('python=' + sys.executable); print('aiohttp=' + aiohttp.__version__); print('rclpy=ok')"
echo.

:done
echo [OK] Environment isolation check passed.
echo      8080/9100 should use: %HTTP_RL_PYTHON%
echo      Legacy ROS2 path stays at: %ROS2_PYTHON%
