# SynEIAgent 项目架构梳理与移动端语音控制方案

## 1. 项目定位

当前项目业务目标：
- 将机器人视频流实时推送到移动端。
- 将移动端控制指令（摇杆/语音）安全、低延迟地转发到机器人 ROS 控制接口。
- 在不依赖 nanobot 运行时的前提下，独立运行网关与 ROS 桥接。

当前代码状态：
- 视频流链路已具备：`/push_frame -> WebRTC VideoTrack -> Mobile`。
- 控制链路已具备：`DataChannel(control) -> ControlRouter -> ROS Bridge`。
- 语音入口已具备协议支撑：`voice_intent` 与 `text` 消息已在网关侧实现解析。

## 2. 当前架构（已落地）

### 2.1 总体链路

```text
Mobile App (Android)
  -> WebSocket signaling (/signal)
  -> WebRTC PeerConnection
  -> DataChannel "control" 发送 joystick / text / voice_intent
  -> 接收远端视频轨 + ACK/Event

Gateway Lite (aiohttp + aiortc)
  -> PeerSession 管理
  -> SharedVideoTrack 接收 /push_frame 的 JPEG
  -> ControlRouter 状态机 + SafetyGuard 限幅 + deadman watchdog
  -> HttpRosBridgeClient 调用 ROS Bridge Lite

ROS Bridge Lite (aiohttp + rclpy)
  -> POST /move   -> ROS2 /cmd_vel
  -> POST /motion -> ROS2 /set_motion_number
```

### 2.2 模块职责映射

- 网关入口与会话管理：`gateway_lite/server.py`
  - 路由：`/signal`、`/health`、`/status`、`/push_frame`。
  - 维护 `PeerSession`、DataChannel 收发、ICE 交换、watchdog 任务。
- 控制状态机：`gateway_lite/state.py`
  - 状态：`IDLE / JOYSTICK_ACTIVE / VOICE_ACTION / EMERGENCY_STOP`。
  - 语音与摇杆仲裁、`seq` 去重、急停锁定、动作映射（`wave_hand` 等）。
- 安全限制：`gateway_lite/safety.py`
  - 速度限幅、摇杆归一化映射、语音动作时长钳制。
- ROS 调用客户端：`gateway_lite/ros_client.py`
  - `move/stop/motion` 转 HTTP（或 mock）。
- 视频轨实现：`gateway_lite/video_track.py`
  - 接收 JPEG、队列丢帧策略（满队列丢旧帧）、统计指标输出。
- ROS 桥服务：`ros_bridge_lite/main.py`
  - 提供 `/move`、`/motion`、`/health`，并写入 ROS2 topic/service。
- 移动端实时通信：`TGrobot4s/mobile/app/src/main/java/com/tgrobot/mobile/core/realtime`
  - `WebRtcRealtimeTransport` 建链、DataChannel 收发、视频轨接收。
- 移动端控制循环：`.../domain/control` + `.../feature/control/TeleopViewModel.kt`
  - 20Hz 限频、平滑、超时归零、急停、UI 与链路状态管理。

### 2.3 当前控制协议（与代码一致）

App -> Gateway：

```json
{"type":"joystick","seq":1024,"x":0.1,"y":0.8,"ts":1710000000000,"request_id":"req-1"}
{"type":"voice_intent","seq":2001,"intent":"move","linear":0.35,"angular":0.0,"duration_ms":700}
{"type":"voice_intent","seq":2002,"intent":"action","action_id":"wave_hand"}
{"type":"text","content":"前进"}
```

Gateway -> App：

```json
{"type":"ack","seq":1024,"request_id":"req-1","reason":"accepted","source":"joystick"}
{"type":"event","name":"state_changed","state":"JOYSTICK_ACTIVE"}
{"type":"error","content":"unknown action_id"}
```

## 3. 移动端语音操控落地方案

### 3.1 推荐方案（优先）

推荐将语音识别放在移动端本地完成，再发送结构化 `voice_intent` 给网关。

优点：
- 延迟更低，弱网更稳定。
- 网关改动最小（当前已支持 `voice_intent`）。
- 安全边界清晰（所有动作仍经过 `ControlRouter + SafetyGuard`）。

### 3.2 端到端流程

```text
按住说话 / 唤醒词
  -> Android ASR (本地或云)
  -> IntentParser (文本 -> intent/参数)
  -> DataChannel 发送 voice_intent
  -> Gateway ControlRouter 仲裁与限幅
  -> ROS Bridge 执行
  -> ACK/Event 回传到 App UI
```

### 3.3 移动端建议新增模块

建议在 `TGrobot4s/mobile/app/src/main/java/com/tgrobot/mobile` 增加：
- `feature/voice/VoiceController.kt`
  - 麦克风会话状态、开始/停止录音、权限管理。
- `feature/voice/AsrEngine.kt`
  - 封装 Android SpeechRecognizer（MVP 可先用系统能力）。
- `domain/voice/VoiceIntentParser.kt`
  - 规则映射：`“前进” -> intent=move, linear=0.35` 等。
- `data/RobotRepository` 扩展 `sendVoiceIntent(...)`
  - 从 `sendText` 升级为结构化语义发送，降低网关歧义解析成本。

### 3.4 网关侧建议（最小改动）

当前网关已支持 `voice_intent` 和 `text`，MVP 可以不改网关逻辑。

建议增量优化：
- 给语音 `ack` 增加 `request_id` 回传一致性（便于 UI 精确追踪）。
- 在 `/status` 中补充最近语音执行统计（成功/拒绝原因）。
- 增加语音命令黑白名单配置（可按场景禁用高风险动作）。

## 4. 分阶段实施计划

### M1（1-2 天）：语音最小可用
- App 接入麦克风权限 + ASR 文本输出。
- 先复用 `sendText`，验证“说话 -> 动作”闭环。

### M2（2-3 天）：结构化意图
- App 增加 `VoiceIntentParser`，发送 `voice_intent`。
- 补充 seq/request_id 与 ACK 对齐。

### M3（2 天）：安全与可观测
- 增加“按住说话”与“急停优先”交互。
- 记录语音命令成功率、拒绝原因、平均往返时延。

### M4（持续）：体验与鲁棒性
- 方言/噪声容错优化。
- 唤醒词与多轮对话（可选）。
- 高风险动作增加确认策略（例如“请确认执行跳舞”）。

## 5. 风险与对策

- 语音误识别导致误动作：
  - 对策：动作类命令走白名单 + 高风险二次确认。
- 网络抖动造成控制延迟：
  - 对策：保持 DataChannel 控制通道、ACK 监控、超时自动 stop。
- 语音与摇杆冲突：
  - 对策：沿用当前优先级策略（急停 > 摇杆 > 语音）。

---

该方案可在不重构后端核心的情况下推进移动端语音控制，优先复用现有 `ControlRouter` 与安全机制，降低实施风险与交付周期。
