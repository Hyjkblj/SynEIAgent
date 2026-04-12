"""
环境快速建模 API — 供 AI/大模型/Cursor 写入 Isaac Sim 场景

- 输入：照片描述/点云/参数（后续可由大模型从素材库生成）
- 输出：在 Isaac Sim Stage 中生成/更新 USD 场景（地面、障碍物、材质等）

用法：
  - Cursor 或 Agent 可调用本模块的函数，暴力写入场景配置
  - 与 scene_obstacles 复用：障碍物、碰撞、摩擦参数
"""
import json
import os
from typing import List, Dict, Any, Optional

# 场景描述结构（可由大模型生成）
SCENE_SCHEMA = {
    "ground": {"size": 20.0, "friction": 0.8, "restitution": 0.0},
    "obstacles": [
        {"type": "box", "path": "/World/obs_1", "position": [2, 0, 0.5], "size": [1, 1, 1], "friction": 0.7},
        {"type": "cylinder", "path": "/World/obs_2", "position": [0, 2, 0.5], "radius": 0.4, "height": 1.0},
    ],
    "lights": [],
}


def load_scene_from_json(path: str) -> Dict[str, Any]:
    """从 JSON 文件加载场景描述（大模型可生成该 JSON）"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_scene_to_isaac(scene: Dict[str, Any], stage=None) -> List[str]:
    """
    将场景描述应用到 Isaac Sim Stage。
    若在 Isaac Sim 外调用，仅返回将要在 Sim 内执行的 prim 路径列表（供 Cursor 写入脚本用）。
    """
    try:
        from isaac_sim.scene_obstacles import (
            get_stage,
            add_ground_plane,
            add_cube_obstacle,
            add_cylinder_obstacle,
            add_sphere_obstacle,
        )
    except ImportError:
        from scene_obstacles import (
            get_stage,
            add_ground_plane,
            add_cube_obstacle,
            add_cylinder_obstacle,
            add_sphere_obstacle,
        )

    stage = stage or get_stage()
    created = []

    if "ground" in scene:
        g = scene["ground"]
        size = g.get("size", 20.0)
        if stage:
            add_ground_plane(stage, size=size)
        created.append("/World/ground")

    for i, obs in enumerate(scene.get("obstacles", [])):
        obs_type = obs.get("type", "box")
        path = obs.get("path", f"/World/obstacles/obs_{i}")
        pos = obs.get("position", [0, 0, 0.5])
        pos = (pos[0], pos[1], pos[2])
        if obs_type == "box" and stage:
            size = obs.get("size", [1, 1, 1])
            add_cube_obstacle(stage, path, pos, tuple(size))
            created.append(path)
        elif obs_type == "cylinder" and stage:
            add_cylinder_obstacle(
                stage, path, pos,
                obs.get("radius", 0.4),
                obs.get("height", 1.0),
            )
            created.append(path)
        elif obs_type == "sphere" and stage:
            add_sphere_obstacle(stage, path, pos, obs.get("radius", 0.3))
            created.append(path)

    return created


def generate_scene_json_from_description(description: str) -> Dict[str, Any]:
    """
    占位：根据文字描述生成场景 JSON。
    后续可接大模型 API：输入「房间里有两张桌子一个柱子」-> 输出 SCENE_SCHEMA 风格 JSON。
    """
    # 简单规则示例；实际可调用 LLM
    scene = {"ground": {"size": 20.0, "friction": 0.8}, "obstacles": []}
    if "桌" in description or "table" in description.lower():
        scene["obstacles"].append({
            "type": "box", "path": "/World/table1",
            "position": [2, 0, 0.4], "size": [1.2, 0.6, 0.8], "friction": 0.6,
        })
    if "柱" in description or "column" in description.lower():
        scene["obstacles"].append({
            "type": "cylinder", "path": "/World/column1",
            "position": [0, 1.5, 0.5], "radius": 0.3, "height": 1.0,
        })
    return scene


def write_scene_script(output_path: str, scene: Dict[str, Any]) -> None:
    """将场景生成可被 Cursor/Isaac Sim 执行的 Python 脚本（暴力写入用）"""
    script = f'''# Auto-generated scene script
import json
from isaac_sim.env_modeling_api import apply_scene_to_isaac

scene = {json.dumps(scene, indent=2)}
apply_scene_to_isaac(scene)
'''
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(script)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        scene_path = sys.argv[1]
        scene = load_scene_from_json(scene_path)
        apply_scene_to_isaac(scene)
    else:
        apply_scene_to_isaac(SCENE_SCHEMA)
