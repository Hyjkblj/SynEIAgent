# Realtime Control Bridge：当前进度与后续规划（先仿真后真机）

本文档将当前已完成任务、已验证指标与后续 PR 规划收敛为一份“可交付控制桥”路线图。

> 定位：本项目当前阶段是 **Realtime Control Bridge（实时控制桥）**  
> 目标：稳定接收输入（mobile/LLM/script）→ 统一为 IR → 最小安全控制（tick/deadman/lock/mode）→ 稳定下发（ROS2）→ WebRTC 视频同步

---

## 1. 当前已完成（代码与验证）

### 1.1 控制链路（Control Plane）已具备
- **Input Envelope**：统一输入语义，避免 compiler 失控
- **Compiler → MoveIR**：边界强校验（Pydantic）
- **Kernel（Tick-based）**：
  - 固定节拍输出（默认 20Hz）
  - deadman（默认 200ms）
  - latest-only（不积压）
  - locks + preempt（抢占触发 stop）
  - mode controller（human/mobile > llm；teleop > auto）
- **Executor（Execution Contract）**：Kernel 不写死 capability 分支，通过 registry 选择 executor 执行
- **ROS2 Adapter**：`Ros2CmdVelAdapter`（运行时可选依赖）
- **Observability**：Kernel 关键事件（submit/execute/stop/preempt/reject）+ JSONL recorder + 最小 replay

### 1.2 稳定性与压测已通过（自动化）
在 `nanobot/` 项目目录（`d:\Develop\Project\nanobot\nanobot`）运行：

```bash
python -m pytest -q tests/robot_platform
```

包含：
- 基础单测（IR/Bus/Kernel/Timing/Locks/Teleop/Obs）
- 指标测试（延迟/节拍/抢占/断流恢复）
- 压测（100Hz 输入、burst→gap→burst）

### 1.3 CI 已收敛到“控制桥基线”
已将 GitHub Actions 工作流收敛为仅跑 `tests/robot_platform`（稳定性基线）。

---

## 2. 需求对照（当前状态）

### 2.1 移动端 App 操控机器人
- **服务端 WebRTC DataChannel joystick 接收**：已具备（`RobotChannel`）
- **Kernel 模式控制（tick/deadman/lock/mode）**：已具备（`control_mode="kernel"`）
- **真实 ROS2 环境 / 仿真环境 E2E 运行验证**：需按 PR-02/PR-03 继续落地（配置 + 运行命令 + topic 对齐）

### 2.2 WebRTC 视频流与机器人摄像头同步
服务端已提供：
- WebRTC video track（`RosVideoTrack`）
- `POST /push_frame` 接口（接收 JPEG 帧）

缺口在“帧源”（仿真/真机摄像头）：
- **ROS2 相机 topic → /push_frame**：仓库已有脚本 `nanobot/docs/tiangong_video_bridge.py`
- **仿真环境是否已有 ROS2 相机 topic**：需要对齐 topic 或补一个本地视频源推帧脚本

---

## 3. 开发策略：先仿真，再真机（最终接口层）

### 3.1 最终接口层定义
- **运动最终接口层**：`RobotAdapter`
  - 仿真/真机差异：通常只是 ROS2 topic/namespace/网络环境不同
- **视频最终接口层**：帧源 → `POST /push_frame`
  - 仿真/真机差异：相机 topic（或本机视频源）不同

原则：Kernel/IR/Mode/Timing 不分叉；只替换 Adapter/帧源。

---

## 4. PR 任务规划（可直接开工）

> 顺序严格按收敛目标推进：先可交付闭环，再做运维与安全收口。

### PR-01【稳定性基线】把“控制桥”测试固化进 CI（已完成）
- **交付物**：CI 中跑 `pytest -q tests/robot_platform`
- **验收**：CI 绿；本地 `tests/robot_platform` 全绿

### PR-02【端到端操控闭环】Kernel 模式默认可跑（仿真优先）
- **范围**：`nanobot/channels/robot.py` + 文档/示例配置
- **交付物**：
  - 最小可运行配置：`/cmd_vel` topic、node_name、rate、deadman、max_linear/max_angular
  - “仿真侧”与“真机侧”仅通过配置差异切换
- **验收（仿真）**：
  - joystick → `/cmd_vel` 生效
  - 停止输入 ≤ 200ms stop
  - human/mobile 抢占 llm 立即生效

### PR-03【视频闭环】摄像头 → /push_frame → WebRTC track → App（仿真优先）
- **范围**：给出可运行“帧源”
  - ROS2 相机 topic：复用 `nanobot/docs/tiangong_video_bridge.py`
  - 若无 ROS2 相机：补一个本机视频源推帧脚本（可选）
- **交付物**：
  - 可复制运行命令（nanobot 地址、fps、topic）
  - topic 对齐说明
- **验收**：
  - App 端视频稳定显示
  - 断流恢复后继续显示
  - 服务端不出现积压导致延迟爆炸（宁可丢帧）

### PR-04【同步与抖动控制】视频帧时间戳/序号 + dropped 指标
- **范围**：`RosVideoTrack` + `/push_frame` 协议增强（可选）
- **交付物**：dropped/latency 可观测
- **验收**：高 fps 推帧时延迟不持续累积

### PR-05【运维化】健康检查 + 关键指标输出
- **范围**：RobotChannel / Kernel / TeleopPipeline 状态输出
- **交付物**：能快速判断是否 kernel 模式、是否触发 deadman、是否频繁 preempt
- **验收**：断流/重连/抢占/stop 可定位

### PR-06【安全收口】进一步减少绕过 Kernel 的可能性
- **范围**：legacy bridge 控制路径
- **交付物**：生产默认 `control_mode="kernel"`；legacy 仅显式开关
- **验收**：未开启 legacy 时 joystick 不直通 bridge

### PR-07【可选】WebRTC 信令与网络鲁棒性强化
- **范围**：session 生命周期、资源释放与日志
- **验收**：频繁连断不泄漏；重连后控制/视频恢复

---

## 5. 仿真：相机来源检查（TGrobot4s）

在 `TGrobot4s/robot` 中已发现 ROS2 相机相关内容：
- `TGrobot4s/robot/orbbec_camera_ros2/...`（Orbbec 相机 ROS2 驱动 + 多个 launch）

### 建议动作
1) 在 ROS2 仿真/开发机运行相机 launch 后，确认图像 topic：

```bash
ros2 topic list | grep -i image
```

2) 将 `nanobot/docs/tiangong_video_bridge.py` 的订阅 topic 改为实际 topic（默认写死 `/camera/color/image_raw`）。

3) 启动推帧桥：

```bash
pip install opencv-python httpx
python d:\Develop\Project\nanobot\nanobot\docs\tiangong_video_bridge.py --nanobot http://127.0.0.1:9100 --fps 15
```

---

## 6. 阶段停手标准（桥的“生死指标”）

当满足以下条件，即可停止架构演进，进入业务迭代：
1) **20Hz 输出稳定**（P95 不抖）
2) **deadman 可靠 stop**（任何断流/抖动下都触发）
3) **human/mobile 一定可抢占 llm**（无例外）
4) **断流/恢复** 不会出现异常行为（无积压、无幽灵移动）

