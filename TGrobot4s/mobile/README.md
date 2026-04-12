# RobotF4s Mobile (Kotlin / Android)

当前移动端已重构为 `Kotlin + Jetpack Compose + WebRTC + OkHttp`，并按高内聚低耦合分层：

- `feature/control`：UI + ViewModel（状态编排）
- `domain/control`：控制算法（限频、平滑、急停、超时归零）
- `data`：`RobotRepository` 统一入口
- `core/realtime`：WebRTC / Signaling / Network Monitor
- `core/model`：领域模型与事件定义

## 与服务端协议对齐

- Signaling：`ws://<host>:<port>/signal`
- DataChannel label：`control`
- Offer：
  - `{"type":"offer","sdp":"...","chat_id":"...","sender_id":"..."}`
- ICE：
  - `{"type":"ice","candidate":{...}}`
- 控制消息（客户端 -> 服务端）：
  - `{"type":"joystick","x":...,"y":...,"linear":...,"angular":...}`
- 文本消息（客户端 -> 服务端）：
  - `{"type":"text","content":"..."}`
- 服务端事件（DataChannel -> 客户端）：
  - `message` / `message_delta` / `transcription` / `error` / `alert` / `joystick_ack`

## 关键控制策略

- 控制与视频解耦：视频走 WebRTC Track，控制走 DataChannel
- 控制采用状态流：周期发送当前控制状态，而不是按键事件
- 限频：默认 `20Hz`（`RateLimiter`）
- 平滑：一阶低通（`Smoother`）
- 安全：
  - 松手即零速（`ControlManager.release`）
  - 急停即零速（`ControlManager.emergencyStop`）
  - 超时归零（`SafetyController`，默认 500ms）

## 运行方式

1. 用 Android Studio 打开 `TGrobot4s/mobile`
2. 等待 Gradle 同步完成
3. 运行到真机或模拟器
4. 在 App 顶部填写机器人服务地址（host/port），点击“连接”

## 当前范围说明

- 已完成：控制链路重构（架构分层 + 信令 + DataChannel + 摇杆状态流）
- 视频显示：已接入 WebRTC 远端视频轨
- 可继续扩展：音频上行、更多状态指标（电量/温度/系统告警细分）
