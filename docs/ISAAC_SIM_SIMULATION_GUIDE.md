# Isaac Sim 仿真环境使用指南

本文档说明如何使用 Isaac Sim 仿真环境验证移动端控制功能。

## 系统架构

```
┌─────────────┐    WebSocket     ┌──────────────┐    HTTP     ┌──────────────┐    ROS2     ┌─────────────┐
│  Mobile App │ ───────────────► │ Gateway Lite │ ──────────► │ ROS Bridge   │ ──────────► │  Isaac Sim  │
│  (摇杆/语音) │                  │  (WebRTC)    │             │    Lite      │  /cmd_vel   │  (仿真机器人) │
└─────────────┘                  └──────────────┘             └──────────────┘             └─────────────┘
       ▲                                ▲                           ▲                            │
       │                                │                           │                            │
       └────────────────────────────────┴───────────────────────────┘                            │
                                    视频流 (JPEG via /push_frame)                                │
                                                                                                │
                                    ┌───────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                            ┌──────────────────┐
                            │  video_bridge.py │
                            │  (摄像头 → JPEG) │
                            └──────────────────┘
```

## 前置要求

### 硬件要求
- NVIDIA GPU（建议 RTX 3060 或更高）
- 至少 16GB RAM
- 50GB+ 可用磁盘空间

### 软件要求
- Ubuntu 20.04/22.04 或 Windows 10/11
- NVIDIA Driver 525+
- ROS2 Humble 或 Iron
- Isaac Sim 4.0+

## 安装步骤

### 1. 安装 Isaac Sim

从 NVIDIA Omniverse 安装：
```bash
# 下载 Omniverse Launcher
# https://www.nvidia.com/en-us/omniverse/download/

# 在 Launcher 中安装 Isaac Sim
```

### 2. 安装 ROS2

```bash
# Ubuntu
sudo apt update && sudo apt install -y curl gnupg lsb-release
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
sudo apt update
sudo apt install ros-humble-desktop

# 安装 ROS2 包
sudo apt install ros-humble-geometry-msgs ros-humble-nav-msgs ros-humble-sensor-msgs
```

### 3. 安装 Python 依赖

```bash
# 使用 Isaac Sim 的 Python
<IsaacSim>/python.sh -m pip install httpx pillow numpy
```

### 4. 获取天工机器人 URDF

```bash
# 如果有官方 URDF，放到以下目录：
TGrobot4s/urdf/lite/urdf/humanoid_publish.urdf

# 或使用其他机器人 URDF
```

## 快速启动

### 方式一：一键启动（推荐）

```bash
# 启动完整仿真环境
cd TGrobot4s/isaac_sim
<IsaacSim>/python.sh simulation_launcher.py --urdf /path/to/robot.urdf
```

### 方式二：分步启动

```bash
# 终端1：启动 ROS Bridge Lite
cd TGrobot4s
python ros_bridge_lite/main.py

# 终端2：启动 Gateway Lite
python gateway_lite/main.py

# 终端3：启动 Isaac Sim 仿真
cd TGrobot4s/isaac_sim
<IsaacSim>/python.sh simulation_launcher.py --urdf /path/to/robot.urdf
```

### 方式三：无头模式（服务器）

```bash
<IsaacSim>/python.sh simulation_launcher.py --urdf /path/to/robot.urdf --headless
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--urdf` | URDF 文件路径 | 自动查找 |
| `--robot-version` | 机器人版本 (lite/pro/tiangong2pro) | lite |
| `--robot-prim` | 机器人 prim 路径 | /World/robot |
| `--fix-base` | 固定基座 | False |
| `--gateway-url` | Gateway URL | http://localhost:8088 |
| `--camera-fps` | 摄像头帧率 | 30.0 |
| `--headless` | 无头模式 | False |
| `--no-video` | 禁用视频流 | False |

## 验证测试

### 1. 验证 ROS2 通信

```bash
# 查看 ROS2 话题
ros2 topic list

# 应该看到：
# /cmd_vel
# /odom
# /joint_states

# 手动发送速度命令
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.5}, angular: {z: 0.0}}"

# 监听里程计
ros2 topic echo /odom
```

### 2. 验证 Gateway 连接

```bash
# 检查 Gateway 状态
curl http://localhost:8088/status

# 通过 HTTP 发送命令
curl -X POST http://localhost:8080/move -H "Content-Type: application/json" -d '{"linear": 0.5, "angular": 0.0}'
```

### 3. 移动端连接测试

1. 确保手机和 PC 在同一局域网
2. 在移动端 App 中配置 Gateway 地址：`http://<PC_IP>:8088`
3. 连接后，使用摇杆控制机器人
4. 观察仿真中的机器人是否移动

## 核心模块说明

### 1. ros2_control_bridge.py

ROS2 控制桥接，负责：
- 订阅 `/cmd_vel` 话题
- 控制仿真机器人移动
- 发布 `/odom` 和 `/joint_states`

```python
from isaac_sim.ros2_control_bridge import create_robot_controller

controller = create_robot_controller(
    robot_prim_path="/World/robot",
    cmd_vel_topic="/cmd_vel"
)

# 在仿真循环中更新
controller.update(dt)
```

### 2. video_bridge.py

视频流桥接，负责：
- 获取 Isaac Sim 摄像头图像
- 编码为 JPEG
- POST 到 Gateway `/push_frame`

```python
from isaac_sim.video_bridge import VideoBridge, VideoBridgeConfig

config = VideoBridgeConfig(
    gateway_url="http://localhost:8088",
    camera_id="main"
)

bridge = VideoBridge(config)
bridge.start()

# 在 asyncio 中运行发送循环
await bridge.send_loop()
```

### 3. simulation_launcher.py

一键启动脚本，整合所有组件。

## 故障排除

### 问题1：Isaac Sim 启动失败

```bash
# 检查 GPU 驱动
nvidia-smi

# 检查 Isaac Sim 安装
<IsaacSim>/python.sh -c "import isaacsim; print('OK')"
```

### 问题2：ROS2 节点无法创建

```bash
# 检查 ROS2 环境
source /opt/ros/humble/setup.bash
ros2 topic list

# 检查 RMW 实现
echo $RMW_IMPLEMENTATION
```

### 问题3：视频流无法推送

```bash
# 检查 Gateway 是否运行
curl http://localhost:8088/health

# 检查网络连接
ping <gateway_ip>
```

### 问题4：机器人不移动

1. 检查 `/cmd_vel` 是否有消息
2. 检查机器人 Articulation 是否正确创建
3. 检查物理仿真是否运行

## 性能优化

### 降低分辨率

```bash
<IsaacSim>/python.sh simulation_launcher.py --camera-fps 15
```

### 无头模式

```bash
<IsaacSim>/python.sh simulation_launcher.py --headless
```

### 禁用视频

```bash
<IsaacSim>/python.sh simulation_launcher.py --no-video
```

## 下一步

1. 获取天工机器人 URDF 文件
2. 配置机器人关节控制
3. 添加更多传感器（激光雷达、IMU）
4. 实现导航功能
