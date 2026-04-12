# RobotF4s 项目结构与接口设计

更新时间：2026-03-09

## 1. 项目结构概览

```text
robotF4s/
├── isaac_sim/                 # Isaac Sim 仿真核心（URDF 导入、场景建模、障碍物）
│   ├── import_tienkung_urdf.py
│   ├── scene_obstacles.py
│   ├── env_modeling_api.py
│   ├── run_standalone.py
│   └── rl_env/
├── mobile/                    # 移动端遥控前端（React + TS + Vite）
│   └── app/
│       ├── components/        # UI（摇杆、技能按钮、视频渲染）
│       ├── hooks/             # 业务调用（useControl）
│       ├── services/          # 对外接口适配（controlApi、webrtcService）
│       ├── store/             # 前端状态（Zustand）
│       └── types/             # 协议类型（command_id、请求响应）
├── agent/                     # Agent 与 Cursor CLI 说明
├── docs/                      # 设计与接口文档
└── scripts/                   # URDF 拉取、真机同步说明
```

## 2. 接口分层（边界）

| 分层 | 调用方 | 被调用方 | 接口形态 | 当前状态 |
|---|---|---|---|---|
| 控制接口 | `mobile` | 真机/仿真网关 | HTTP (`/api/command`) | 已在前端实现调用 |
| 视频链路 | `mobile` | 真机/流媒体网关 | WebRTC + 信令（HTTP/WS） | 前端 `PeerConnection` 已封装，信令接口待后端落地 |
| 场景建模 | Agent/脚本 | `isaac_sim` | Python 函数接口 | 已实现 |
| URDF 导入 | 脚本/Isaac Sim | `isaac_sim` | Python 函数 + CLI 参数 | 已实现 |

## 3. 统一数据模型

### 3.1 控制命令模型（`mobile/app/types/commands.ts`）

```ts
type CommandId =
  | "move_fwd" | "move_bwd"
  | "turn_l" | "turn_r"
  | "squat" | "stand"
  | "skill_tieshankao" | "skill_wave" | "skill_kick";

interface CommandPayload {
  command_id: CommandId;
  params?: Record<string, number | string>;
}

interface CommandResponse {
  ok: boolean;
  message?: string;
}
```

### 3.2 场景建模模型（`isaac_sim/env_modeling_api.py`）

```json
{
  "ground": {
    "size": 20.0,
    "friction": 0.8,
    "restitution": 0.0
  },
  "obstacles": [
    {
      "type": "box|cylinder|sphere",
      "path": "/World/obs_1",
      "position": [2, 0, 0.5]
    }
  ],
  "lights": []
}
```

## 4. 接口设计

### 4.1 控制接口（已接入前端）

`POST /api/command`

- 用途：移动端发送遥控或技能命令给网关（再路由到仿真或真机）
- 调用入口：`mobile/app/services/controlApi.ts` -> `sendCommand()`
- 请求体：

```json
{
  "command_id": "skill_tieshankao",
  "params": {
    "direction": "left"
  }
}
```

- 响应体：

```json
{
  "ok": true,
  "message": "accepted"
}
```

- 约束建议：
  - `command_id` 必须属于 `CommandId` 枚举
  - `params` 键值需要按命令白名单校验
  - 响应至少返回 `ok` 字段，便于前端统一处理

### 4.2 状态接口（规划中，文档已定义）

`GET /api/status`

- 用途：返回连接状态、当前命令、电量等
- 建议响应：

```json
{
  "connected": true,
  "battery": 0.78,
  "current_command": "move_fwd",
  "mode": "teleop",
  "updated_at": "2026-03-09T10:30:00Z"
}
```

### 4.3 WebRTC 信令接口（规划中）

当前前端已有 `webrtcService.ts` 的以下能力：

- `createPeerConnection(onStream, onStateChange)`
- `createOffer()`
- `setRemoteDescription(sdp)`
- `addIceCandidate(candidate)`

建议网关提供以下任一方案（HTTP 或 WebSocket）：

1. 会话创建：`POST /api/webrtc/session`
2. Offer/Answer 交换：`POST /api/webrtc/offer`、`POST /api/webrtc/answer`
3. ICE 交换：`POST /api/webrtc/ice`

## 5. Isaac Sim 侧 Python 接口（已实现）

### 5.1 环境建模（`isaac_sim/env_modeling_api.py`）

| 函数 | 输入 | 输出 | 说明 |
|---|---|---|---|
| `load_scene_from_json(path)` | JSON 文件路径 | `dict` | 加载场景描述 |
| `generate_scene_json_from_description(description)` | 文本描述 | `dict` | 描述转场景 JSON（当前为规则占位实现） |
| `apply_scene_to_isaac(scene, stage=None)` | 场景字典 | `List[str]` | 在 Isaac Sim 中创建地面/障碍物，返回创建路径 |
| `write_scene_script(output_path, scene)` | 输出路径 + 场景字典 | `None` | 生成可执行 Python 场景脚本 |

### 5.2 URDF 导入（`isaac_sim/import_tienkung_urdf.py`）

| 函数 | 说明 |
|---|---|
| `get_default_urdf_path(version)` | 根据版本获取默认 URDF 路径 |
| `create_import_config(...)` | 构建 URDF 导入配置 |
| `import_tienkung(urdf_path, fix_base, self_collision, dest_path)` | 导入天工 URDF 到当前 Stage |
| `setup_scene_basic()` | 初始化基础地面/物理场景 |

## 6. 命令清单（面向移动端与 Agent）

| command_id | 语义 | 常见参数 |
|---|---|---|
| `move_fwd` / `move_bwd` | 前进 / 后退 | `speed`, `duration` |
| `turn_l` / `turn_r` | 左转 / 右转 | `angular_speed`, `duration` |
| `squat` / `stand` | 蹲下 / 站起 | - |
| `skill_tieshankao` | 铁山靠 | `direction`（可选） |
| `skill_wave` | 挥手 | - |
| `skill_kick` | 踢腿 | `side`（可选） |

## 7. 当前落地状态总结

- 已可直接使用：`POST /api/command` 协议、`command_id` 类型体系、Isaac Sim 场景建模 Python API。
- 已有前端能力但依赖后端：WebRTC 媒体接收逻辑（缺信令服务）。
- 文档定义但未见实现：`GET /api/status`、完整 WebRTC 信令网关。

