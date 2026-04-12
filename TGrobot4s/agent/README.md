# Agent 与 Cursor CLI

## 目标

- 根据场景或任务（如「去拿桌上的瓶子」「执行铁山靠」）生成行为序列或 command 列表。
- 可后台挂 **Cursor CLI**，由 Agent 写入配置/脚本，供真机控制服务或仿真使用。

## 用法

- Agent 输入：场景描述、任务文本、当前状态（可选）。
- Agent 输出：command 序列（如 `[move_fwd, turn_r, skill_tieshankao]`）、或直接写入本仓库下的 JSON/脚本。
- Cursor CLI：在后台以 headless 方式运行，接收任务并调用上述逻辑，结果写回项目或通过 API 发给控制端。

## 与比赛

- 满足「有 agent」要求；与移动端、仿真、真机形成闭环。
