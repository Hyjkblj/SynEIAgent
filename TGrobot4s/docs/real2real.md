# 真机 Real2Real 与移动端

## 目标

- 仿真跑完后 **一键同步到真机**。
- 移动端可 **遥控机器人**，并支持 **环太平洋式** 实时视频遥控。
- **Agent** 根据场景设计特殊交互（可后台挂 Cursor CLI）。

## 移动端

- **控制**：WebRTC（低延迟） + HTTP（指令、状态）。
- **视频流**：摄像头/机载相机 → 编码 → WebRTC 或 HTTP 流 → 移动端渲染（环太平洋式第一视角）。
- **语音**：语音指令 → 识别 → 转为 command_id 或参数，再通过控制通道下发。

## Agent 与 Cursor CLI

- 后台挂 **Cursor CLI**：Agent 接收场景描述或任务（如「去拿桌上的瓶子」），生成行为序列或 command 列表。
- Agent 输出可写入本仓库的配置/脚本，由真机控制服务解析执行。

## 一键同步到真机

- **策略/技能**：仿真中训练好的策略或示教得到的轨迹 → 导出为真机可执行格式（如 joint trajectory、torque 序列或 command 序列）。
- **脚本**：`scripts/sync_to_real.md` 描述打包、传输、部署流程；具体协议依赖真机 SDK（如优必选天工提供的 API）。

## 比赛要求对照

- 移动端 ✓：WebRTC + HTTP、视频、语音。
- Agent ✓：场景内特殊交互、Cursor CLI。
- 渲染 ✓：Isaac Sim 渲染；移动端渲染视频流。
- 3D 建模 + Reward ✓：见 `isaac_sim/`、`rl_env/reward_design.md`。
