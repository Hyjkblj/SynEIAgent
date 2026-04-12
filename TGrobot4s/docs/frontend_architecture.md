# 前端技术选型与架构设计

面向 **移动端控制**：实时视频（WebRTC）、控制指令（HTTP/WebSocket）、语音控制、大招/技能按钮、可选 3D 预览。

---

## 一、技术选型

### 1. 应用形态

| 方案 | 优点 | 缺点 | 建议 |
|------|------|------|------|
| **PWA / 响应式 Web** | 一套代码多端、迭代快、无需应用商店、易与 WebRTC/HTTP 集成 | 依赖浏览器、部分系统权限受限 | **首选**：比赛快速落地、与 Cursor/后端对接简单 |
| React Native | 原生体验、推送/传感器好 | 双端维护、WebRTC 需原生模块 | 若强需求原生包、深度系统集成时考虑 |
| Flutter | 性能好、UI 一致 | 生态内 WebRTC 方案相对少、学习成本 | 团队已用 Flutter 可选用 |
| 原生 (Swift/Kotlin) | 性能与系统能力最强 | 开发周期长、双端两套 | 非首选 |

**推荐**：**PWA（Progressive Web App）**，技术栈 **React + TypeScript + Vite**，移动端浏览器全屏使用，可“添加到主屏幕”当类 App 用。

---

### 2. 核心技术栈

| 能力 | 选型 | 说明 |
|------|------|------|
| **框架** | React 18+ | 组件化、生态成熟、与 Agent/后端联调方便 |
| **语言** | TypeScript | 类型安全、接口与 command_id 等可集中定义 |
| **构建** | Vite | 快、适合 PWA、ESM 友好 |
| **状态** | Zustand 或 React Context + useReducer | 轻量，控制状态、连接状态、视频状态集中管理 |
| **样式** | Tailwind CSS 或 CSS Modules | 快速做响应式、移动端适配 |
| **HTTP/控制** | fetch + 可选 axios | 发 command_id、查状态；长连接用 WebSocket |
| **WebSocket** | 原生 `WebSocket` 或 `socket.io-client` | 实时控制、状态推送、可选作为控制通道 |
| **WebRTC** | 原生 RTCPeerConnection 或 **simple-peer** / **react-native-webrtc**（若 RN） | 接收机器人端视频/音频流，低延迟 |
| **视频渲染** | `<video autoplay playsInline>` 绑定 WebRTC 的 MediaStream | 环太平洋式第一视角；移动端务必 `playsInline` |
| **语音** | Web Speech API (SpeechRecognition) 或 云端 ASR API | 语音 → 文本 → 意图 → command_id |
| **PWA** | vite-plugin-pwa (Workbox) | 离线缓存、可安装、图标与 manifest |

---

### 3. 关键库推荐

```text
React + TypeScript + Vite
├── zustand              # 状态（连接状态、当前 command、视频是否就绪）
├── simple-peer          # 或原生 WebRTC 封装，用于接收视频流
├── socket.io-client     # 可选，与后端/真机网关长连接
├── vite-plugin-pwa      # PWA 支持
├── tailwindcss          # 样式
└── @types/webrtc        # TypeScript 类型
```

- **不推荐** 为比赛阶段引入过重的状态机（如 XState）或复杂架构，保持「连接层 + 控制层 + UI 层」清晰即可。

---

## 二、架构设计

### 1. 分层架构

```text
┌─────────────────────────────────────────────────────────────┐
│  UI 层 (Views / Components)                                  │
│  视频区、摇杆/按钮、大招按钮、语音按钮、状态栏、设置           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  控制层 (Hooks / Controllers)                                │
│  useControlCommands、useVideoStream、useVoice、useConnection │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  连接层 (Services / Adapters)                                │
│  ControlAPI (HTTP/WS)、WebRTCService、VoiceService            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  后端 / 真机网关                                             │
│  REST 发 command_id、WebSocket 状态、WebRTC 信令+媒体        │
└─────────────────────────────────────────────────────────────┘
```

- **连接层**：只关心「发 command」「收状态」「建 WebRTC/收流」。
- **控制层**：把连接层封装成 React Hooks，供 UI 调用。
- **UI 层**：只调用 Hooks、展示状态，不直接碰 WebRTC/HTTP 细节。

---

### 2. 目录结构（推荐）

```text
mobile/
├── app/                    # 或 src/
│   ├── components/         # 通用组件
│   │   ├── VideoStream.tsx       # 第一视角视频（绑 WebRTC 流）
│   │   ├── ControlPad.tsx        # 方向/摇杆
│   │   ├── SkillButton.tsx       # 大招/技能按钮
│   │   └── StatusBar.tsx         # 连接状态、电量等
│   ├── hooks/
│   │   ├── useControl.ts         # 发 command_id
│   │   ├── useVideoStream.ts     # WebRTC 拉流、状态
│   │   ├── useVoice.ts           # 语音识别 → command
│   │   └── useConnection.ts      # 连接状态、重连
│   ├── services/
│   │   ├── controlApi.ts         # HTTP/WS 发指令
│   │   ├── webrtcService.ts      # 信令 + 接流
│   │   └── voiceService.ts       # 语音 → 文本/意图
│   ├── store/
│   │   └── appStore.ts           # Zustand：connected, streamReady, lastCommand
│   ├── types/
│   │   └── commands.ts           # CommandId 联合类型、API 入参
│   ├── App.tsx
│   └── main.tsx
├── public/
│   ├── manifest.json
│   └── icons/
├── index.html
├── vite.config.ts
├── tailwind.config.js
└── package.json
```

---

### 3. 数据流（核心）

- **发控制指令**  
  - 用户点击「大招」或摇杆 → `useControl().sendCommand(command_id, params?)` → `controlApi.post('/api/command', { command_id, ... })` → 后端/真机执行。
- **视频**  
  - 后端/机器人端推送 SDP/ICE（信令）→ 前端 `webrtcService` 建 `RTCPeerConnection`，收到 `track` → 挂到 `<video srcObject={stream}>`。
- **语音**  
  - 用户按住说话 → `useVoice()` 调 Web Speech 或云端 ASR → 文本 → 简单规则或调用后端「意图接口」得到 `command_id` → 再走 `sendCommand`。
- **状态**  
  - 可选：WebSocket 收机器人状态（电量、当前模式、错误码）→ 写入 Zustand → UI 展示。

---

### 4. 接口约定（与后端/真机网关）

- **发指令**  
  - `POST /api/command`  
  - Body: `{ "command_id": "skill_tieshankao" | "move_fwd" | ... , "params": {} }`  
  - 返回：`{ "ok": true }` 或错误码。
- **WebRTC 信令**  
  - 由后端提供「创建会话、交换 SDP/ICE」的接口或 WebSocket 事件，前端只实现标准 WebRTC 客户端逻辑（offer/answer/candidate）。
- **状态（可选）**  
  - `GET /api/status` 或 WebSocket `status` 事件，字段可包含：`connected`、`battery`、`current_command` 等。

---

### 5. 安全与部署

- **HTTPS**：生产环境必须，WebRTC 和部分浏览器 API 要求安全源。
- **环境变量**：`VITE_API_BASE`、`VITE_WS_URL`、`VITE_SIGNALING_URL` 等，避免写死。
- **PWA**：`manifest.json` 中 `display: standalone`、`orientation` 按需设，方便全屏遥控体验。

---

## 三、与比赛要求的对应

| 要求 | 实现方式 |
|------|----------|
| 移动端 | PWA 响应式 + 全屏，或后续打包为 TWA/Cordova 等 |
| 有 Agent | 后端/Agent 生成 command 序列；前端可增加「任务列表」或「推荐技能」由 Agent 下发 |
| 有渲染 | 第一视角视频（WebRTC）为主；若需 3D 可再叠 Three.js 做简单场景预览 |
| 控制 | HTTP/WebSocket 发 command_id；大招按钮即固定 command_id |
| 语音 | Web Speech 或云端 ASR → 意图 → command_id |

---

## 四、实施顺序建议

1. **搭架子**：Vite + React + TS + Tailwind，路由若需要可加 React Router。
2. **连接层**：`controlApi` 发 `POST /api/command`，定义好 `CommandId` 类型。
3. **UI**：ControlPad + SkillButton，先不接真实后端，用 mock 或本地日志验证点击流。
4. **WebRTC**：接信令接口，实现接流并显示在 `<video>`。
5. **语音**：Web Speech API 简单识别 → 关键词映射到 command_id。
6. **状态与重连**：Zustand 存连接/流状态，断线重连与提示。
7. **PWA**：manifest + Service Worker，可安装到主屏幕。

这样前端技术选型（PWA + React + TS + WebRTC + HTTP/WS）和分层架构就清晰了，便于和仿真/真机/Agent 后端对接。
