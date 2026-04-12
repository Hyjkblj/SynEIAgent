# RL Reward 设计（天工行者仿真）

## 目标

- 在 Isaac Sim 中跑 RL 仿真，训练步行/避障/技能（如铁山靠可拆成子技能）。
- Reward 设计要利于 sim2real：避免过于依赖仿真特有信号，多用电机的力矩/接触/姿态等可迁移信号。

## 常用项

| 名称 | 形式 | 说明 |
|------|------|------|
| 存活/前进 | +1 每步 或 + v_x | 鼓励向前走、不倒地 |
| 高度 | -\|z - z_target\| | 保持躯干高度 |
| 姿态 | -\|roll\| - \|pitch\| | 躯干尽量竖直 |
| 角速度惩罚 | -\|\omega\|^2 | 减少晃动 |
| 接触 | 脚接触合理、躯干/头不触地 | 用 contact force 或 binary 接触 |
| 动作平滑 | -\|\Delta a\|^2 | 减少抖动 |
| 能量/力矩 | -\|tau\|^2 | 可选，省能、更真实 |
| 障碍物 | -1 若碰撞 / 距离障碍物过近 | 与 scene_obstacles 配合 |

## 权重建议（起步）

- 存活/前进：1.0
- 高度：0.5
- 姿态：0.3
- 角速度：0.01
- 动作变化：0.001
- 障碍物碰撞：-1.0 或 -0.5

具体数值在 `tienkung_rl_env.py` 或 Isaac Lab 的 env_cfg 里调。

## 与 Isaac Lab 的对接

若用 Isaac Lab，在 `humanoid_env_cfg` 风格里加 `RewardTermCfg`，在 `tienkung_rl_env.py` 里用同一套项即可。
