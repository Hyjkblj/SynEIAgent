@echo off
setlocal

if not defined PROJECT_ROOT set "PROJECT_ROOT=D:\Develop\Project\SynEIAgent"
if not defined HTTP_RL_ENV_NAME set "HTTP_RL_ENV_NAME=syn-ei-http-rl"
if not defined HTTP_RL_TEMP set "HTTP_RL_TEMP=%PROJECT_ROOT%\pip_cache\http-rl-temp"
if not defined HTTP_RL_PIP_CACHE set "HTTP_RL_PIP_CACHE=%PROJECT_ROOT%\pip_cache\http-rl-pip-cache"

set "DEFAULT_CONDA_BASE="
for /f "usebackq delims=" %%I in (`conda info --base 2^>nul`) do if not defined DEFAULT_CONDA_BASE set "DEFAULT_CONDA_BASE=%%I"
if not defined CONDA_BASE if defined DEFAULT_CONDA_BASE set "CONDA_BASE=%DEFAULT_CONDA_BASE%"
if not defined CONDA_BASE set "CONDA_BASE=D:\Develop\anaconda3"
set "DEFAULT_CONDA_ENVS_DIR="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$j = conda info --json ^| ConvertFrom-Json; if ($j.envs_dirs.Count -gt 0) { $j.envs_dirs[0] }" 2^>nul`) do if not defined DEFAULT_CONDA_ENVS_DIR set "DEFAULT_CONDA_ENVS_DIR=%%I"
if not defined CONDA_ENVS_DIR if defined DEFAULT_CONDA_ENVS_DIR set "CONDA_ENVS_DIR=%DEFAULT_CONDA_ENVS_DIR%"
if not defined CONDA_ENVS_DIR set "CONDA_ENVS_DIR=%CONDA_BASE%\envs"

set "ENV_FILE=%PROJECT_ROOT%\environment-http-rl.yml"
set "HTTP_RL_PYTHON=%CONDA_ENVS_DIR%\%HTTP_RL_ENV_NAME%\python.exe"

if not exist "%HTTP_RL_TEMP%" mkdir "%HTTP_RL_TEMP%"
if not exist "%HTTP_RL_PIP_CACHE%" mkdir "%HTTP_RL_PIP_CACHE%"

set "TEMP=%HTTP_RL_TEMP%"
set "TMP=%HTTP_RL_TEMP%"
set "PIP_CACHE_DIR=%HTTP_RL_PIP_CACHE%"

if not exist "%ENV_FILE%" (
    echo [ERROR] environment file not found: %ENV_FILE%
    exit /b 1
)

echo [INFO] TEMP=%TEMP%
echo [INFO] PIP_CACHE_DIR=%PIP_CACHE_DIR%

conda env list | findstr /B /C:"%HTTP_RL_ENV_NAME% " >nul 2>nul
if errorlevel 1 (
    echo [INFO] Creating conda env %HTTP_RL_ENV_NAME% from %ENV_FILE%
    conda env create -f "%ENV_FILE%"
) else (
    echo [INFO] Updating conda env %HTTP_RL_ENV_NAME% from %ENV_FILE%
    conda env update -n %HTTP_RL_ENV_NAME% -f "%ENV_FILE%" --prune
)
if errorlevel 1 exit /b 1

echo [INFO] Verifying HTTP RL env imports...
conda run -n %HTTP_RL_ENV_NAME% python -c "import sys, aiohttp, aiortc, httpx, numpy, openvino, yaml, OpenSSL, cryptography; from PIL import Image; print('python=' + sys.executable); print('aiohttp=' + aiohttp.__version__); print('aiortc=' + aiortc.__version__); print('httpx=' + httpx.__version__); print('openvino=' + openvino.__version__); print('yaml=ok'); print('OpenSSL=ok'); print('cryptography=' + cryptography.__version__); print('Pillow=ok'); print('numpy=' + numpy.__version__)"
if errorlevel 1 exit /b 1

echo.
echo [OK] HTTP RL conda env is ready.
echo [INFO] Python path: %HTTP_RL_PYTHON%
echo [INFO] start_ros_bridge_isolated.cmd and start_gateway_isolated.cmd will auto-detect this env by default.
exit /b 0
