#!/usr/bin/env python3
"""
天工Lite 上肢动作 - 骨架可视化（不加载 mesh，轻量级）
"""

import numpy as np
import math
import sys
import io
import xml.etree.ElementTree as ET

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ============== URDF 解析（轻量级，只提取关节信息） ==============
def parse_urdf_joints(urdf_path):
    """解析 URDF 中的关节信息"""
    tree = ET.parse(urdf_path)
    root = tree.getroot()

    joints = {}
    for joint in root.findall('joint'):
        name = joint.get('name')
        jtype = joint.get('type')

        parent = joint.find('parent').get('link')
        child = joint.find('child').get('link')

        origin = joint.find('origin')
        xyz = [0, 0, 0]
        rpy = [0, 0, 0]
        if origin is not None:
            if origin.get('xyz'):
                xyz = [float(x) for x in origin.get('xyz').split()]
            if origin.get('rpy'):
                rpy = [float(x) for x in origin.get('rpy').split()]

        limit = joint.find('limit')
        lower, upper = -3.14, 3.14
        if limit is not None:
            lower = float(limit.get('lower', -3.14))
            upper = float(limit.get('upper', 3.14))

        joints[name] = {
            'type': jtype,
            'parent': parent,
            'child': child,
            'xyz': xyz,
            'rpy': rpy,
            'lower': lower,
            'upper': upper,
        }

    return joints


def compute_link_positions(joints, cfg):
    """计算各连杆的位置"""
    # 构建变换矩阵
    def transform_matrix(xyz, rpy, angle=0):
        tx, ty, tz = xyz
        rx, ry, rz = rpy

        # 绕 X 轴旋转
        Rx = np.array([
            [1, 0, 0],
            [0, math.cos(rx), -math.sin(rx)],
            [0, math.sin(rx), math.cos(rx)]
        ])
        # 绕 Y 轴旋转
        Ry = np.array([
            [math.cos(ry), 0, math.sin(ry)],
            [0, 1, 0],
            [-math.sin(ry), 0, math.cos(ry)]
        ])
        # 绕 Z 轴旋转
        Rz = np.array([
            [math.cos(rz + angle), -math.sin(rz + angle), 0],
            [math.sin(rz + angle), math.cos(rz + angle), 0],
            [0, 0, 1]
        ])

        R = Rz @ Ry @ Rx
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = [tx, ty, tz]
        return T

    # 从根节点开始计算
    link_positions = {'pelvis': np.array([0, 0, 0.8])}  # 假设骨盆高度 0.8m
    link_transforms = {'pelvis': np.eye(4)}

    # 按层级顺序计算
    def compute_child_links(parent_link, parent_transform):
        for joint_name, joint_info in joints.items():
            if joint_info['parent'] == parent_link:
                child_link = joint_info['child']

                # 计算关节角度
                angle = 0
                if joint_info['type'] == 'revolute' and joint_name in cfg:
                    angle = cfg[joint_name]

                # 计算变换
                T = transform_matrix(joint_info['xyz'], joint_info['rpy'], angle)
                T_world = parent_transform @ T

                link_transforms[child_link] = T_world
                link_positions[child_link] = T_world[:3, 3]

                compute_child_links(child_link, T_world)

    compute_child_links('pelvis', np.eye(4))
    return link_positions, link_transforms


# ============== 动作定义 ==============
def create_wave_motion():
    # 幅度更大的挥手动作
    return [
        (0.0, {
            'shoulder_pitch_r_joint': 0.0,
            'shoulder_roll_r_joint': math.radians(-10),
            'elbow_pitch_r_joint': 0.0,
        }, "Home"),
        (1.5, {
            'shoulder_pitch_r_joint': math.radians(-90),   # 肩膀向前90度
            'shoulder_roll_r_joint': math.radians(-30),    # 肩膀外展30度
            'elbow_pitch_r_joint': math.radians(-90),     # 肘部弯曲90度
        }, "Raise arm high"),
        (2.0, {
            'shoulder_pitch_r_joint': math.radians(-90),
            'shoulder_roll_r_joint': math.radians(-30),
            'elbow_pitch_r_joint': math.radians(-120),    # 肘部更弯曲
        }, "Wave out"),
        (2.5, {
            'shoulder_pitch_r_joint': math.radians(-90),
            'shoulder_roll_r_joint': math.radians(-30),
            'elbow_pitch_r_joint': math.radians(-60),     # 肘部伸展
        }, "Wave in"),
        (3.0, {
            'shoulder_pitch_r_joint': math.radians(-90),
            'shoulder_roll_r_joint': math.radians(-30),
            'elbow_pitch_r_joint': math.radians(-120),    # 再次弯曲
        }, "Wave out"),
        (3.5, {
            'shoulder_pitch_r_joint': math.radians(-90),
            'shoulder_roll_r_joint': math.radians(-30),
            'elbow_pitch_r_joint': math.radians(-60),     # 再次伸展
        }, "Wave in"),
        (5.0, {
            'shoulder_pitch_r_joint': 0.0,
            'shoulder_roll_r_joint': math.radians(-10),
            'elbow_pitch_r_joint': 0.0,
        }, "Return home"),
    ]


# ============== 3D 可视化 ==============
def run_visualization(urdf_path, motion_name="wave"):
    print(f"[INFO] Loading URDF: {urdf_path}")

    joints = parse_urdf_joints(urdf_path)
    print(f"[INFO] Found {len(joints)} joints")

    keyframes = create_wave_motion()
    print(f"[INFO] Motion: {motion_name}, Keyframes: {len(keyframes)}")

    try:
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d import Axes3D

        fig = plt.figure(figsize=(10, 8))
        ax = fig.add_subplot(111, projection='3d')

        # 定义要显示的连杆连接关系
        skeleton_connections = [
            ('pelvis', 'hip_roll_l_link'),
            ('hip_roll_l_link', 'hip_pitch_l_link'),
            ('hip_pitch_l_link', 'hip_yaw_l_link'),
            ('hip_yaw_l_link', 'knee_pitch_l_link'),
            ('knee_pitch_l_link', 'ankle_pitch_l_link'),
            ('ankle_pitch_l_link', 'ankle_roll_l_link'),
            ('pelvis', 'hip_roll_r_link'),
            ('hip_roll_r_link', 'hip_pitch_r_link'),
            ('hip_pitch_r_link', 'hip_yaw_r_link'),
            ('hip_yaw_r_link', 'knee_pitch_r_link'),
            ('knee_pitch_r_link', 'ankle_pitch_r_link'),
            ('ankle_pitch_r_link', 'ankle_roll_r_link'),
            ('pelvis', 'spine_link'),
            ('spine_link', 'shoulder_pitch_l_link'),
            ('shoulder_pitch_l_link', 'shoulder_roll_l_link'),
            ('shoulder_roll_l_link', 'shoulder_yaw_l_link'),
            ('shoulder_yaw_l_link', 'elbow_pitch_l_link'),
            ('spine_link', 'shoulder_pitch_r_link'),
            ('shoulder_pitch_r_link', 'shoulder_roll_r_link'),
            ('shoulder_roll_r_link', 'shoulder_yaw_r_link'),
            ('shoulder_yaw_r_link', 'elbow_pitch_r_link'),
        ]

        def update_frame(frame_idx):
            ax.clear()
            t, positions, desc = keyframes[frame_idx]

            # 计算连杆位置
            link_pos, _ = compute_link_positions(joints, positions)

            # 绘制骨架
            for parent, child in skeleton_connections:
                if parent in link_pos and child in link_pos:
                    p = link_pos[parent]
                    c = link_pos[child]
                    ax.plot([p[0], c[0]], [p[1], c[1]], [p[2], c[2]], 'b-', linewidth=2)

            # 绘制关节点
            for name, pos in link_pos.items():
                ax.scatter(pos[0], pos[1], pos[2], c='r', s=50)

            # 设置坐标轴
            ax.set_xlim(-0.5, 0.5)
            ax.set_ylim(-0.5, 0.5)
            ax.set_zlim(0, 1.5)
            ax.set_xlabel('X')
            ax.set_ylabel('Y')
            ax.set_zlabel('Z')
            ax.set_title(f'Frame {frame_idx+1}/{len(keyframes)}: {desc}')

        # 添加滑块
        from matplotlib.widgets import Slider
        ax_slider = plt.axes([0.2, 0.02, 0.6, 0.03])
        slider = Slider(ax_slider, 'Frame', 0, len(keyframes)-1, valinit=0, valstep=1)

        def slider_update(val):
            frame_idx = int(slider.val)
            update_frame(frame_idx)
            fig.canvas.draw_idle()

        slider.on_changed(slider_update)

        # 初始帧
        update_frame(0)

        print("\n[INFO] Controls:")
        print("  - Drag slider to change frame")
        print("  - Mouse: rotate/zoom")
        print("  - Close window to exit")

        plt.show()

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()

        # 备用：文本输出
        print("\n[INFO] Keyframe summary:")
        for i, (t, positions, desc) in enumerate(keyframes):
            print(f"  Frame {i+1}: t={t}s, {desc}")
            for joint_name, angle in positions.items():
                print(f"    {joint_name}: {math.degrees(angle):.1f} deg")


if __name__ == "__main__":
    urdf_path = "D:/Develop/Project/SynEIAgent/third_party/TienKung-Lab/legged_lab/assets/tienkung2_lite/urdf/tienkung2_lite.urdf"
    run_visualization(urdf_path, "wave")
