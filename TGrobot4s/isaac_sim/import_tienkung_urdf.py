"""
天工行者（TienKung）URDF 导入 Isaac Sim

- 使用 Isaac Sim URDF API：URDFParseFile / URDFImportRobot
- 支持 lite/pro/tiangong2pro 等版本，需保证 meshes 路径正确

运行方式：
  - 在 Isaac Sim 中：Window -> Script Editor，加载并运行
  - 或 standalone：python.exe 使用 Isaac Sim 自带的 Python 解释器运行
    例如：<IsaacSim>/python.sh run_standalone.py
"""
import os
import argparse

# Isaac Sim / Omniverse 在 GUI 或 standalone 下可用
def _get_urdf_import_api():
    try:
        from isaacsim.asset.importer.urdf import _urdf
        return _urdf
    except ImportError:
        try:
            import omni.kit.commands
            # 仅用 omni.kit.commands 也可以，但 ImportConfig 需从扩展来
            return None
        except Exception:
            return None


def get_default_urdf_path(version="lite"):
    """返回本项目内天工 URDF 默认路径"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    
    # 新的 URDF 路径（x_humanoid_0430_newfeet_newbody_publish）
    urdf_root = os.path.join(repo_root, "lite_urdf_publish", "x_humanoid_0430_newfeet_newbody_publish")
    
    if version == "lite":
        return os.path.join(urdf_root, "urdf", "humanoid_publish.urdf")
    if version == "pro":
        # 如果有 pro 版本，更新此路径
        return os.path.join(urdf_root, "urdf", "humanoid_publish.urdf")
    if version == "tiangong2pro":
        # 如果有 tiangong2pro 版本，更新此路径
        return os.path.join(urdf_root, "urdf", "humanoid_publish.urdf")
    
    # 默认返回 lite 版本
    return os.path.join(urdf_root, "urdf", "humanoid_publish.urdf")


def create_import_config(fix_base=False, self_collision=True, merge_fixed_joints=False):
    """创建 URDF 导入配置（人形为移动底座）"""
    try:
        from isaacsim.asset.importer.urdf import _urdf
    except ImportError:
        raise RuntimeError("请在 Isaac Sim 的 Python 环境中运行（Window -> Script Editor 或 standalone）")
    cfg = _urdf.ImportConfig()
    cfg.fix_base = fix_base
    cfg.self_collision = self_collision
    cfg.merge_fixed_joints = merge_fixed_joints
    # Prefer convex decomposition for mesh contacts so the feet/ground
    # interaction is more stable after the startup hold is released.
    cfg.convex_decomp = True
    cfg.distance_scale = 1.0
    cfg.density = 0.0
    cfg.make_default_prim = True
    return cfg


def import_tienkung(urdf_path, fix_base=False, self_collision=True, dest_path=None):
    """
    解析并导入天工 URDF 到当前 Stage。

    Args:
        urdf_path: 指向 .urdf 的绝对路径（所在目录应含 meshes/ 或与 URDF 内路径一致）
        fix_base: False 为人形移动底座
        self_collision: 是否自碰撞
        dest_path: 可选，导出 USD 路径

    Returns:
        (success: bool, prim_path: str)
        prim_path 优先返回带 ArticulationRootAPI 的 prim，避免后续包裹到导入根节点而不是可运动根。
    """
    try:
        import omni.kit.commands
        from isaacsim.asset.importer.urdf import _urdf
    except ImportError:
        return False, "请在 Isaac Sim 内运行（omni/isaacsim 未找到）"

    if not os.path.isfile(urdf_path):
        return False, f"URDF not found: {urdf_path}"

    import_config = create_import_config(
        fix_base=fix_base,
        self_collision=self_collision
    )

    # 解析
    result, robot_model = omni.kit.commands.execute(
        "URDFParseFile",
        urdf_path=urdf_path,
        import_config=import_config,
    )
    if not result:
        return False, "URDFParseFile failed"

    # 可选：统一设置关节驱动（可按关节名分别调）
    for joint in robot_model.joints:
        robot_model.joints[joint].drive.strength = 1047.0
        robot_model.joints[joint].drive.damping = 52.0

    if dest_path:
        result, prim_path = omni.kit.commands.execute(
            "URDFParseAndImportFile",
            urdf_path=urdf_path,
            import_config=import_config,
            dest_path=dest_path,
            get_articulation_root=True,
        )
    else:
        result, prim_path = omni.kit.commands.execute(
            "URDFImportRobot",
            urdf_robot=robot_model,
            import_config=import_config,
            get_articulation_root=True,
        )

    return result, prim_path


def setup_scene_basic():
    """添加地面、灯光、物理场景，便于直接播放仿真"""
    from isaacsim.examples.interactive.base_sample import BaseSample
    try:
        world = BaseSample().get_world()
        world.scene.add_default_ground_plane()
    except Exception:
        pass
    # 若在 standalone 中无 BaseSample，可改用 omni.usd / omni.kit 直接创建 ground + physics
    try:
        import omni.usd
        stage = omni.usd.get_context().get_stage()
        if stage and not stage.GetPrimAtPath("/World/ground"):
            from pxr import UsdGeom, PhysxSchema, Gf
            scope = UsdGeom.Scope.Define(stage, "/World")
            plane = UsdGeom.Plane.Define(stage, "/World/ground")
            plane.CreateExtentAttr([(-100, -100), (100, 100)])
            plane.CreateAxisAttr("Z")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Import TienKung URDF into Isaac Sim")
    parser.add_argument("--urdf", type=str, default=None, help="Path to .urdf file")
    parser.add_argument("--version", type=str, default="lite", choices=["lite", "pro", "tiangong2pro"])
    parser.add_argument("--fix-base", action="store_true", help="Fix base (default: False for humanoid)")
    parser.add_argument("--no-self-collision", action="store_true")
    parser.add_argument("--dest-usd", type=str, default=None)
    args = parser.parse_args()

    urdf_path = args.urdf or get_default_urdf_path(args.version)
    try:
        success, out = import_tienkung(
            urdf_path,
            fix_base=args.fix_base,
            self_collision=not args.no_self_collision,
            dest_path=args.dest_usd,
        )
    except Exception as e:
        print("Import error (ensure running inside Isaac Sim):", e)
        return 1
    if success:
        print("Robot imported at:", out)
        try:
            setup_scene_basic()
        except Exception:
            pass
    else:
        print("Import failed:", out)
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
