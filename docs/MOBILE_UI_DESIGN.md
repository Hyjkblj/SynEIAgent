# TGrobot4s 移动端 UI 设计文档

## 一、整体架构

移动端采用 **Jetpack Compose** 构建原生 Android 应用，主要包含两个核心界面：

1. **连接界面 (ConnectScreen)** - 机器人连接配置
2. **驾驶界面 (DriveScreen)** - 实时遥控操作主界面

---

## 二、界面设计图

### 2.1 连接界面 (ConnectScreen)

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│                                                         │
│                                                         │
│              ┌───────────────────────────┐              │
│              │                           │              │
│              │      Robot Control        │              │
│              │                           │              │
│              │  ┌───────────┬────────┐   │              │
│              │  │ Host / IP │ Port   │   │              │
│              │  │192.168.41.1│ 9100  │   │              │
│              │  └───────────┴────────┘   │              │
│              │                           │              │
│              │   Ready to connect        │              │
│              │                           │              │
│              │  ┌─────────────────────┐  │              │
│              │  │      Connect        │  │              │
│              │  └─────────────────────┘  │              │
│              │                           │              │
│              └───────────────────────────┘              │
│                                                         │
│                                                         │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**组件说明：**

| 组件 | 功能 | 状态显示 |
|------|------|----------|
| Host/IP 输入框 | 输入机器人网关地址 | 默认: 192.168.41.1 |
| Port 输入框 | 输入信令端口 | 默认: 9100 |
| 状态文本 | 显示连接状态 | Ready to connect / Connecting... / Connected / Failed |
| Connect 按钮 | 发起连接 | 仅在 DISCONNECTED 或 FAILED 状态可用 |

**连接状态流转：**

```
DISCONNECTED → CONNECTING_SIGNAL → SIGNAL_CONNECTED → PEER_CONNECTING → DATA_CHANNEL_OPEN
                                    ↓
                                  FAILED
```

---

### 2.2 驾驶界面 (DriveScreen) - 主控制界面

```
┌─────────────────────────────────────────────────────────┐
│ ┌──────┐                              ┌──────────────┐ │
│ │●LIVE │ Disconnect                   │ Latency  45ms│ │
│ └──────┘                              │ Battery  78% │ │
│                                       │ VOICE LISTENING│
│         ┌─────────────────┐           └──────────────┘ │
│         │   Camera: head  ▼│                            │
│         └─────────────────┘                            │
│                                                         │
│                                                         │
│                    ┌─────────────────┐                  │
│                    │                 │                  │
│                    │   VIDEO FEED    │                  │
│                    │   (WebRTC)      │                  │
│                    │                 │                  │
│                    │   机器人第一视角  │                  │
│                    │                 │                  │
│                    └─────────────────┘                  │
│                                                         │
│                                                         │
│ ┌───────────┐                          ┌─────────────┐ │
│ │           │                          │   Voice     │ │
│ │  JOYSTICK │                          ├─────────────┤ │
│ │     ○     │                          │   Chat      │ │
│ │  (虚拟摇杆)│                          ├─────────────┤ │
│ │           │                          │  ┌───────┐  │ │
│ └───────────┘                          │  │E-STOP │  │ │
│                                        │  └───────┘  │ │
│         ┌─────────────────────┐        └─────────────┘ │
│         │ L 0.35 m/s  A 0.12 r/s│                        │
│         └─────────────────────┘                        │
└─────────────────────────────────────────────────────────┘
```

**布局层级：**

| 层级 | 内容 | 位置 |
|------|------|------|
| Layer 0 | 视频背景 (全屏) | 填充整个屏幕 |
| Layer 1 | HUD 控件叠加层 | 在视频上方 |

---

### 2.3 HUD 组件详细设计

#### 左上角 (TopLeftHud)

```
┌────────────────────────────────┐
│ ● LIVE   [Disconnect]          │
└────────────────────────────────┘
```

- 绿色圆点指示器 (10dp)
- "LIVE" 文字 (白色加粗)
- Disconnect 按钮 (半透明黑色背景)

#### 右上角 (TopRightHud)

```
┌──────────────────┐
│ Latency    45ms  │
│ Battery    78%   │
│ VOICE LISTENING  │  ← 仅在语音激活时显示
│ VOICE UNAVAILABLE│  ← 仅在语音不可用时显示
│ NO NETWORK       │  ← 仅在网络断开时显示
└──────────────────┘
```

#### 顶部中央 (CameraSelectorDropdown)

```
┌─────────────────────┐
│ Camera: head     ▼ │
└─────────────────────┘
        ↓ 点击展开
┌─────────────────────┐
│ * head              │  ← 当前选中 (绿色)
│   chest             │
│   left_hand         │
│   right_hand        │
└─────────────────────┘
```

#### 左下角 (JoystickView)

```
        ┌─────────────────┐
        │                 │
        │    ╭───────╮    │
        │   ╱         ╲   │
        │  │     ○     │  │  ← 可拖动的控制球
        │   ╲         ╱   │
        │    ╰───────╯    │
        │                 │
        └─────────────────┘
```

**摇杆交互：**

- 拖动控制球发送 `(linear, angular)` 命令
- X轴: angular (旋转速度) [-1, 1]
- Y轴: linear (线速度) [-1, 1]
- 松开自动归零并发送停止命令

#### 右下角控制区

```
┌─────────────┐
│   Voice     │  ← 语音控制按钮
├─────────────┤
│   Chat      │  ← 聊天面板开关
├─────────────┤
│  ┌───────┐  │
│  │E-STOP │  │  ← 紧急停止 (红色醒目)
│  └───────┘  │
└─────────────┘
```

#### 底部中央 (SpeedReadout)

```
┌─────────────────────────────┐
│  L 0.35 m/s    A 0.12 r/s   │
└─────────────────────────────┘
```

- L: 线速度 (linear velocity)
- A: 角速度 (angular velocity)
- 运动时背景加深高亮

---

### 2.4 聊天面板 (ChatOverlay)

点击 Chat 按钮后从底部滑入：

```
┌─────────────────────────────────────────┐
│                                         │
│  User: 前进两米                          │  ← 蓝色
│  Robot: 已执行前进命令                   │  ← 绿色
│  System: 连接已建立                      │  ← 半透明白色
│                                         │
├─────────────────────────────────────────┤
│ ┌───────────────────────────┬───────┐   │
│ │ Send a command...         │ Send  │   │
│ └───────────────────────────┴───────┘   │
└─────────────────────────────────────────┘
```

**消息角色颜色：**

| 角色 | 颜色 | 用途 |
|------|------|------|
| USER | #90CAF9 (蓝色) | 用户输入的命令 |
| ROBOT | #A5D6A7 (绿色) | 机器人响应 |
| SYSTEM | 白色半透明 | 系统消息 |

---

### 2.5 语音测试对话框 (VoiceTestDialog)

```
┌─────────────────────────────────────┐
│                                     │
│         语音识别测试                 │
│                                     │
│  ● 正在识别...                       │
│  ─────────────────────────────────  │
│                                     │
│  实时结果                           │
│  前进两米                           │  ← 青色
│                                     │
│  最终结果                           │
│  前进两米                           │  ← 蓝色加粗
│                                     │
│                          [关闭]     │
│                                     │
└─────────────────────────────────────┘
```

**状态指示：**

| 状态 | 指示灯颜色 |
|------|-----------|
| 正在识别 | 绿色 (#4CAF50) |
| 已停止 | 灰色 |
| 错误 | 红色 |

---

## 三、设计规范

### 3.1 颜色方案

| 用途 | 颜色值 | 说明 |
|------|--------|------|
| 背景 | 黑色 | 视频背景 |
| HUD背景 | 黑色 45% 透明 | 控件叠加层 |
| 主色调 | Material3 主题色 | 按钮、强调 |
| 成功/在线 | #4CAF50 | 连接成功、LIVE指示 |
| 错误/警告 | #D32F2F | E-STOP、错误状态 |
| 用户消息 | #90CAF9 | 聊天气泡 |
| 机器人消息 | #A5D6A7 | 聊天气泡 |

### 3.2 尺寸规范

| 组件 | 尺寸 |
|------|------|
| 摇杆 | 180dp |
| E-STOP 按钮 | 120dp × 56dp |
| HUD 圆角 | 8-16dp |
| 状态指示点 | 10dp |
| 摇杆控制球 | 25dp (14% of base) |

### 3.3 字体规范

| 用途 | 大小 | 字重 |
|------|------|------|
| 标题 | headlineSmall | Bold |
| HUD标签 | 11sp | Normal |
| HUD数值 | 11sp | Medium |
| E-STOP | 16sp | ExtraBold |
| 聊天消息 | 12sp | Normal |

---

## 四、交互流程

### 4.1 连接流程

```
用户输入 Host:Port → 点击 Connect → 显示 "Connecting..." 
    → WebRTC 信令协商 → DataChannel 建立 → 进入 DriveScreen
```

### 4.2 控制流程

```
拖动摇杆 → onJoystickInput(x, y) → ControlEngine 处理 
    → 发送 TeleopCommand(linear, angular) → 机器人执行
```

### 4.3 语音控制流程

```
点击 Voice → VoiceModule 启动 ASR → 实时显示 partialText 
    → 识别完成 → 意图解析 → 发送对应 command_id
```

---

## 五、技术实现

### 5.1 核心组件

| 文件 | 职责 |
|------|------|
| `TeleopScreen.kt` | 主界面 Composable |
| `TeleopViewModel.kt` | UI 状态管理 |
| `TeleopCoordinator.kt` | 业务逻辑协调 |
| `JoystickView` | 虚拟摇杆控件 |
| `VideoBackground` | WebRTC 视频渲染 |
| `ChatOverlay` | 聊天面板 |

### 5.2 状态管理

```kotlin
data class TeleopUiState(
    val host: String,                    // 网关地址
    val port: String,                    // 端口
    val connectionState: RobotConnectionState,  // 连接状态
    val remoteVideoTrack: VideoTrack?,   // 视频轨道
    val videoStreams: Map<String, VideoStream>, // 多相机流
    val primaryCameraId: String,         // 当前相机
    val lastCommand: TeleopCommand,      // 最后发送的命令
    val isVoiceListening: Boolean,       // 语音状态
    val messages: List<UiMessage>,       // 聊天消息
    // ...
)
```

---

## 六、多相机支持

应用支持多路视频流切换：

```kotlin
data class VideoStream(
    val cameraId: String,      // 相机ID: head, chest, left_hand, right_hand
    val displayName: String,   // 显示名称
    val isAvailable: Boolean,  // 是否可用
    val order: Int,            // 排序优先级
)
```

用户可通过顶部下拉菜单切换不同视角。

---

## 七、安全设计

1. **E-STOP 紧急停止** - 大红色按钮，随时可见，一键停止所有运动
2. **连接状态指示** - 实时显示延迟、电量、网络状态
3. **语音状态提示** - 明确显示语音识别状态和错误

---

## 八、参考文件

- `TGrobot4s/mobile/app/src/main/java/com/tgrobot/mobile/feature/control/TeleopScreen.kt`
- `TGrobot4s/mobile/app/src/main/java/com/tgrobot/mobile/feature/control/TeleopUiState.kt`
- `TGrobot4s/mobile/app/src/main/java/com/tgrobot/mobile/feature/control/CameraSelectorDropdown.kt`
- `TGrobot4s/mobile/app/src/main/java/com/tgrobot/mobile/feature/voice/VoiceTestDialog.kt`
- `TGrobot4s/docs/frontend_architecture.md`
- `TGrobot4s/docs/interface_design.md`
