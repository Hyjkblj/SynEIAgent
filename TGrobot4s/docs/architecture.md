# 整体架构与数据流

## 目标

1. **环境快速建模**：手机拍照 → 3D 场景（Isaac Sim），参数可由大模型/素材库生成  
2. **动作示教与快速仿真**：示教（如铁山靠）→ 抽象为若干基础遥控命令，移动端「大招」按钮触发  
3. **真机 Real2Real**：移动端遥控 + Agent 设计场景内特殊交互（可后台挂 Cursor CLI）

## 数据流概览

```
[手机拍照/素材] → [环境建模 API] → [Isaac Sim 场景 USD]
                        ↑
                  [大模型/素材库生成参数]

[示教动作] → [动作序列] → [基础命令映射] → [移动端 UI：大招/技能按钮]

[Isaac Sim 仿真] → [策略/策略导出] → [一键同步] → [真机]
       ↑                    ↑
   [RL 训练]           [Reward 设计]

[移动端] ←→ [WebRTC/HTTP] ←→ [真机]  （视频流 + 控制 + 语音）
                ↑
         [Agent / Cursor CLI]  （场景内特殊交互逻辑）
```

## 模块说明

| 模块 | 输入 | 输出 | 备注 |
|------|------|------|------|
| 环境建模 | 照片/点云/参数 | USD 场景、障碍物、材质 | Isaac Sim 有 API，可 Cursor 写入 |
| URDF 导入 | 天工 URDF + meshes | 仿真中的机器人 | Isaac Sim URDF Importer |
| 障碍物/碰撞摩擦 | 场景配置 | 物理场景 | 见 scene_obstacles |
| RL 仿真 | 环境 + 策略 | 训练曲线 / 导出策略 | Isaac Lab 或自定义 Gym |
| 动作→命令 | 示教轨迹 | 离散命令 ID + 参数 | 后续可大模型生成 |
| 真机同步 | 策略/技能包 | 真机可执行 | 一键脚本 + 协议 |
| 移动端 | 用户操作、视频流 | 控制指令、语音 | WebRTC + HTTP |
| Agent | 场景描述、任务 | 行为序列、CLI 调用 | 可挂 Cursor CLI |

## 技术选型摘要

- **仿真**：NVIDIA Isaac Sim（URDF API、PhysX、渲染）
- **RL**：Isaac Lab 或 Isaac Gym 风格接口，reward 在 `isaac_sim/rl_env/`
- **URDF**：优必选天工行者 [TienKung_URDF](https://github.com/x-humanoid-robomind/TienKung_URDF)
- **移动端**：WebRTC（视频）+ HTTP（控制）+ 语音
- **Agent**：后台 Cursor CLI，解析场景与任务生成控制/技能序列
