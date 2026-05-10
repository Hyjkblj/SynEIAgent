"""
Isaac Sim 控制桥接启动脚本

在 Isaac Sim 中导入 URDF 后，通过 Script Editor 运行此脚本：
  Window -> Script Editor -> 粘贴运行

功能：
- 自动查找场景中已导入的机器人
- 点击 PLAY 后自动创建 Articulation
- 启动 HTTP API（端口 9200）
- 支持逐关节 PD 增益（从 tg22_config.yaml 加载）

运行步骤：
  1. 导入 URDF
  2. 在 Script Editor 中运行此脚本
  3. 点击 PLAY
"""
import os
import sys
import threading
import time

import numpy as np

# ===== 项目路径（Script Editor 中 __file__ 不可靠，硬编码）=====
PROJECT_ROOT = r"D:\Develop\Project\SynEIAgent"
ISAAC_SIM_DIR = os.path.join(PROJECT_ROOT, "TGrobot4s", "isaac_sim")

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_ROBOT_PRIM_CANDIDATES = [
    "/World/humanoid",
    "/World/robot",
    "/World/tienkung",
    "/World/tiangong_lite",
]


def find_robot_prim():
    """在 Stage 中查找机器人 prim"""
    try:
        import omni.usd
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return None
        for path in _ROBOT_PRIM_CANDIDATES:
            prim = stage.GetPrimAtPath(path)
            if prim.IsValid():
                return path
        world_prim = stage.GetPrimAtPath("/World")
        if world_prim.IsValid():
            for child in world_prim.GetChildren():
                if child.GetChildren():
                    for sub in child.GetChildren():
                        if "joint" in sub.GetName().lower():
                            return str(child.GetPath())
        return None
    except Exception:
        return None


def load_policy_gains(policy_config_path=None):
    """从 tg22_config.yaml 加载逐关节 PD 增益"""
    if policy_config_path is None:
        policy_config_path = os.path.join(
            PROJECT_ROOT, "DeployTienkug", "Deploy_Tienkung",
            "rl_control_new", "config", "tg22_config.yaml"
        )
    if not os.path.isfile(policy_config_path):
        print(f"[Config] tg22_config.yaml not found: {policy_config_path}")
        return None, None
    try:
        import yaml
    except ImportError:
        yaml = None
    try:
        with open(policy_config_path, encoding="utf-8") as f:
            if yaml:
                data = yaml.safe_load(f)
            else:
                import json
                text = f.read()
                text = text.replace("'", '"')
                data = {}
                for key in ("joint_kp_p", "joint_kd_p"):
                    start = text.find(f"{key}:")
                    if start >= 0:
                        bracket_start = text.find("[", start)
                        bracket_end = text.find("]", bracket_start)
                        if bracket_start >= 0 and bracket_end >= 0:
                            data[key] = json.loads(text[bracket_start:bracket_end + 1])
        kp = list(data.get("joint_kp_p", []))[:20]
        kd = list(data.get("joint_kd_p", []))[:20]
        if kp and kd:
            print(f"[Config] Loaded per-joint KP/KD ({len(kp)} joints)")
            return kp, kd
        print("[Config] No joint_kp_p/joint_kd_p found in config")
        return None, None
    except Exception as e:
        print(f"[Config] Failed to load: {e}")
        return None, None


def start(robot_prim_path=None, port=9200, policy_config=None):
    """
    启动控制桥接。

    Args:
        robot_prim_path: 机器人 prim 路径，None 则自动查找
        port: HTTP API 端口
        policy_config: tg22_config.yaml 路径，None 则使用默认
    """
    from TGrobot4s.isaac_sim.ros2_control_bridge import create_robot_controller

    # 查找机器人
    if robot_prim_path is None:
        robot_prim_path = find_robot_prim()
    if robot_prim_path is None:
        print("[Error] 未找到机器人 prim。请先导入 URDF。")
        print(f"  尝试过的路径: {_ROBOT_PRIM_CANDIDATES}")
        print(f"  或手动指定: start(robot_prim_path='/World/your_robot')")
        return None

    print(f"[Control] Robot prim: {robot_prim_path}")

    # 加载 PD 增益
    joint_kp, joint_kd = load_policy_gains(policy_config)

    # 创建控制器（HTTP 服务器立即启动）
    controller = create_robot_controller(
        robot_prim_path=robot_prim_path,
        joint_kp=joint_kp,
        joint_kd=joint_kd,
    )

    def _wait_and_init():
        """后台线程：等待 PLAY，然后创建 Articulation"""
        print("[Control] Waiting for PLAY...")

        # 等待时间轴开始播放
        check_count = 0
        while True:
            try:
                import omni.timeline
                timeline = omni.timeline.get_timeline_interface()
                playing = timeline.is_playing()
                check_count += 1
                if check_count % 10 == 1:
                    print(f"[Control] Timeline check #{check_count}: playing={playing}")
                if playing:
                    break
            except Exception as e:
                if check_count <= 3:
                    print(f"[Control] Timeline check error: {e}")
            time.sleep(0.5)

        print("[Control] PLAY detected, creating Articulation...")

        # 给物理引擎一点启动时间
        time.sleep(2.0)

        # 尝试创建 Articulation
        try:
            from isaacsim.core.prims import SingleArticulation as ArticulationClass
        except ImportError:
            from isaacsim.core.prims import Articulation as ArticulationClass

        robot = None
        for attempt in range(100):
            try:
                if robot is None:
                    robot = ArticulationClass(prim_path=robot_prim_path, name="robot")
                robot.initialize()
                controller.set_robot(robot)

                # 验证物理句柄
                view = getattr(robot, "_articulation_view", None)
                if view is not None and hasattr(view, "is_physics_handle_valid"):
                    handle_valid = view.is_physics_handle_valid()
                    if handle_valid is None or not handle_valid:
                        if attempt % 10 == 0:
                            print(f"[Control] Waiting for physics handle... (attempt {attempt+1})")
                        time.sleep(0.5)
                        continue

                print(f"[Control] Articulation created, {len(controller._joint_names)} joints")

                # 注册物理回调：应用关节目标 + 更新 IMU
                # 注意：只写不读！get_joint_positions() 在物理步进期间禁止
                try:
                    import omni.physx
                    physx = omni.physx.get_physx_interface()

                    def _on_physics_step(dt):
                        controller._apply_joint_targets()
                        controller._update_imu(dt)

                    physx.subscribe_physics_step_events(_on_physics_step)
                    print("[Control] Physics callback registered (targets + IMU)")
                except Exception as e:
                    print(f"[Control] Physics callback failed: {e}")

                # 启动控制线程：仅应用目标（纯写操作，无竞态风险）
                # get_joint_positions() 有竞态风险，不在控制线程中调用
                def _control_loop():
                    import omni.timeline
                    dt = 1.0 / 50.0  # 50Hz
                    while True:
                        try:
                            timeline = omni.timeline.get_timeline_interface()
                            if not timeline.is_playing():
                                time.sleep(0.5)
                                continue
                            controller._apply_joint_targets()
                        except Exception:
                            pass
                        time.sleep(dt)

                ctrl_thread = threading.Thread(target=_control_loop, daemon=True)
                ctrl_thread.start()
                print("[Control] Control thread started (50Hz)")

                return

            except Exception as e:
                if attempt < 3 or attempt % 20 == 0:
                    print(f"[Control] Articulation init failed (attempt {attempt+1}): {e}")
                robot = None  # 重置，下次重新创建
                time.sleep(0.5)

        print("[Control] Failed to create Articulation after 100 attempts")

    # 启动后台线程
    thread = threading.Thread(target=_wait_and_init, daemon=True)
    thread.start()

    print(f"\n[Control] HTTP API ready on http://0.0.0.0:{port}")
    print(f"  /health         - health check")
    print(f"  /joint_states   - joint states")
    print(f"  /imu            - IMU data")
    print(f"  /joint_command  - joint commands")
    print(f"  /move           - velocity commands")
    print(f"  /stop           - stop")
    print(f"\n[Control] Click PLAY in Isaac Sim to start simulation")

    return controller


# 自动启动
start()
