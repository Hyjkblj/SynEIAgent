"""
Isaac Sim 一键跑通：导入天工 URDF + 障碍物场景 + 物理

使用方式（在 Isaac Sim 安装目录下用其自带的 Python）：
  Windows:   <IsaacSim>\python.bat <项目路径>/isaac_sim/run_standalone.py
  Linux:     <IsaacSim>/python.sh <项目路径>/isaac_sim/run_standalone.py

或在 Isaac Sim 内：File -> Run Script -> 选择 run_standalone.py
"""
import os
import sys

# 把项目根目录加入 path，便于 import
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def main():
    # 1. 导入天工 URDF
    try:
        from isaac_sim.import_tienkung_urdf import import_tienkung, get_default_urdf_path, setup_scene_basic
    except ImportError:
        from import_tienkung_urdf import import_tienkung, get_default_urdf_path, setup_scene_basic

    urdf_path = get_default_urdf_path("lite")
    if not os.path.isfile(urdf_path):
        print("URDF 未找到，请先执行 scripts/fetch_tienkung_urdf.bat 或 .sh")
        print("路径:", urdf_path)
        return 1

    success, out = import_tienkung(urdf_path, fix_base=False, self_collision=True)
    if not success:
        print("URDF 导入失败:", out)
        return 1
    print("机器人已导入:", out)
    setup_scene_basic()

    # 2. 添加障碍物与碰撞/摩擦
    try:
        from isaac_sim.scene_obstacles import get_stage, build_demo_obstacle_scene
    except ImportError:
        from scene_obstacles import get_stage, build_demo_obstacle_scene

    stage = get_stage()
    if stage:
        build_demo_obstacle_scene(stage)
        print("障碍物场景已添加，可点击 PLAY 运行仿真。")
    else:
        print("未获取到 Stage，请确保在 Isaac Sim 内运行。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
