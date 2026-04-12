# 基础命令 ID（移动端 / Agent 使用）

示教动作可映射为以下 command_id，供移动端「大招按钮」或 Agent 调用。

| command_id | 说明 | 参数 |
|------------|------|------|
| `move_fwd` | 前进 | speed, duration |
| `move_bwd` | 后退 | speed, duration |
| `turn_l` / `turn_r` | 左/右转 | angular_speed, duration |
| `squat` / `stand` | 蹲下 / 站起 | - |
| `skill_tieshankao` | 铁山靠 | 可选 direction |
| `skill_wave` | 挥手 | - |
| `skill_kick` | 踢腿 | 可选 left/right |

真机/仿真后端根据 command_id 查表执行对应轨迹或策略。
