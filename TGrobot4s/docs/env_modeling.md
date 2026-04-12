# 环境快速建模

## 目标

- **手机拍照** 或 **文字/参数** → 在 Isaac Sim 里快速生成 3D 场景（地面、障碍物、碰撞/摩擦）。
- 相关参数可 **后续由大模型生成**（他们有素材库），或由 Cursor 暴力写入。

## 流程

1. **输入**
   - 手机拍照 → 可选：先做 3D 重建/深度估计，得到点云或几何参数；
   - 或直接由「描述 + 大模型」生成场景参数（见下）。
2. **参数格式**
   - 使用 `isaac_sim/env_modeling_api.py` 的 `SCENE_SCHEMA`：
     - `ground`: size, friction, restitution
     - `obstacles`: 列表，每项 type(box/cylinder/sphere)、path、position、size 或 radius/height、friction
3. **写入方式**
   - **Isaac Sim 有 API**：可用 Python 在 Sim 内创建/修改 USD（见 `scene_obstacles.py`、`env_modeling_api.py`）。
   - **AI 自动填充**：大模型根据描述生成 JSON → `apply_scene_to_isaac(scene)` 或 `write_scene_script()` 生成脚本。
   - **Cursor 暴力写入**：在项目里直接改 JSON 或生成的 Python 脚本，再在 Isaac Sim 中执行。

## 所需参数（供大模型/素材库）

- **地面**：尺寸、静摩擦、动摩擦、恢复系数。
- **障碍物**：类型（box/cylinder/sphere）、位置 (x,y,z)、尺寸（长宽高或半径高度）、摩擦、是否可移动。
- **可选**：灯光、材质名（后续可扩展为 Sim 内材质 ID）。

## 接口小结

| 接口 | 说明 |
|------|------|
| `load_scene_from_json(path)` | 从 JSON 加载场景 |
| `apply_scene_to_isaac(scene)` | 在 Isaac Sim 内应用场景 |
| `generate_scene_json_from_description(desc)` | 占位：描述 → JSON（可接 LLM） |
| `write_scene_script(output_path, scene)` | 生成可执行 Python 脚本 |

## 手机拍照实现环境建模（需要啥）

- **图像**：一张或多张照片。
- **可选**：深度图/点云（手机 LiDAR 或单目深度估计）。
- **输出**：几何体列表（位置、尺寸、粗略形状）→ 转成上述 JSON。
- **后续**：大模型可根据「房间」「办公室」等标签从素材库选典型物体并填参数。
