# RobotF4s — 人形机器人仿真与真机一体化

比赛目标：**环境快速建模** + **动作示教/仿真** + **真机 Real2Real**，移动端控制 + Agent + 渲染。

## 核心能力

| 模块 | 说明 | 技术栈 |
|------|------|--------|
| **环境快速建模** | 手机拍照 → 3D 场景（Isaac Sim），参数可后续由大模型/素材库生成 | Isaac Sim API、AI 填充、Cursor 写入 |
| **动作示教与仿真** | 示教动作（如铁山靠）→ 抽象为遥控指令，移动端「大招按钮」一键触发 | 动作序列 → 基础命令映射 |
| **真机 Real2Real** | 移动端遥控 + Agent 设计场景内特殊交互（后台 Cursor CLI） | WebRTC/HTTP、视频流、语音控制 |

## 项目结构

```
robotF4s/
├── isaac_sim/           # Isaac Sim 仿真核心
│   ├── import_tienkung_urdf.py   # 天工行者 URDF 导入
│   ├── scene_obstacles.py        # 障碍物与碰撞/摩擦场景
│   ├── rl_env/                   # RL 环境与 reward
│   └── env_modeling_api.py       # 环境建模 API（供 AI/手机端调用）
├── urdf/                 # 天工行者 URDF（clone 自 TienKung_URDF）
├── mobile/                # 移动端控制（WebRTC+HTTP、视频、语音）
├── agent/                 # Agent 与 Cursor CLI 集成
├── docs/                  # 设计文档与 API 说明
└── scripts/               # 一键同步、下载 URDF 等脚本
```

## 快速开始

### 1. 准备 URDF（天工行者）

```bash
# 克隆优必选天工行者 URDF（Open-X-Humanoid）
scripts/fetch_tienkung_urdf.sh   # 或 .bat 见 scripts/
```

来源：https://github.com/x-humanoid-robomind/TienKung_URDF  
可选：`lite/`、`pro/`、`tiangong2pro-urdf/`、`tianyi2-urdf/`

### 2. 在 Isaac Sim 中跑仿真

- 安装 [NVIDIA Isaac Sim](https://docs.isaacsim.omniverse.nvidia.com/)（推荐 4.x/5.x+）
- 在 Isaac Sim 中：**File → Run Script** 选择 `isaac_sim/run_standalone.py`，或 **Window → Script Editor** 中逐段运行

**一键跑通（推荐）**：运行 `isaac_sim/run_standalone.py`，会依次完成：
  - 导入天工 URDF（需先执行 step 1 拉取 URDF）
  - 添加地面与障碍物（碰撞/摩擦）
  - 点击 Sim 内 **PLAY** 即可看仿真

```bash
# 使用 Isaac Sim 自带 Python（将 <IsaacSim> 换成实际安装路径）
<IsaacSim>/python.bat D:/Develop/Project/robotF4s/isaac_sim/run_standalone.py
```

或分步执行：`import_tienkung_urdf.py` → `scene_obstacles.py --demo`

### 3. RL 仿真

```bash
# 使用 Isaac Lab 或自定义 Gym 接口
python isaac_sim/rl_env/tienkung_rl_env.py
```

### 4. 一键同步到真机

见 `scripts/sync_to_real.md` 与 `docs/real2real.md`。

## 比赛要求对照

- **移动端**：见 `mobile/`（WebRTC + HTTP、视频流、语音 control）
- **Agent**：见 `agent/`，可挂 Cursor CLI 做场景内特殊交互
- **渲染**：Isaac Sim 自带渲染；移动端可接视频流做「环太平洋」式实时遥控
- **3D 建模 + Reward**：`isaac_sim/` + `isaac_sim/rl_env/reward_design.md`

## 文档

- [架构与数据流](docs/architecture.md)
- [环境快速建模与 Isaac Sim API](docs/env_modeling.md)
- [动作示教 → 遥控命令](docs/motion_to_commands.md)
- [真机 Real2Real 与移动端](docs/real2real.md)
- [URDF 与 Isaac Sim 接口](docs/urdf_isaac_api.md)

## License

见仓库根目录 LICENSE 文件。
