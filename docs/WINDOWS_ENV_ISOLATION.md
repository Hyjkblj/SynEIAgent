# Windows Environment Isolation (CMD)

This project uses two isolated Python runtimes on Windows:

1. Gateway runtime (Isaac/Conda):
`D:\isaaclab_env\python.exe`
2. ROS bridge runtime (Pixi + ROS2 Jazzy):
`C:\pixi_ws\.pixi\envs\default\python.exe` with `D:\Develop\ros2-jazzy-20260128-windows-release-amd64\ros2-windows\setup.bat`

Do not run both services with plain `python` from an unknown shell.

If your paths are different, set env vars before running scripts:

```bat
set PROJECT_ROOT=D:\Develop\Project\SynEIAgent
set ROS2_ROOT=D:\Develop\ros2-jazzy-20260128-windows-release-amd64\ros2-windows
set ROS2_PYTHON=C:\pixi_ws\.pixi\envs\default\python.exe
set ISAAC_ENV_PYTHON=D:\isaaclab_env\python.exe
```

## 1. One-time check

Open CMD in repo root and run:

```bat
scripts\check_env_isolation.cmd
```

Expected:
- Gateway env prints `python=D:\isaaclab_env\python.exe`
- ROS env prints `python=C:\pixi_ws\.pixi\envs\default\python.exe`
- Final line: `[OK] Environment isolation check passed.`
- The RTI warning can be ignored if you use default DDS (`rmw_fastrtps_cpp` or `rmw_cyclonedds_cpp`).

## 2. Start services in separate CMD windows

Window A (ROS bridge):

```bat
cd /d D:\Develop\Project\SynEIAgent
scripts\start_ros_bridge_isolated.cmd
```

Expected:
- `ROS Bridge Lite ready on http://0.0.0.0:8080`
- If already running, script will print `ROS Bridge is already running on port 8080`.

Window B (Gateway):

```bat
cd /d D:\Develop\Project\SynEIAgent
scripts\start_gateway_isolated.cmd
```

Expected:
- Gateway health: `http://127.0.0.1:9100/health`
- If already running, script will print `Gateway is already running on port 9100`.

## 3. Verify the chain

In a third CMD:

```bat
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:9100/health
curl http://127.0.0.1:9100/status
```

Check:
- ROS bridge shows `ros_enabled: true`
- Gateway is healthy and has active sessions after app connects

## 4. If ROS bridge says aiohttp missing

Install only into the ROS2 runtime:

```bat
C:\pixi_ws\.pixi\envs\default\python.exe -m pip install aiohttp
```

Do not install ROS bridge dependencies into `D:\isaaclab_env` unless needed by Gateway.
