# Windows Environment Isolation (CMD)

Current recommendation on Windows is a three-layer runtime split:

1. `9200 Isaac Sim`
Use Isaac's bundled `kit/python` runtime only.

2. `8080 ROS Bridge Lite`
Use a dedicated `conda` env for the HTTP RL path.

3. `9100 Gateway Lite`
Use the same dedicated `conda` env as `8080`.

The legacy `Pixi + ROS2 Jazzy` runtime is kept only for the old ROS2 HTTP RL path and should not be the default path for simulation debugging.

## 0. Create the HTTP RL conda env

Open CMD in repo root and run:

```bat
scripts\create_http_rl_conda_env.cmd
```

This creates or updates:
- env name: `syn-ei-http-rl`
- env file: `environment-http-rl.yml`

Defaults:
- the scripts auto-resolve `CONDA_BASE` from `conda info --base`
- `HTTP_RL_ENV_NAME` defaults to `syn-ei-http-rl`
- `HTTP_RL_PYTHON` defaults to `%CONDA_BASE%\envs\%HTTP_RL_ENV_NAME%\python.exe`

If your paths are different, set env vars before running scripts:

```bat
set PROJECT_ROOT=D:\Develop\Project\SynEIAgent
set CONDA_BASE=D:\Develop\anaconda3
set HTTP_RL_ENV_NAME=syn-ei-http-rl
set HTTP_RL_PYTHON=D:\Develop\anaconda3\envs\syn-ei-http-rl\python.exe
set ROS2_ROOT=D:\Develop\ros2-jazzy-20260128-windows-release-amd64\ros2-windows
set ROS2_PYTHON=C:\pixi_ws\.pixi\envs\default\python.exe
```

## 1. One-time check

```bat
scripts\check_env_isolation.cmd
```

Expected:
- HTTP RL env prints the `python=` path inside `syn-ei-http-rl`
- It can import `aiohttp`, `aiortc`, `httpx`, `openvino`, `yaml`, `numpy`, and Pillow
- Final line: `[OK] Environment isolation check passed.`
- The ROS2 section is optional and only matters when you force the old ROS2 HTTP RL path

## 2. Start services in separate CMD windows

Window A (`8080` ROS bridge):

```bat
cd /d D:\Develop\Project\SynEIAgent
scripts\start_ros_bridge_isolated.cmd
```

Expected:
- `HTTP RL no-ROS2 mode enabled`
- `Starting ROS Bridge Lite on 8080 via HTTP RL transport`
- If already running, the script prints `ROS Bridge is already running on port 8080`

Window B (`9100` Gateway):

```bat
cd /d D:\Develop\Project\SynEIAgent
scripts\start_gateway_isolated.cmd
```

Expected:
- the detected python path points to `syn-ei-http-rl`
- `Starting Gateway Lite on 9100`
- If already running, the script prints `Gateway is already running on port 9100`

## 3. Verify the chain

In a third CMD:

```bat
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:9100/health
curl http://127.0.0.1:9200/health
```

Check:
- `8080` is healthy and `last_command_ok` stays true after commands
- `9100` is healthy and exposes the WebRTC/DataChannel session state
- `9200` is healthy before running long RL diagnostics
- for Lite RL validation, `9200/health` should report `gain_profile=policy_config`
- for Lite RL validation, `9200/health` should report `limit_profile=official_lite`

If you use the repo root launcher:

```powershell
.\start_isaac_headless.ps1
```

it now enables the official Lite actuator gain and effort/velocity limit
profiles by default. To A/B test back to policy-config gains, override before
launch:

```powershell
$env:ISAAC_ACTUATOR_GAIN_PROFILE = ""
.\start_isaac_headless.ps1
```

To A/B test without the explicit limit profile, override before launch:

```powershell
$env:ISAAC_ACTUATOR_LIMIT_PROFILE = ""
.\start_isaac_headless.ps1
```

## 4. Legacy ROS2 path

Only if you explicitly need the old ROS2 route:

```bat
set FORCE_ROS2_HTTP_RL=1
scripts\start_ros_bridge_isolated.cmd
```

That path still depends on:
- `C:\pixi_ws\.pixi\envs\default\python.exe`
- `D:\Develop\ros2-jazzy-20260128-windows-release-amd64\ros2-windows\setup.bat`

Keep ROS2-only dependencies in the ROS2 runtime. Do not mix them back into the HTTP RL conda env unless a dependency is truly shared.
