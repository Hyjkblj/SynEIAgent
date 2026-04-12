# SynEIAgent

独立运行的机器人网关，用于替代 nanobot 运行时。

当前版本覆盖你的核心业务：
- WebRTC 视频流连接
- DataChannel 控制（摇杆 + 语音意图）
- ROS 执行（`/cmd_vel` + `/set_motion_number`）

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
  -> POST /move   -> ROS2 /cmd_vel
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

4. 健康检查

```bash
curl http://127.0.0.1:9100/health
curl http://127.0.0.1:8080/health
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

## 架构梳理与语音规划文档

- [项目架构梳理与移动端语音控制方案](docs/PROJECT_ARCHITECTURE_AND_MOBILE_VOICE_PLAN.md)

