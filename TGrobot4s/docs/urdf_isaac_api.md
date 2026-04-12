# URDF 与 Isaac Sim 接口说明

## 天工行者 URDF 来源

- **仓库**：https://github.com/x-humanoid-robomind/TienKung_URDF  
- **官网**：https://x-humanoid.com/opensource.html  

可选版本：

- `lite/` — Lite 版本，`urdf/humanoid_publish.urdf` + `meshes/`
- `pro/` — Pro 版本，结构类似
- `tiangong2pro-urdf/` — 天工 2.0 Pro（含 xacro、launch、RViz）
- `tianyi2-urdf/` — 天轶 2.0

mesh 路径：URDF 内通常使用相对路径指向 `meshes/*.STL`，导入时需保证 **asset root** 指向含 `urdf/` 与 `meshes/` 的目录。

## Isaac Sim URDF API（有接口）

Isaac Sim 提供 **URDF 扩展** 与 **命令式 API**，可直接导入 URDF，无需手写 USD。

### 扩展

- 扩展名：`isaacsim.asset.importer.urdf`
- 启用：**Window → Extensions** 中勾选，或配置中启用。

### 常用 API（Python）

```python
import omni.kit.commands
from isaacsim.asset.importer.urdf import _urdf

# 1. 创建导入配置
urdf_interface = _urdf.acquire_urdf_interface()
import_config = _urdf.ImportConfig()
# 人形为移动底座
import_config.fix_base = False
import_config.merge_fixed_joints = False
import_config.convex_decomp = False
import_config.self_collision = True
import_config.distance_scale = 1.0
import_config.density = 0.0

# 2. 解析 URDF 文件
result, robot_model = omni.kit.commands.execute(
    "URDFParseFile",
    urdf_path="/path/to/urdf/humanoid_publish.urdf",
    import_config=import_config
)

# 3. 可选：调整关节驱动（刚度/阻尼）
for joint in robot_model.joints:
    robot_model.joints[joint].drive.strength = 1047.19751
    robot_model.joints[joint].drive.damping = 52.35988

# 4. 导入到 Stage
result, prim_path = omni.kit.commands.execute(
    "URDFImportRobot",
    urdf_robot=robot_model,
    import_config=import_config,
)
```

### 一步到位：Parse + Import

```python
result, prim_path = omni.kit.commands.execute(
    "URDFParseAndImportFile",
    urdf_path="/path/to/urdf/humanoid_publish.urdf",
    import_config=import_config,
    dest_path="/path/to/output.usd"  # 可选
)
```

### 文档

- [Import URDF Tutorial](https://docs.isaacsim.omniverse.nvidia.com/latest/importer_exporter/import_urdf.html)
- [Urdf struct / ImportConfig](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/py/api/structisaacsim_1_1asset_1_1importer_1_1urdf_1_1_urdf.html)

## 天工机器人在 Isaac Sim 中的注意点

1. **底座**：人形为移动基座，`import_config.fix_base = False`（Moveable Base）。
2. **关节驱动**：腿/臂可为 Position 或 Velocity；若做扭矩控制，可设为 None drive，再在 RL 里用扭矩动作。
3. **mesh 路径**：URDF 中 `<mesh filename="..."/>` 多为相对路径，`urdf_path` 的父目录或 `asset root` 需包含 `meshes/`。
4. **单位**：天工 URDF 一般为米/千克，`distance_scale=1` 即可；若有毫米制需对应缩放。

## 本仓库用法

- 脚本：`isaac_sim/import_tienkung_urdf.py`（指定 `urdf/` 下的路径）。
- URDF 下载：`scripts/fetch_tienkung_urdf.bat`（或 .sh）克隆 TienKung_URDF 到 `urdf/`。
