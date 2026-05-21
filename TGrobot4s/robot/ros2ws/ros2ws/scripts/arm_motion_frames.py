#!/usr/bin/env python3
"""
天工Lite 上肢动作 - 逐帧导出为图片
"""

import yourdfpy
import numpy as np
import math
import sys
import io
import os

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

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
        (6.0, {21: 0.0, 22: -10.0, 23: 0.0}, "Return"),
    ]

def set_robot_pose(robot, actuated_joints, positions):
    num_joints = len(actuated_joints)
    cfg = np.zeros(num_joints)
    for i, name in enumerate(actuated_joints):
        if name in URDF_TO_MOTOR:
            motor_id = URDF_TO_MOTOR[name]
            if motor_id in positions:
                cfg[i] = math.radians(positions[motor_id])
    robot.update_cfg(cfg)

def main():
    urdf_path = "D:/Develop/Project/SynEIAgent/third_party/TienKung-Lab/legged_lab/assets/tienkung2_lite/urdf/tienkung2_lite.urdf"
    output_dir = "TGrobot4s/robot/ros2ws/ros2ws/scripts/frames"

    os.makedirs(output_dir, exist_ok=True)

    keyframes = create_wave_motion()
    print(f"[INFO] Generating {len(keyframes)} frames...")

    for i, (t, positions, desc) in enumerate(keyframes):
        print(f"[INFO] Frame {i+1}/{len(keyframes)}: {desc}")

        # 每次重新加载 URDF（避免内存问题）
        robot = yourdfpy.URDF.load(urdf_path, build_scene_graph=True)
        actuated_joints = robot.actuated_joint_names

        set_robot_pose(robot, actuated_joints, positions)

        # 导出为 GLB 文件
        glb_path = os.path.join(output_dir, f"frame_{i:02d}_{desc.replace(' ', '_')}.glb")
        robot.scene.export(glb_path)
        print(f"  Saved: {glb_path}")

    print(f"\n[INFO] All frames saved to {output_dir}")
    print("[INFO] You can view these files with:")
    print("  - Windows 3D Viewer")
    print("  - https://3dviewer.net/")
    print("  - Any GLB/GLTF viewer")

if __name__ == "__main__":
    main()
