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
if not defined GATEWAY_PYTHON set "GATEWAY_PYTHON=%HTTP_RL_PYTHON%"
if not defined ISAAC_TEMP set "ISAAC_TEMP=D:\IsaacSim\temp"
if not defined ISAAC_PIP_CACHE set "ISAAC_PIP_CACHE=D:\IsaacSim\pip-cache"
if not defined CONFIG_FILE set "CONFIG_FILE=config.json"

set "PYTHONNOUSERSITE=1"
set "PYTHONPATH="
set "PYTHONHOME="
set "TEMP=%ISAAC_TEMP%"
set "TMP=%ISAAC_TEMP%"
set "PIP_CACHE_DIR=%ISAAC_PIP_CACHE%"
set "OMNI_KIT_ACCEPT_EULA=YES"

if not exist "%PROJECT_ROOT%" (
    echo [ERROR] PROJECT_ROOT not found: %PROJECT_ROOT%
    exit /b 1
)

if /I not "%GATEWAY_PYTHON%"=="python" if not exist "%GATEWAY_PYTHON%" (
    echo [WARN] HTTP RL env python not found: %GATEWAY_PYTHON%
    echo [INFO] Falling back to PATH python for gateway HTTP mode.
    set "GATEWAY_PYTHON=python"
)

if not exist "%ISAAC_TEMP%" mkdir "%ISAAC_TEMP%"
if not exist "%ISAAC_PIP_CACHE%" mkdir "%ISAAC_PIP_CACHE%"

set "EXISTING_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":9100 .*LISTENING"') do (
    set "EXISTING_PID=%%P"
    goto :found_gateway_port
)
goto :no_gateway_port

:found_gateway_port
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:9100/health' -TimeoutSec 2; if ($r.ok -eq $true) { exit 0 } else { exit 2 } } catch { exit 1 }" >nul 2>nul
if "%errorlevel%"=="0" (
    echo [INFO] Gateway is already running on port 9100. PID=%EXISTING_PID%
    echo [INFO] Health: http://127.0.0.1:9100/health
    exit /b 0
)
echo [ERROR] Port 9100 is already in use by PID=%EXISTING_PID%, but health check failed.
echo [HINT] Stop the process or change Gateway port in config.json.
exit /b 1

:no_gateway_port

if not exist "%PROJECT_ROOT%\%CONFIG_FILE%" (
    if exist "%PROJECT_ROOT%\config.example.json" (
        copy "%PROJECT_ROOT%\config.example.json" "%PROJECT_ROOT%\%CONFIG_FILE%" >nul
    ) else (
        echo [ERROR] Missing config file and config.example.json
        exit /b 1
    )
)

cd /d "%PROJECT_ROOT%"

echo [INFO] Gateway env python:
"%GATEWAY_PYTHON%" -c "import sys; print(sys.executable)"
if errorlevel 1 exit /b 1

echo [INFO] Verifying gateway runtime deps...
"%GATEWAY_PYTHON%" -c "import aiohttp, aiortc, httpx, numpy, OpenSSL, cryptography; from PIL import Image" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Missing gateway deps in %GATEWAY_PYTHON%.
    echo [HINT] Verify in CMD:
    echo        scripts\create_http_rl_conda_env.cmd
    echo [HINT] Or install directly:
    echo        "%GATEWAY_PYTHON%" -m pip install -r requirements-gateway.txt
    exit /b 1
)
echo [INFO] aiohttp+aiortc+httpx+numpy+Pillow ok

echo [INFO] Starting Gateway Lite on 9100...
"%GATEWAY_PYTHON%" -m gateway_lite.main --config "%CONFIG_FILE%"
exit /b %errorlevel%
