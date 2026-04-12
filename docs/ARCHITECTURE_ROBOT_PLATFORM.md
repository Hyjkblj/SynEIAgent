# 机器人操控平台：设计理念与架构蓝图（nanobot）

本文档用于把当前阶段的**设计理念**与**架构设计**固化为工程可执行的蓝图，目标是：

- **一周内跑通闭环**：移动端 App → Realtime Bus → Action IR → Execution Kernel → ROS2 机器人动起来
- **可扩展**：后续接入更多 LLM Provider、更多机器人形态、更多端（Web/PC/其他控制器）不会推翻架构
- **可控/可审计**：所有动作可追踪、可回放、可限权、可限速

---

## 设计理念（只保留会影响代码结构的原则）

### 1) LLM 是“决策引擎”，不是核心系统
- **LLM 只负责提出意图**（Intent）或候选动作，不允许直接产生底层控制指令直达机器人。
- **系统必须可替换**：模型可换、provider 可换，但执行内核与 IR 不换。

### 2) Capability 是业务抽象的中心
- Channel/接入层只是“输入设备/数据源”，不承载业务决策。
- 系统对外暴露的是能力（Capabilities），例如 `robot.motion`、`media.stream`、`policy.evaluate`。

### 3) 所有控制都必须经过 Execution Kernel
铁律：
- **所有输入先变成 IR**：LLM / 人类 / WebRTC → Action IR
- **Kernel 只接收 IR**：禁止 JSON/文本直达 adapter
- **Adapter 只执行不决策**
- **Stop 必须是 Kernel 的自动安全行为**（deadman/超时触发）

---

## 总体分层架构（Data Plane / Control Plane / Model Plane）

### Data Plane（数据面：Realtime I/O）
承载：控制指令、遥测、视频/音频、状态心跳等多流数据。

### Control Plane（控制面：Capability Gateway + Execution Kernel）
- **Capability Gateway**：定义“能做什么”（接口与参数）
- **Execution Kernel**：决定“什么时候、怎么做”（状态机、仲裁、锁、队列、时间语义）

### Model Plane（模型面：Model Orchestrator）
负责：模型选择、降级、重试、预算治理、输出约束（Intent→IR），但不负责执行。

---

## 推荐目录结构（按 nanobot 落地）

```text
nanobot/nanobot/
├── kernel/
│   ├── runtime.py          # ⭐Kernel 入口：start/submit/cancel/subscribe
│   ├── state_machine.py    # 状态机：idle/teleop/auto/e-stop/fault
│   ├── arbiter.py          # 冲突仲裁：system > human/mobile > llm
│   ├── queue.py            # job 队列（对 motion 采用“最新覆盖”策略）
│   ├── timing.py           # ⭐时间语义：rate/drop_stale/deadman
│   ├── locks.py            # ⭐资源锁：robot.motion/navigation/...
│   ├── actor.py            # actor 结构：id/type/priority/scopes
│
├── action_ir/
│   ├── base.py             # IR 基类：version/capability/trace/ts/ttl
│   ├── motion.py           # MoveIR（MVP）
│   ├── compiler.py         # data/intent → IR（可先规则，后续可引入 LLM）
│   ├── validators.py       # 校验：能力支持/限速/禁区/状态/权限
│
├── realtime/
│   ├── bus.py              # ⭐Realtime Bus：publish/subscribe
│   ├── streams.py          # Control/Telemetry/Video 三类流
│   ├── qos.py              # 背压：control 保留最新，video 丢旧帧
│
├── adapters/
│   ├── robot/
│   │   ├── base.py         # RobotAdapter 接口
│   │   ├── ros2_adapter.py # ROS2 /cmd_vel（MVP）
│
├── capabilities/
│   ├── robot.py            # RobotCapability（薄层，转交 Kernel）
│
├── policy/
│   ├── engine.py           # Policy Engine：RBAC+ABAC+Context
│
├── obs/
│   ├── events.py           # 事件模型（可回放）
│   ├── recorder.py         # JSONL 落盘记录
```

---

## 核心接口契约（必须锁死）

### Action IR（统一入口）
Action IR 需要：**版本化 + 能力声明 + 时间字段**，以便演进、协商、丢弃过期控制。

- **字段要求**：
  - **`version`**：IR 版本（例如 `"1.0"`）
  - **`capability`**：能力名（例如 `"motion"` / `"navigation"`）
  - **`trace_id` / `intent_id`**：审计与回放
  - **`ts_ms`**：产生时间（用于 stale 丢弃）
  - **`ttl_ms`**：有效期（控制类建议很短，如 200ms）

> 注意：`intent_id` 等默认值应使用 `default_factory`（避免类加载时固定一次的坑）。

### Kernel（唯一执行入口）
Kernel 需要提供最小公共 API：
- `start()`：启动常驻 loop（deadman/消费控制流等）
- `submit_ir(actor, ir) -> job_id`
- `cancel(job_id | scope)`
- `get_state()`
- `subscribe_events(handler)`

### RobotAdapter（严格限制）
Adapter 只提供“执行原语”：
- `move(linear, angular)` / `stop()`
- `get_capabilities() -> dict`（用于 capability 协商与限幅）

---

## Execution Kernel：关键职责与运行时流程

### Kernel 关键模块
- **StateMachine**：`idle / teleop / auto / e-stop / fault`
- **LockManager（资源锁）**：同一资源同一时刻只能一个 owner，支持抢占
- **Arbiter（仲裁）**：actor 优先级（system > human/mobile > llm）
- **TimingController（时间语义）**：
  - `drop_stale`：过期 IR 丢弃
  - `enforce_rate`：下发频率稳定（例如 20Hz）
  - `deadman`：超时自动 stop（例如 200ms）
- **JobQueue（队列）**：
  - motion 类建议“最新覆盖”，避免积压导致延迟爆炸

### submit 流程（MVP）
1. **stale/ttl 检查**（Timing）
2. **capability 支持检查**（Adapter capabilities）
3. **权限/仲裁**（Policy + Arbiter）
4. **资源锁 acquire / 抢占**（Locks）
5. **入队（或覆盖）**（Queue）
6. **执行**：
   - motion：按 rate 限流后调用 `adapter.move(...)`
   - 若 deadman 触发：强制 `adapter.stop()`

---

## Realtime Bus：多流 + QoS + 背压（Backpressure）

### 三类流建议
- **ControlStream**（最高优先级）：摇杆/急停，**只保留最新**，允许丢包但不允许积压
- **TelemetryStream**：电量/状态/传感摘要，允许小队列，满了丢 oldest 或降频
- **VideoStream**：允许丢旧帧（宁可花屏，不许积压导致延迟）

### 背压策略（必须）
若不做背压，会出现：移动端卡顿→队列堆积→控制延迟爆炸→危险行为。

---

## Model Orchestrator（多 LLM 平台）接入原则

- Orchestrator 产出 **Intent 或 IR 候选**，必须通过 `action_ir.validators` 与 Kernel 的锁/仲裁。
- 对高风险能力（如 motion/navigation）：
  - **禁止自由文本直达**
  - 必须输出结构化（Intent/IR），并且可被校验/裁剪/拒绝

---

## 可观测性与可回放（Observability）

建议固化 3 个 ID：
- **`trace_id`**：一次端到端链路（移动端一次操作/一次用户指令）
- **`decision_id`**：一次模型决策（prompt、模型、输出、版本）
- **`job_id`**：一次执行任务（Kernel 内部）

必须能回放：LLM 决策 → IR → Kernel 仲裁/锁/时间语义 → Adapter 执行 → 机器人反馈。

---

## 风险与漏洞清单（按严重级别）

### P0（高危：可能造成失控/越权/数据外泄）
- **控制链路绕过 Kernel**
  - **风险**：Channel/Tool/Adapter 之间出现“直通”，跳过仲裁、锁、deadman，导致不可预测行为
  - **缓解**：Adapter 仅在 Kernel 内被引用；代码审计+单元测试确保唯一入口；运行时加断言/日志

- **时间语义缺失（deadman / stale / rate）**
  - **风险**：旧指令继续执行（幽灵移动）；网络抖动引发危险动作
  - **缓解**：Kernel 内强制 TimingController；ControlStream 必带 `ts_ms`

- **资源锁缺失或粒度错误**
  - **风险**：LLM 导航与人类遥控冲突，导致抖动/不可预测
  - **缓解**：MVP 先锁 `robot.motion`/`robot.navigation`；system/human 抢占需触发 stop

- **权限与策略不足（仅函数 check）**
  - **风险**：低电量/夜间/禁区仍能执行；访客能操控
  - **缓解**：Policy Engine（RBAC+ABAC+Context），并且在 Kernel 前置执行

- **高频控制无背压**
  - **风险**：队列堆积导致延迟；控制与视频争用资源导致控制不稳定
  - **缓解**：ControlStream 容量=1，永远覆盖；Video 丢旧帧；暴露 dropped/latency 指标

### P1（中高：稳定性/可扩展性/可运维问题）
- **IR 未版本化 / 无能力声明**
  - **风险**：机器人能力不一致时崩溃或行为错误；升级难
  - **缓解**：IR `version` + `capability`；adapter `get_capabilities()` 协商

- **JobQueue 对 motion 采用累积 enqueue**
  - **风险**：积压导致延迟爆炸
  - **缓解**：motion “最新覆盖”；或者对同 capability 只保留最后一条

- **事件模型不统一**
  - **风险**：多端/多机器人扩展时事件类型爆炸，难以兼容
  - **缓解**：统一 event envelope：`type=event, event=..., data=...`

### P2（中：安全与工程治理欠缺）
- **速率限制缺失（发送/控制/任务）**
  - **风险**：误触或攻击导致控制/消息风暴
  - **缓解**：按 actor/能力做 rate limit；对 teleop 单独限频

- **审计不可回放**
  - **风险**：事故无法追责与复盘
  - **缓解**：obs 记录 decision→IR→kernel→adapter 全链路 JSONL

---

## 与 WhatsApp Bridge 的边界（明确禁止污染主链路）

`nanobot/bridge`（WhatsApp Baileys）定位为**消息类 Adapter**（message/media），原则：
- **Bridge 不允许进入 Robot 控制链路**
- 机器人控制链路只在 Python 主进程的 Kernel/IR/Adapter 内闭环

---

## MVP 验收标准（“能动起来”的定义）
- 移动端（或模拟器）以 ControlStream 发送 `{linear, angular, ts_ms}`，频率可 > 20Hz
- 系统稳定以 20Hz 下发 `/cmd_vel`（或等价）
- 停止发送后 ≤ 200ms 自动 stop
- 人类抢占（高优）能中断 LLM（低优）控制并 stop
- 全链路可记录：trace_id / job_id 与关键事件

---

## PR 任务规划（可直接按此开工）

本节把实现拆成可以并行推进的 PR，**每个 PR 都有明确交付物、验收点、依赖关系**。建议采用：

- **分支命名**：`feat/robot-kernel-<topic>` 或 `feat/robot-platform-<topic>`
- **PR 标题前缀**：`[robot-platform] ...`
- **PR 原则**：
  - PR1 先把“骨架与接口契约”落地，让后续 PR 不互相打架
  - motion/teleop 这类高风险路径必须先把 **timing + deadman** 做出来
  - 所有模块优先写“最小可运行闭环”，功能再迭代

### PR-01：基础骨架与接口契约（Action IR + Adapter 接口）
- **范围**：
  - `nanobot/nanobot/action_ir/base.py`（IR 基类，含 `version/capability/trace_id/intent_id/ts_ms/ttl_ms`）
  - `nanobot/nanobot/action_ir/motion.py`（`MoveIR`）
  - `nanobot/nanobot/adapters/robot/base.py`（`RobotAdapter` 接口）
- **交付物**：
  - IR 使用 `default_factory` 生成 `intent_id` 等默认值（避免静态默认值坑）
  - `MoveIR` 可被实例化并序列化（Pydantic）
- **验收**：
  - 单元测试：`MoveIR` 的默认字段正确、`ttl_ms` 可配置、`ts_ms` 存在
- **依赖**：无（全项目地基）

### PR-02：ROS2 Adapter（能发 `/cmd_vel`，能 stop）
- **范围**：
  - `nanobot/nanobot/adapters/robot/ros2_adapter.py`
- **交付物**：
  - `move(linear, angular)` / `stop()` / `get_capabilities()`
- **验收**：
  - 在仿真或真机环境下：调用 `move` 能看到 `/cmd_vel` 输出；`stop` 输出零速度
- **依赖**：PR-01（接口）

### PR-03：Realtime Bus（ControlStream 只保留最新 + 背压）
- **范围**：
  - `nanobot/nanobot/realtime/bus.py`
  - `nanobot/nanobot/realtime/streams.py`
  - `nanobot/nanobot/realtime/qos.py`
- **交付物**：
  - `ControlStream` 容量=1，push 覆盖，consume 返回最新
  - `TelemetryStream`/`VideoStream` 基础骨架（可先 stub）
- **验收**：
  - 单元测试：连续 push 100 次，consume 只返回最后一次数据；队列不增长
- **依赖**：无（可并行于 PR-02）

### PR-04：Kernel Runtime（submit_ir + 最小执行路径）
- **范围**：
  - `nanobot/nanobot/kernel/runtime.py`
  - `nanobot/nanobot/kernel/state_machine.py`（最小状态：idle/teleop）
  - `nanobot/nanobot/kernel/queue.py`（motion 最新覆盖策略）
- **交付物**：
  - `Kernel.submit_ir(actor, ir)` 能把 `MoveIR` 转成 `adapter.move(...)`
  - motion job 不积压（覆盖/去抖）
- **验收**：
  - 伪造 adapter（mock）测试：submit 触发 move；重复 submit 不导致队列增长
- **依赖**：PR-01、PR-02

### PR-05：Timing（时间语义：drop_stale / enforce_rate / deadman）
- **范围**：
  - `nanobot/nanobot/kernel/timing.py`
  - Kernel 中接入 timing（PR-04 的 runtime 调整）
- **交付物**：
  - `drop_stale`：IR 超过 `ttl_ms` 丢弃
  - `enforce_rate(hz=20)`：稳定下发频率（过快则不下发）
  - `deadman(timeout_ms=200)`：超过阈值自动 stop
  - `Kernel.start()` 启动 deadman loop（async task）
- **验收**：
  - 单元测试：不再 submit 时，deadman 会调用 `adapter.stop()`
  - 单元测试：高频 submit（>100Hz）最终下发频率≤20Hz
- **依赖**：PR-04

### PR-06：Locks + Arbiter + Actor（抢占规则锁死）
- **范围**：
  - `nanobot/nanobot/kernel/locks.py`
  - `nanobot/nanobot/kernel/arbiter.py`
  - `nanobot/nanobot/kernel/actor.py`
- **交付物**：
  - 资源锁：至少 `robot.motion` 一把锁
  - actor 优先级：`system > human/mobile > llm`
  - 抢占触发 stop（若抢占 motion owner）
- **验收**：
  - 单元测试：低优 actor 无法夺锁；高优可抢占并触发 stop
- **依赖**：PR-04、PR-05

### PR-07：Compiler + Validators（data/intent → MoveIR + 安全限幅）
- **范围**：
  - `nanobot/nanobot/action_ir/compiler.py`
  - `nanobot/nanobot/action_ir/validators.py`
- **交付物**：
  - compiler：从 control data 生成 `MoveIR`（要求包含 `ts_ms`）
  - validators：根据 adapter capabilities 做限幅（max_linear/max_angular）
- **验收**：
  - 单元测试：超限输入会被裁剪或拒绝（明确策略）
- **依赖**：PR-01、PR-02

### PR-08：移动端 Channel 接入（WebRTC/DataChannel → RealtimeBus → Kernel）
- **范围**：
  - 你们当前“移动端自研 channel”所在目录（将控制包 publish 到 bus）
  - 启动时创建 Kernel、启动 Kernel loop、订阅 bus 并 submit IR
- **交付物**：
  - 控制包进入 ControlStream（只保留最新）
  - compiler→validator→kernel.submit_ir 全链路贯通
- **验收**：
  - 端到端：移动端摇杆→机器人动；松手≤200ms 停
- **依赖**：PR-03、PR-04、PR-05、PR-07

### PR-09：Observability（最小可回放：events + recorder）
- **范围**：
  - `nanobot/nanobot/obs/events.py`
  - `nanobot/nanobot/obs/recorder.py`
- **交付物**：
  - 记录：trace_id / job_id / 关键事件（submit/execute/stop/preempt）
- **验收**：
  - JSONL 能还原一次 teleop 会话关键节点
- **依赖**：PR-04（或之后逐步补齐）

### 推荐 7 天排期（可并行）
- **Day 1–2**：PR-01 + PR-02（能发 `/cmd_vel`）
- **Day 3**：PR-04（Kernel 最小执行）
- **Day 4**：PR-05（Timing + deadman，锁死安全）
- **Day 5**：PR-03 + PR-07（Bus + Compiler/Validator）
- **Day 6**：PR-08（移动端接入打通闭环）
- **Day 7**：PR-06 + PR-09（抢占/审计补齐）

> 备注：如果资源紧张，PR-06/PR-09 可延后，但 **PR-05（Timing/Deadman）必须在闭环前完成**。

