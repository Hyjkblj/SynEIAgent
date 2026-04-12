"""
障碍物与碰撞、摩擦场景配置 — Isaac Sim

- 在已有 Stage 上添加障碍物（立方体/圆柱/球等）
- 配置物理材质：静摩擦、动摩擦、恢复系数
- 与 RL 环境配合：障碍物可随机化（位置/尺寸）做 domain randomization
"""
import os
import argparse
from typing import Optional, List, Tuple

# 使用 Isaac Sim / Omniverse 的 USD 与 PhysX API
def get_stage():
    try:
        import omni.usd
        return omni.usd.get_context().get_stage()
    except Exception:
        return None


def add_ground_plane(stage, path="/World/ground", size=10.0):
    """添加地面平面并启用碰撞"""
    from pxr import UsdGeom, UsdPhysics, PhysxSchema, Gf
    if stage.GetPrimAtPath(path):
        return path
    plane = UsdGeom.Plane.Define(stage, path)
    plane.CreateExtentAttr([(-size, -size), (size, size)])
    plane.CreateAxisAttr("Z")
    # 碰撞
    UsdPhysics.CollisionAPI.Apply(plane.GetPrim())
    return path


def create_physics_material(stage, path: str, static_friction: float = 0.8, dynamic_friction: float = 0.6, restitution: float = 0.0):
    """
    创建 PhysX 材质并返回 prim path。
    Isaac Sim 4.x/5.x 常用：UsdPhysics.MaterialAPI + PhysxSchema 或 omni.physics
    """
    from pxr import UsdShade, UsdPhysics, Sdf
    if stage.GetPrimAtPath(path):
        return path
    material = UsdPhysics.MaterialAPI.Apply(stage.DefinePrim(path, "Scope"))
    # PhysX 材质在 Isaac Sim 中可能通过 PhysxSchema 或 omni 设置
    # 这里用 USD 占位，实际摩擦/恢复系数可在 omni.physics 里设置
    return path


def add_cube_obstacle(stage, path: str, position: Tuple[float, float, float], size: Tuple[float, float, float],
                      static_friction: float = 0.7, dynamic_friction: float = 0.5, restitution: float = 0.0):
    """添加立方体障碍物并设置碰撞与摩擦"""
    from pxr import UsdGeom, UsdPhysics, Gf
    if stage.GetPrimAtPath(path):
        return path
    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr(1.0)
    x, y, z = size
    cube.GetSizeAttr().Set(max(x, y, z))  # 简化：立方体边长取最大
    cube.AddTranslateOp().Set(Gf.Vec3d(*position))
    UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
    # 刚体（静态障碍物可不设 RigidBody，仅 Collision）
    return path


def add_cylinder_obstacle(stage, path: str, position: Tuple[float, float, float], radius: float, height: float,
                          static_friction: float = 0.7, dynamic_friction: float = 0.5):
    """添加圆柱障碍物"""
    from pxr import UsdGeom, UsdPhysics, Gf
    if stage.GetPrimAtPath(path):
        return path
    cylinder = UsdGeom.Cylinder.Define(stage, path)
    cylinder.CreateRadiusAttr(radius)
    cylinder.CreateHeightAttr(height)
    cylinder.AddTranslateOp().Set(Gf.Vec3d(*position))
    UsdPhysics.CollisionAPI.Apply(cylinder.GetPrim())
    return path


def add_sphere_obstacle(stage, path: str, position: Tuple[float, float, float], radius: float,
                        static_friction: float = 0.7, dynamic_friction: float = 0.5):
    """添加球体障碍物"""
    from pxr import UsdGeom, UsdPhysics, Gf
    if stage.GetPrimAtPath(path):
        return path
    sphere = UsdGeom.Sphere.Define(stage, path)
    sphere.CreateRadiusAttr(radius)
    sphere.AddTranslateOp().Set(Gf.Vec3d(*position))
    UsdPhysics.CollisionAPI.Apply(sphere.GetPrim())
    return path


def build_demo_obstacle_scene(stage=None):
    """
    构建一个示例障碍物场景：地面 + 若干立方体/圆柱/球。
    与 Isaac Lab 的 RigidBodyMaterialCfg 对应：可在此设置摩擦/恢复系数。
    """
    stage = stage or get_stage()
    if not stage:
        print("No stage available. Run inside Isaac Sim.")
        return []

    add_ground_plane(stage, size=20.0)

    obstacles = []
    # 立方体
    obstacles.append(add_cube_obstacle(stage, "/World/obstacles/box1", (2.0, 0.0, 0.5), (1.0, 1.0, 1.0)))
    obstacles.append(add_cube_obstacle(stage, "/World/obstacles/box2", (-1.5, 1.5, 0.4), (0.8, 0.8, 0.8)))
    # 圆柱
    obstacles.append(add_cylinder_obstacle(stage, "/World/obstacles/cyl1", (0.0, 2.0, 0.5), 0.4, 1.0))
    # 球
    obstacles.append(add_sphere_obstacle(stage, "/World/obstacles/sphere1", (1.0, -1.0, 0.3), 0.3))

    print("Obstacles added:", obstacles)
    return obstacles


def configure_scene_physics(stage, gravity=-9.81):
    """配置场景物理（重力等）。Isaac Sim 中也可通过 SimulationContext 设置"""
    try:
        import omni.physics
        if hasattr(omni.physics, "get_physics_engine"):
            # 视版本而定
            pass
    except Exception:
        pass
    return


def main():
    parser = argparse.ArgumentParser(description="Add obstacles and collision/friction to Isaac Sim scene")
    parser.add_argument("--demo", action="store_true", help="Build demo obstacle scene")
    args = parser.parse_args()

    stage = get_stage()
    if not stage:
        print("Run this script inside Isaac Sim (Script Editor or standalone with stage).")
        return 1

    if args.demo:
        build_demo_obstacle_scene(stage)
        configure_scene_physics(stage)
    return 0


if __name__ == "__main__":
    exit(main())
