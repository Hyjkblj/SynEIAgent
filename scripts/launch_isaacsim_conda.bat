@echo off
setlocal

set "CONDA_ACTIVATE=D:\Develop\anaconda3\Scripts\activate.bat"
set "CONDA_ENV=D:\isaaclab_env"
set "ISAAC_EXE=D:\isaaclab_env\Scripts\isaacsim.exe"
set "ISAAC_TEMP=D:\IsaacSim\temp"
set "ISAAC_PIP_CACHE=D:\IsaacSim\pip-cache"

if not exist "%CONDA_ACTIVATE%" (
    echo [ERROR] conda activate script not found: %CONDA_ACTIVATE%
    exit /b 1
)

if not exist "%CONDA_ENV%\python.exe" (
    echo [ERROR] conda env python not found: %CONDA_ENV%\python.exe
    exit /b 1
)

if not exist "%ISAAC_EXE%" (
    echo [ERROR] isaacsim launcher not found: %ISAAC_EXE%
    exit /b 1
)

if not exist "%ISAAC_TEMP%" mkdir "%ISAAC_TEMP%"
if not exist "%ISAAC_PIP_CACHE%" mkdir "%ISAAC_PIP_CACHE%"

set "TEMP=%ISAAC_TEMP%"
set "TMP=%ISAAC_TEMP%"
set "PIP_CACHE_DIR=%ISAAC_PIP_CACHE%"
set "OMNI_KIT_ACCEPT_EULA=YES"

call "%CONDA_ACTIVATE%" "%CONDA_ENV%"
if errorlevel 1 (
    echo [ERROR] failed to activate conda env: %CONDA_ENV%
    exit /b 1
)

echo [INFO] Active env: %CONDA_ENV%
python -V

if "%~1"=="" (
    echo [INFO] Launching Isaac Sim...
    "%ISAAC_EXE%"
) else (
    echo [INFO] Running in env: %*
    %*
)

endlocal
