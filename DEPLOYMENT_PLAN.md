# 天工 Lite 落地方案（完整版）

> 基于对 SynEIAgent 全项目 + Deploy_Tienkung 仓库的完整阅读

---

## 1. 现状总结

### 已有的基础设施

```
SynEIAgent (本仓库)
├── Android App          — 摇杆 UI + 语音 + WebRTC
├── Gateway Lite         — WebRTC 会话 + 控制状态机 + deadman
├── ROS Bridge Lite      — HTTP->ROS2 桥接 (cmd_vel / joint_gait)
├── TGrobot4s/mobile     — Kotlin 移动端完整实现
├── TGrobot4s/robot      — 机器人侧 ROS2 工作区 (已安装)
│   ├── body_control     — 电机/IMU 驱动 (CAN + EtherCAT)
│   ├── usb_sbus         — 本地摇杆 USB 读取
│   ├── rl_control       — RL 步态控制器 (已编译, 含 OpenVINO)
│   ├── bodyctrl_msgs    — 电机/IMU 消息定义
│   └── proc_manager     — 进程管理器
└── DeployTienkug        — Deploy_Tienkung 开源仓库 (已确认适配 Lite)

机器人本体已安装的 ROS2 包:
  body_control → /leg/status, /arm/status, /imu/status (发布)
                /leg/cmd_ctrl, /arm/cmd_ctrl (订阅)
  usb_sbus    → /sbus_data (发布)
  rl_control  → 订阅 /sbus_data + /leg/status + /arm/status + /imu/status
                发布 /leg/cmd_ctrl + /arm/cmd_ctrl
```

### 核心矛盾

当前 SynEIAgent 的控制链路终点是：
```
App → Gateway → ROS Bridge → /cmd_vel 或 /joint_command (6 关节简化 gait)
```

天工 Lite 真机的控制链路终点是：
```
/sbus_data → rl_control → FSM(STOP/ZERO/MLP) → OpenVINO RL Policy → /leg/cmd_ctrl + /arm/cmd_ctrl
```

**两套链路的接口层完全不同**。当前 ROS Bridge 输出的 `/cmd_vel` 和 `/joint_command` 不在 rl_control 的输入范围内。

---

## 2. 落地方案：3 层改动

### 层级总览

| 层级 | 改什么 | 改几个文件 | 目的 |
|---|---|---|---|
| **L1: Deploy_Tienkung 修缮** | IMU 安全 + Launch remap | 2 文件, ~11 行 | 让 rl_control 安全可用 |
| **L2: ROS Bridge 新增模式** | `tienkung_remote_joy` 控制模式 | 1 文件, ~120 行 | 让远程摇杆指令变成 `/sbus_data` 兼容格式 |
| **L3: 机器人侧仲裁 Mux** | 本地/远程摇杆优先级 | 1 新文件 + 1 Launch, ~150 行 | 防止远程覆盖本地急停 |

---

## 3. L1: Deploy_Tienkung 修缮（必做）

### 改动 1.1: Launch 文件补 remap

**文件**: `DeployTienkug/Deploy_Tienkung/rl_control_new/launch/rl.launch.py`

```python
# 第 53-62 行, 为 joy_node 添加 remap
joy_node = Node(
    package='joy',
    executable='joy_node',
    name='joy_node',
    parameters=[{
        'device': '/dev/input/js0',
        'use_sim_time': LaunchConfiguration('use_sim_time'),
    }],
    remappings=[('/joy', '/sbus_data')],  # ← 新增这一行
    output='screen',
)
```

### 改动 1.2: IMU 超限强制急停

**文件**: `DeployTienkug/Deploy_Tienkung/rl_control_new/src/plugins/rl_control_new/src/RLControlNewPlugin.cpp`

删除第 308-317 行的空检查块，在第 425 行 `get_xbox_flag()` 之后插入：

```cpp
// IMU 安全检查 — 超限时强制急停
{
    double pitch = xsense_data(1);
    double roll = xsense_data(2);
    Eigen::Vector3d gyro_vec = xsense_data.segment<3>(3);
    double gyro_norm = gyro_vec.norm();
    if (std::abs(pitch) >= 0.8 || std::abs(roll) >= 0.8 ||
        gyro_norm > 5.0) {
        flag_.is_disable = 1;
        std::cout << "[IMU] Pitch=" << pitch << " Roll=" << roll
                  << " GyroNorm=" << gyro_norm << " -> Emergency Stop" << std::endl;
    }
}
```

---

## 4. L2: ROS Bridge 新增 `tienkung_remote_joy` 模式（必做）

### 设计思路

当前 ROS Bridge 有两种模式：
- `cmd_vel` → 发布 `geometry_msgs/Twist`
- `joint_gait` → 发布 `sensor_msgs/JointState`（6 关节简化 gait）

新增第三种模式：
- `tienkung_remote_joy` → 发布 `sensor_msgs/Joy` 到 `/sbus_data`

这样远程摇杆指令就能被 rl_control 直接消费，走完整的 FSM → RL Policy → 电机控制链路。

### 改动 2.1: `ros_bridge_lite/main.py`

在 `BridgeConfig` 中新增模式，在 `Ros2BridgeRuntime` 中新增处理逻辑：

```python
# BridgeConfig 新增
control_mode: str = "cmd_vel"  # cmd_vel | joint_gait | tienkung_remote_joy
sbus_data_topic: str = "/sbus_data"

# Ros2BridgeRuntime.__init__ 中新增分支
if cfg.control_mode == "tienkung_remote_joy":
    from sensor_msgs.msg import Joy
    self._joy_type = Joy
    self._joy_pub = self._node.create_publisher(Joy, cfg.sbus_data_topic, 100)

# Ros2BridgeRuntime.move() 中新增分支
if self.cfg.control_mode == "tienkung_remote_joy":
    msg = self._joy_type()
    msg.header.stamp = self._node.get_clock().now().to_msg()
    # 映射: linear → axes[1](前进), angular → axes[0](转向)
    # 云卓手柄 12 轴格式, 与 rl_control 中的映射对齐
    msg.axes = [0.0] * 12
    msg.buttons = [0] * 12
    msg.axes[0] = float(angular)   # y2 = 转向
    msg.axes[1] = float(linear)    # y1 = 前进
    msg.axes[2] = 0.0              # x1 = 横移
    msg.axes[3] = 0.0              # x2
    self._joy_pub.publish(msg)
    return True, "ok"
```

### 改动 2.2: FSM 状态切换命令

在 `ros_bridge_lite/main.py` 的 HTTP `/motion` 接口中，新增对天工 FSM 状态切换的支持：

```python
# 新增 HTTP 接口 /fsm_cmd
async def fsm_cmd(req: web.Request) -> web.Response:
    body = await req.json()
    cmd = body.get("cmd", "")  # gotoZero | gotoStop | gotoMLP
    ok, detail = runtime.send_fsm_command(cmd)
    return web.json_response({"success": ok, "detail": detail, "cmd": cmd})

# Ros2BridgeRuntime 新增方法
def send_fsm_command(self, cmd: str) -> tuple[bool, str]:
    if self.cfg.control_mode != "tienkung_remote_joy":
        return False, "not_in_tienkung_mode"
    # 通过 Joy 消息的 buttons 模拟摇杆按键
    msg = self._joy_type()
    msg.header.stamp = self._node.get_clock().now().to_msg()
    msg.axes = [0.0] * 12
    msg.buttons = [0] * 12
    if cmd == "gotoZero":
        msg.axes[11] = 1.0   # D 键
    elif cmd == "gotoStop":
        msg.axes[10] = 1.0   # C 键
    elif cmd == "gotoMLP":
        msg.axes[8] = 1.0    # A 键
        msg.axes[5] = 0.0    # G 键 = 0
    else:
        return False, f"unknown_cmd:{cmd}"
    self._joy_pub.publish(msg)
    return True, "ok"
```

### 改动 2.3: Gateway 新增 FSM 命令转发

**文件**: `gateway_lite/ros_client.py`

```python
class RosBridgeClient(Protocol):
    async def move(self, linear: float, angular: float) -> tuple[bool, str]: ...
    async def stop(self) -> tuple[bool, str]: ...
    async def motion(self, motion_number: int, active: bool = True) -> tuple[bool, str]: ...
    async def fsm_cmd(self, cmd: str) -> tuple[bool, str]: ...  # ← 新增

class HttpRosBridgeClient:
    async def fsm_cmd(self, cmd: str) -> tuple[bool, str]:
        return await self._post("/fsm_cmd", {"cmd": cmd})
```

**文件**: `gateway_lite/state.py`

在 `_handle_voice` 中新增意图处理：

```python
if intent == "walk":
    # 先 gotoZero, 再 gotoMLP
    out.commands.append(ControlCommand(kind=CommandKind.FSM_CMD, source="voice", fsm_cmd="gotoZero"))
    out.commands.append(ControlCommand(kind=CommandKind.FSM_CMD, source="voice", fsm_cmd="gotoMLP"))
    return
```

---

## 5. L3: 机器人侧摇杆仲裁 Mux（建议做）

### 问题

如果远程 App 和本地摇杆同时发布到 `/sbus_data`，rl_control 只会收到最后一个消息，无法区分来源，也无法保证本地急停优先。

### 方案

新增一个轻量 ROS2 节点 `sbus_mux`，订阅两个输入话题，仲裁后输出到 `/sbus_data`：

```
本地 usb_sbus → /sbus_data_hw ──┐
                                 ├→ [sbus_mux] → /sbus_data → rl_control
远程 App      → /sbus_data_remote ┘
```

优先级：`本地急停 > 本地摇杆 > 远程摇杆`

### 实现

**新文件**: `TGrobot4s/robot/sbus_mux/sbus_mux_node.py`

```python
#!/usr/bin/env python3
"""
sbus_mux: 本地/远程摇杆仲裁节点

优先级: 本地急停 > 本地摇杆 > 远程摇杆
"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
import time


class SbusMux(Node):
    def __init__(self):
        super().__init__('sbus_mux')
        
        # 本地摇杆 (usb_sbus)
        self.sub_local = self.create_subscription(
            Joy, '/sbus_data_hw', self._on_local, 100)
        # 远程摇杆 (SynEIAgent)
        self.sub_remote = self.create_subscription(
            Joy, '/sbus_data_remote', self._on_remote, 100)
        # 输出
        self.pub = self.create_publisher(Joy, '/sbus_data', 100)
        
        self._local_msg: Joy | None = None
        self._remote_msg: Joy | None = None
        self._local_ts: float = 0.0
        self._remote_ts: float = 0.0
        self._local_timeout: float = 0.5  # 本地 500ms 超时
        self._remote_timeout: float = 0.3  # 远程 300ms 超时
        
        self.timer = self.create_timer(0.01, self._tick)  # 100Hz
    
    def _on_local(self, msg: Joy):
        self._local_msg = msg
        self._local_ts = time.time()
    
    def _on_remote(self, msg: Joy):
        self._remote_msg = msg
        self._remote_ts = time.time()
    
    def _tick(self):
        now = time.time()
        local_alive = self._local_msg and (now - self._local_ts) < self._local_timeout
        remote_alive = self._remote_msg and (now - self._remote_ts) < self._remote_timeout
        
        # 优先级: 本地 > 远程
        if local_alive:
            self.pub.publish(self._local_msg)
        elif remote_alive:
            self.pub.publish(self._remote_msg)
        # 两者都超时则不发布 (rl_control 自身有安全机制)


def main():
    rclpy.init()
    node = SbusMux()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
```

**新文件**: `TGrobot4s/robot/sbus_mux/launch/sbus_mux.launch.py`

```python
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='sbus_mux',
            executable='sbus_mux_node',
            name='sbus_mux',
            output='screen',
        ),
    ])
```

---

## 6. 完整部署流程

### 6.1 机器人侧 (Ubuntu 22.04 + ROS2 Humble)

```bash
# 1. 编译 Deploy_Tienkung (含 L1 改动)
cd ~/Deploy_Tienkung
colcon build --packages-select rl_control_new x_humanoid_rl_sdk
source install/setup.bash

# 2. 启动机器人基础驱动
ros2 launch body_control body.launch.py
# 这会启动: body_control(电机/IMU) + usb_sbus(本地摇杆) + diagnose + power_board

# 3. 启动 sbus_mux (L3)
ros2 launch sbus_mux sbus_mux.launch.py

# 4. 启动 RL 步态控制器
ros2 launch rl_control rl.py
```

### 6.2 网关侧 (同一台机器人或局域网)

```bash
# 5. 启动 ROS Bridge (L2, tienkung 模式)
python -m ros_bridge_lite.main --control-mode tienkung_remote_joy --sbus-data-topic /sbus_data_remote --port 8080

# 6. 启动 Gateway
python -m gateway_lite.main --config config.json
```

### 6.3 移动端

```
Android App 连接 Gateway → WebRTC DataChannel → 摇杆/语音控制
```

---

## 7. 两种运行模式

| 模式 | 用途 | 启动方式 |
|---|---|---|
| **仿真模式** | Isaac Sim 联调 / UI 验证 | `ros_bridge_lite --control-mode joint_gait` |
| **真机模式** | 天工 Lite 真机步态控制 | `ros_bridge_lite --control-mode tienkung_remote_joy` |

---

## 8. 改动量汇总

| 层级 | 文件 | 改动类型 | 代码量 |
|---|---|---|---|
| L1 | `Deploy_Tienkung/rl.launch.py` | 修改 | +1 行 |
| L1 | `Deploy_Tienkung/RLControlNewPlugin.cpp` | 修改 | +10 行 |
| L2 | `ros_bridge_lite/main.py` | 修改 | +80 行 |
| L2 | `gateway_lite/ros_client.py` | 修改 | +5 行 |
| L2 | `gateway_lite/state.py` | 修改 | +15 行 |
| L2 | `gateway_lite/protocol.py` | 修改 | +5 行 |
| L3 | `TGrobot4s/robot/sbus_mux/` | 新增 | ~150 行 |

**总计: 4 个文件修改 + 2 个新文件, 约 266 行代码。**

---

## 9. 验证顺序

### Step 1: 本地验证 (不联网)

```bash
# 确认 body_control + usb_sbus 正常
ros2 topic echo /leg/status --once
ros2 topic echo /sbus_data --once

# 确认 rl_control 启动正常
ros2 launch rl_control rl.py
# 摇杆: D → ZERO, A+G → MLP, C → STOP
```

### Step 2: 远程摇杆验证

```bash
# 用 curl 模拟远程摇杆
curl -X POST http://127.0.0.1:8080/move -d '{"linear": 0.3, "angular": 0.0}' -H 'Content-Type: application/json'

# 确认 /sbus_data_remote 有消息
ros2 topic echo /sbus_data_remote --once

# 确认 sbus_mux 正确转发
ros2 topic echo /sbus_data --once
```

### Step 3: FSM 状态切换验证

```bash
# 远程触发 ZERO
curl -X POST http://127.0.0.1:8080/fsm_cmd -d '{"cmd": "gotoZero"}' -H 'Content-Type: application/json'

# 远程触发 MLP
curl -X POST http://127.0.0.1:8080/fsm_cmd -d '{"cmd": "gotoMLP"}' -H 'Content-Type: application/json'
```

### Step 4: App 端到端验证

```
Android App → 连接 → 摇杆前进 → 机器人迈步 → 松手停 → 急停
```

---

## 10. 不改的部分

| 组件 | 理由 |
|---|---|
| `body_control` | 已正确发布电机/IMU 数据 |
| `usb_sbus` | 已正确发布本地摇杆到 `/sbus_data` |
| `rl_control` (已安装版) | 已编译含 OpenVINO, 直接可用 |
| `bodyctrl_msgs` | 消息定义已正确 |
| Android App | 摇杆 UI + 语音已完整 |
| Gateway 控制状态机 | deadman / 仲裁 / seq 去重已完整 |
| Deploy_Tienkung 策略模型 | 已在 Lite 真机验证 |
| Deploy_Tienkung 关节映射 | 已适配 Lite |
| Deploy_Tienkung 串并联库 | 已适配 Lite |
