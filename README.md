# SynEIAgent

独立运行的机器人网关，用于替代 nanobot 运行时。

当前版本覆盖你的核心业务：
- WebRTC 视频流连接
- DataChannel 控制（摇杆 + 语音意图）
- ROS 执行（`/cmd_vel` 或 `/joint_command` + `/set_motion_number`）

## 当前技术架构

```text
Android App
  -> WebRTC /signal
  -> DataChannel "control" (joystick / voice_intent / action)
  -> 本地ASR(推荐)

Gateway Lite
  -> WebRTC会话管理
  -> /push_frame 视频帧入口
  -> 控制状态机 + seq去重 + ACK + deadman
  -> 转发到 ROS Bridge Lite

ROS Bridge Lite
  -> POST /move   -> ROS2 /cmd_vel (兼容模式) 或 /joint_command (步态模式)
  -> POST /motion -> ROS2 /set_motion_number
```

## 控制状态机

- `IDLE`
- `JOYSTICK_ACTIVE`
- `VOICE_ACTION`
- `EMERGENCY_STOP`

优先级：`EMERGENCY_STOP > JOYSTICK > VOICE`

## 内置动作映射

- `wave_hand` -> `1`（挥手）
- `hand_shake` -> `2`（握手）
- `bow` -> `3`（鞠躬）
- `dance_1` -> `4`（跳舞1）
- `dance_2` -> `5`（跳舞2）

## 依赖库

### Gateway（pip）

- `aiohttp`
- `aiortc`
- `httpx`
- `numpy`
- `Pillow`
- `av`（通常由 aiortc 带入）

安装：

```bash
pip install -r requirements-gateway.txt
```

### ROS Bridge（ROS2 环境）

- `rclpy`
- `geometry_msgs`
- `hric_msgs`（来自你的机器人 SDK/工作区）

## 快速启动

1. 准备配置

```bash
copy config.example.json config.json
```

2. 启动 Gateway

```bash
python -m gateway_lite.main --config config.json
```

3. 启动 ROS Bridge Lite

```bash
python -m ros_bridge_lite.main --host 0.0.0.0 --port 8080
```

步态关节模式（推荐用于 Isaac Sim 关节驱动验证）：

```bash
python -m ros_bridge_lite.main --host 0.0.0.0 --port 8080 --control-mode joint_gait --joint-command-topic /joint_command --control-hz 50
```

4. 健康检查

```bash
curl http://127.0.0.1:9100/health
curl http://127.0.0.1:8080/health
```

## Windows 环境隔离启动（推荐）

为了避免 `python` 混用导致依赖冲突，推荐把运行时拆成三层：

- `9200 Isaac Sim`：继续使用 Isaac 自带 `kit/python`
- `8080 ROS Bridge Lite`：使用专门的 `conda` HTTP RL 环境
- `9100 Gateway Lite`：与 `8080` 共用同一个 `conda` HTTP RL 环境

先准备 HTTP RL 的独立环境：

```bat
scripts\create_http_rl_conda_env.cmd
```

然后再用仓库内的隔离脚本（CMD）：

1. 先做隔离检查

```bat
scripts\check_env_isolation.cmd
```

2. 在独立 CMD 窗口启动 ROS Bridge

```bat
scripts\start_ros_bridge_isolated.cmd
```

3. 在另一个独立 CMD 窗口启动 Gateway

```bat
scripts\start_gateway_isolated.cmd
```

4. 确认 `9200 Isaac Sim` 也按 Lite 执行层配置启动

```powershell
.\start_isaac_headless.ps1
curl http://127.0.0.1:9200/health
```

至少确认：
- `gain_profile` 是 `policy_config` 或 `official_lite`
- `limit_profile` 是 `official_lite`

完整说明见：
- `docs/WINDOWS_ENV_ISOLATION.md`

## 视频流适配联调

当机器人侧暂时没有直接对接脚本时，可先用本地摄像头或 RTSP 源验证 `WebRTC -> Mobile` 全链路。

1. 安装视频桥接依赖

```bash
pip install -r requirements-video-bridge.txt
```

2. 推送本地摄像头（`--source 0`）或 RTSP（`--source rtsp://...`）到 Gateway

```bash
python scripts/local_video_bridge.py --gateway http://127.0.0.1:9100 --source 0 --fps 15
```

## 独立运行校验

1. 安装依赖并启动服务：

```bash
pip install -r requirements-gateway.txt
python -m gateway_lite.main --config config.json
python -m ros_bridge_lite.main
```

2. 校验不依赖 nanobot 运行时：

```bash
python scripts/check_independence.py
```

## DataChannel 协议

App -> Gateway：

```json
{"type":"joystick","seq":1024,"x":0.1,"y":0.8,"ts":1710000000000,"request_id":"req-1"}
{"type":"voice_intent","seq":2001,"intent":"move","linear":0.35,"angular":0.0,"duration_ms":700}
{"type":"voice_intent","seq":2002,"intent":"action","action_id":"wave_hand"}
{"type":"voice_intent","seq":2003,"intent":"stop"}
```

Gateway -> App：

```json
{"type":"ack","seq":1024,"request_id":"req-1","reason":"accepted","source":"joystick"}
{"type":"event","name":"state_changed","state":"JOYSTICK_ACTIVE"}
{"type":"error","content":"unknown action_id"}
```

## 移动端语音动作适配入口

移动端语音动作映射已在 `ActionCatalog` 统一管理，按你的动作体系扩展即可：

- `TGrobot4s/mobile/app/src/main/java/com/tgrobot/mobile/domain/voice/ActionCatalog.kt`
- `TGrobot4s/mobile/app/src/main/java/com/tgrobot/mobile/domain/voice/VoiceIntentParser.kt`

## 本地语音查询（电量/配置/状态）

移动端支持本地语音业务查询，不依赖云端 LLM：
- “电量多少 / battery” -> 查询并回显电量字段（若后端未提供则提示 unknown）
- “配置参数 / config” -> 查询 deadman、joystick 频率、voice 时长等配置
- “当前状态 / status” -> 查询 sessions、视频帧统计、ROS bridge 健康

本地查询实现：
- `TGrobot4s/mobile/app/src/main/java/com/tgrobot/mobile/data/local/LocalRobotInfoService.kt`

## 架构梳理与语音规划文档

- [项目架构梳理与移动端语音控制方案](docs/PROJECT_ARCHITECTURE_AND_MOBILE_VOICE_PLAN.md)

