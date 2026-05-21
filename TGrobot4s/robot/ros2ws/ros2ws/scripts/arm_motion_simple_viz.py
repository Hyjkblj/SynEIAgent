#!/usr/bin/env python3
"""
天工Lite 上肢动作 3D 可视化（简化版）
逐帧展示关键姿态，按回车切换下一帧
"""

import yourdfpy
import numpy as np
import math
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# URDF 关节名 -> 电机ID
URDF_TO_MOTOR = {
    'shoulder_pitch_l_joint': 11,
    'shoulder_roll_l_joint': 12,
    'elbow_pitch_l_joint': 13,
    'shoulder_pitch_r_joint': 21,
    'shoulder_roll_r_joint': 22,
    'elbow_pitch_r_joint': 23,
}

def create_wave_motion():
    return [
        (0.0, {21: 0.0, 22: -10.0, 23: 0.0}, "Home"),
        (1.5, {21: -45.0, 22: -10.0, 23: -60.0}, "Raise arm"),
        (2.5, {21: -45.0, 22: -10.0, 23: -60.0}, "Wave start"),
        (3.0, {21: -45.0, 22: -10.0, 23: -60.0}, "Wave mid"),
        (3.5, {21: -45.0, 22: -10.0, 23: -60.0}, "Wave end"),
        (6.0, {21: 0.0, 22: -10.0, 23: 0.0}, "Return home"),
    ]

def create_ready_motion():
    return [
        (0.0, {11: 0.0, 12: 10.0, 13: 0.0, 21: 0.0, 22: -10.0, 23: 0.0}, "Home"),
        (2.5, {11: 30.0, 12: 30.0, 13: -30.0, 21: 30.0, 22: -30.0, 23: -30.0}, "Ready"),
    ]

def create_nod_motion():
    return [
        (0.0, {11: 0.0, 12: 10.0, 13: 0.0, 21: 0.0, 22: -10.0, 23: 0.0}, "Home"),
        (2.0, {11: -45.0, 12: 40.0, 13: -90.0, 21: -45.0, 22: -40.0, 23: -90.0}, "Arms forward"),
        (4.0, {11: -45.0, 12: 40.0, 13: -90.0, 21: -45.0, 22: -40.0, 23: -90.0}, "Hold"),
        (6.0, {11: 0.0, 12: 10.0, 13: 0.0, 21: 0.0, 22: -10.0, 23: 0.0}, "Return"),
    ]

def set_robot_pose(robot, actuated_joints, positions):
    """设置机器人姿态"""
    num_joints = len(actuated_joints)
    cfg = np.zeros(num_joints)
    for i, name in enumerate(actuated_joints):
        if name in URDF_TO_MOTOR:
            motor_id = URDF_TO_MOTOR[name]
            if motor_id in positions:
                cfg[i] = math.radians(positions[motor_id])
    robot.update_cfg(cfg)
    return robot.scene

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--motion', type=str, default='wave', choices=['wave', 'ready', 'nod'])
    parser.add_argument('--urdf', type=str, default=None)
    args = parser.parse_args()

    if args.urdf is None:
        args.urdf = "D:/Develop/Project/SynEIAgent/third_party/TienKung-Lab/legged_lab/assets/tienkung2_lite/urdf/tienkung2_lite.urdf"

    motions = {
        "wave": create_wave_motion(),
        "ready": create_ready_motion(),
        "nod": create_nod_motion(),
    }

    keyframes = motions[args.motion]
    print(f"[INFO] Motion: {args.motion}, Keyframes: {len(keyframes)}")

    # 加载 URDF
    robot = yourdfpy.URDF.load(args.urdf)
    actuated_joints = robot.actuated_joint_names

    # 显示第一帧
    t, positions, desc = keyframes[0]
    scene = set_robot_pose(robot, actuated_joints, positions)
    print(f"\n[INFO] Showing frame 1/{len(keyframes)}: {desc}")

    # 使用 trimesh 查看器
    try:
        import trimesh
        from trimesh.viewer.windowed import SceneViewer
        import pyglet

        viewer = SceneViewer(scene=scene, caption=f"TiGong Lite - {args.motion} - {desc}")

        current_frame = [0]

        def on_key_press(symbol, modifiers):
            """按键事件处理"""
            if symbol == pyglet.window.key.RIGHT or symbol == pyglet.window.key.RETURN:
                current_frame[0] = (current_frame[0] + 1) % len(keyframes)
            elif symbol == pyglet.window.key.LEFT:
                current_frame[0] = (current_frame[0] - 1) % len(keyframes)
            elif symbol == pyglet.window.key.ESCAPE:
                pyglet.app.exit()
                return

            # 更新姿态
            t, positions, desc = keyframes[current_frame[0]]
            new_scene = set_robot_pose(robot, actuated_joints, positions)

            # 删除旧几何体，添加新几何体
            # 清空当前场景的几何体
            for name in list(viewer.scene.geometry.keys()):
                viewer.scene.delete_geometry(name)

            # 添加新场景的几何体
            for name, geom in new_scene.geometry.items():
                viewer.scene.add_geometry(geom, node_name=name, geom_name=name)

            # 更新场景图变换
            for node in list(viewer.scene.graph.nodes):
                if node in new_scene.graph.nodes:
                    transform_data = new_scene.graph.get(node)
                    if transform_data is not None:
                        viewer.scene.graph.update(node, transform=transform_data)

            print(f"[INFO] Frame {current_frame[0]+1}/{len(keyframes)}: {desc}")

        # 注册事件处理
        viewer.push_handlers(on_key_press)

        print("\n[INFO] Controls:")
        print("  - RIGHT/ENTER: Next frame")
        print("  - LEFT: Previous frame")
        print("  - ESC: Exit")
        print("  - Mouse: Rotate/zoom/pan")

        pyglet.app.run()

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()

        # 备用：打印所有关键帧信息
        print("\n[INFO] Keyframe summary:")
        for i, (t, positions, desc) in enumerate(keyframes):
            print(f"  Frame {i+1}: t={t}s, {desc}")
            for motor_id, angle in positions.items():
                print(f"    Motor {motor_id}: {angle} deg")

if __name__ == "__main__":
    main()
