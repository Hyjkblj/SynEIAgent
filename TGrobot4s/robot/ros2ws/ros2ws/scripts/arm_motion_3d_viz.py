#!/usr/bin/env python3
"""
天工Lite 上肢动作 3D 可视化
使用 yourdfpy 加载 URDF 模型，预览动作序列
"""

import yourdfpy
import numpy as np
import time
import math
import sys
import io

# Windows 终端 UTF-8 支持
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ============== URDF 关节映射 ==============
# URDF 关节名 -> 电机ID 映射
URDF_TO_MOTOR = {
    'shoulder_pitch_l_joint': 11,
    'shoulder_roll_l_joint': 12,
    'elbow_pitch_l_joint': 13,
    'shoulder_pitch_r_joint': 21,
    'shoulder_roll_r_joint': 22,
    'elbow_pitch_r_joint': 23,
}

# 电机ID -> URDF关节名（反向映射）
MOTOR_TO_URDF = {v: k for k, v in URDF_TO_MOTOR.items()}


# ============== 动作定义 ==============
def create_wave_motion():
    """挥手动作"""
    keyframes = [
        (0.0, {21: 0.0, 22: -10.0, 23: 0.0}),
        (1.5, {21: -45.0, 22: -10.0, 23: -60.0}),
        (2.5, {21: -45.0, 22: -10.0, 23: -60.0}),
        (3.0, {21: -45.0, 22: -10.0, 23: -60.0}),
        (3.5, {21: -45.0, 22: -10.0, 23: -60.0}),
        (4.0, {21: -45.0, 22: -10.0, 23: -60.0}),
        (4.5, {21: -45.0, 22: -10.0, 23: -60.0}),
        (6.0, {21: 0.0, 22: -10.0, 23: 0.0}),
    ]
    return keyframes


def create_ready_motion():
    """准备姿态"""
    keyframes = [
        (0.0, {11: 0.0, 12: 10.0, 13: 0.0, 21: 0.0, 22: -10.0, 23: 0.0}),
        (2.5, {11: 30.0, 12: 30.0, 13: -30.0, 21: 30.0, 22: -30.0, 23: -30.0}),
    ]
    return keyframes


def create_nod_motion():
    """点头致意"""
    keyframes = [
        (0.0, {11: 0.0, 12: 10.0, 13: 0.0, 21: 0.0, 22: -10.0, 23: 0.0}),
        (2.0, {11: -45.0, 12: 40.0, 13: -90.0, 21: -45.0, 22: -40.0, 23: -90.0}),
        (4.0, {11: -45.0, 12: 40.0, 13: -90.0, 21: -45.0, 22: -40.0, 23: -90.0}),
        (6.0, {11: 0.0, 12: 10.0, 13: 0.0, 21: 0.0, 22: -10.0, 23: 0.0}),
    ]
    return keyframes


# ============== 插值函数 ==============
def interpolate_keyframes(keyframes, t):
    """线性插值获取任意时刻的关节角度"""
    if t <= keyframes[0][0]:
        return keyframes[0][1].copy()
    if t >= keyframes[-1][0]:
        return keyframes[-1][1].copy()

    for i in range(len(keyframes) - 1):
        t1, pos1 = keyframes[i]
        t2, pos2 = keyframes[i + 1]
        if t1 <= t <= t2:
            alpha = (t - t1) / (t2 - t1) if t2 > t1 else 0
            result = {}
            all_ids = set(pos1.keys()) | set(pos2.keys())
            for motor_id in all_ids:
                p1 = pos1.get(motor_id, 0.0)
                p2 = pos2.get(motor_id, p1)
                result[motor_id] = p1 + alpha * (p2 - p1)
            return result

    return keyframes[-1][1].copy()


# ============== 主可视化函数 ==============
def run_visualization(urdf_path, motion_name="wave"):
    """运行 3D 可视化"""

    # 选择动作
    motions = {
        "wave": create_wave_motion(),
        "ready": create_ready_motion(),
        "nod": create_nod_motion(),
    }

    if motion_name not in motions:
        print(f"[ERROR] Unknown motion: {motion_name}")
        print(f"Available: {list(motions.keys())}")
        return

    keyframes = motions[motion_name]
    print(f"[INFO] Loading URDF: {urdf_path}")
    print(f"[INFO] Motion: {motion_name}, Keyframes: {len(keyframes)}")

    # 加载 URDF
    try:
        robot = yourdfpy.URDF.load(urdf_path, build_scene_graph=True, build_collision_scene_graph=False)
    except Exception as e:
        print(f"[ERROR] Failed to load URDF: {e}")
        return

    # 打印关节信息
    print("\n[INFO] Upper body joints in URDF:")
    actuated_joints = robot.actuated_joint_names
    joint_map = robot.joint_map
    for urdf_name, motor_id in URDF_TO_MOTOR.items():
        if urdf_name in actuated_joints:
            idx = actuated_joints.index(urdf_name)
            joint = joint_map[urdf_name]
            lower = math.degrees(joint.limit.lower) if joint.limit else 'N/A'
            upper = math.degrees(joint.limit.upper) if joint.limit else 'N/A'
            print(f"  {urdf_name}: index={idx}, limits=[{lower:.1f}, {upper:.1f}] deg, motor_id={motor_id}")
        else:
            print(f"  {urdf_name}: NOT FOUND in URDF")

    print(f"\n[INFO] All actuated joints ({len(actuated_joints)}):")
    for i, name in enumerate(actuated_joints):
        print(f"  [{i}] {name}")

    # 创建关节角度数组（按 URDF 关节顺序）
    num_joints = len(actuated_joints)
    joint_cfg = np.zeros(num_joints)

    # 初始姿态
    positions = keyframes[0][1]
    for i, name in enumerate(actuated_joints):
        if name in URDF_TO_MOTOR:
            motor_id = URDF_TO_MOTOR[name]
            if motor_id in positions:
                joint_cfg[i] = math.radians(positions[motor_id])

    robot.update_cfg(joint_cfg)

    # 尝试启动可视化
    try:
        print("\n[INFO] Starting 3D visualization...")
        print("[INFO] Controls:")
        print("  - Mouse: rotate/zoom/pan")
        print("  - Close window or Ctrl+C to exit")
        print("[INFO] Playing animation...")

        # 设置初始姿态
        positions = keyframes[0][1]
        cfg = np.zeros(num_joints)
        for i, name in enumerate(actuated_joints):
            if name in URDF_TO_MOTOR:
                motor_id = URDF_TO_MOTOR[name]
                if motor_id in positions:
                    cfg[i] = math.radians(positions[motor_id])
        robot.update_cfg(cfg)

        # 使用 trimesh 的 SceneViewer 进行动画
        from trimesh.viewer.windowed import SceneViewer
        import pyglet

        viewer = SceneViewer(scene=robot.scene, caption=f"TiGong Lite - {motion_name}")

        t_start = time.time()
        t_end = keyframes[-1][0]
        fps = 30

        def update(dt):
            """动画更新函数"""
            t = (time.time() - t_start) % (t_end * 2)
            if t > t_end:
                t = t_end * 2 - t

            positions = interpolate_keyframes(keyframes, t)
            cfg = np.zeros(num_joints)
            for i, name in enumerate(actuated_joints):
                if name in URDF_TO_MOTOR:
                    motor_id = URDF_TO_MOTOR[name]
                    if motor_id in positions:
                        cfg[i] = math.radians(positions[motor_id])
            robot.update_cfg(cfg)

            # 更新场景
            viewer.scene = robot.scene

        # 注册更新函数
        pyglet.clock.schedule_interval(update, 1.0 / fps)

        # 运行
        pyglet.app.run()

    except KeyboardInterrupt:
        print("\n[INFO] Visualization stopped")
    except Exception as e:
        print(f"\n[ERROR] Visualization failed: {e}")
        import traceback
        traceback.print_exc()
        print("\n[INFO] Trying simple static view...")

        # 最简单的静态展示
        try:
            robot.show()
        except Exception as e2:
            print(f"[ERROR] Simple view also failed: {e2}")


# ============== 主程序 ==============
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='TiGong Lite 3D Motion Visualization')
    parser.add_argument('--urdf', type=str, default=None,
                        help='Path to URDF file')
    parser.add_argument('--motion', type=str, default='wave',
                        choices=['wave', 'ready', 'nod'],
                        help='Motion to visualize')
    parser.add_argument('--list-joints', action='store_true',
                        help='List all joints in URDF and exit')
    args = parser.parse_args()

    # 默认 URDF 路径
    if args.urdf is None:
        args.urdf = "D:/Develop/Project/SynEIAgent/third_party/TienKung-Lab/legged_lab/assets/tienkung2_lite/urdf/tienkung2_lite.urdf"

    if args.list_joints:
        # 仅列出关节信息
        robot = yourdfpy.URDF.load(args.urdf)
        print("Actuated joints:")
        for i, name in enumerate(robot.actuated_joint_names):
            joint = robot.joint_map[name]
            lower = math.degrees(joint.limit.lower) if joint.limit else 'N/A'
            upper = math.degrees(joint.limit.upper) if joint.limit else 'N/A'
            print(f"  [{i}] {name}: [{lower}, {upper}]")
    else:
        run_visualization(args.urdf, args.motion)
