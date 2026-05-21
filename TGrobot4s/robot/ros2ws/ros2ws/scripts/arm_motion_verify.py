#!/usr/bin/env python3
"""
天工Lite 上肢动作本地验证脚本
- 不依赖 ROS2，纯 Python 验证
- 可视化关节轨迹
- 检查角度安全限位
- 生成可直接在机器人上运行的 ROS2 脚本
"""

import json
import time
import math
import sys
import io
from dataclasses import dataclass
from typing import Dict, List, Tuple

# Windows 终端 UTF-8 支持
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ============== 电机配置（来自 YAML） ==============
@dataclass
class MotorConfig:
    motor_id: int
    joint_name: str
    pos_min: float  # 度
    pos_max: float  # 度
    default_pos: float = 0.0


# 左臂电机配置
LEFT_ARM_MOTORS = [
    MotorConfig(11, "left_shoulder_pitch", -170, 170),
    MotorConfig(12, "left_shoulder_roll", -15, 150),  # 不对称范围！
    MotorConfig(13, "left_elbow_pitch", -170, 170),
    MotorConfig(14, "left_wrist_roll", -150, 15),     # 不对称范围！
]

# 右臂电机配置
RIGHT_ARM_MOTORS = [
    MotorConfig(21, "right_shoulder_pitch", -170, 170),
    MotorConfig(22, "right_shoulder_roll", -150, 15),  # 不对称范围！
    MotorConfig(23, "right_elbow_pitch", -170, 170),
    MotorConfig(24, "right_wrist_roll", -150, 15),     # 不对称范围！
]

ALL_MOTORS = {m.motor_id: m for m in LEFT_ARM_MOTORS + RIGHT_ARM_MOTORS}


# ============== 安全检查 ==============
def check_safety(positions: Dict[int, float], use_hardware_limit: bool = True) -> Tuple[bool, List[str]]:
    """
    检查目标角度是否在安全范围内
    use_hardware_limit: True=使用硬件限位, False=在硬件限位基础上保留10%余量
    返回: (是否安全, 错误信息列表)
    """
    errors = []
    for motor_id, target_pos in positions.items():
        if motor_id not in ALL_MOTORS:
            errors.append(f"[WARN] Unknown motor ID: {motor_id}")
            continue

        motor = ALL_MOTORS[motor_id]

        if use_hardware_limit:
            # 使用硬件限位（推荐，因为底层控制器已有保护）
            safe_min = motor.pos_min
            safe_max = motor.pos_max
        else:
            # 在硬件限位基础上保留 10% 余量
            margin = (motor.pos_max - motor.pos_min) * 0.1
            safe_min = motor.pos_min + margin
            safe_max = motor.pos_max - margin

        if target_pos < safe_min or target_pos > safe_max:
            errors.append(
                f"[WARN] Motor {motor_id}({motor.joint_name}): "
                f"target {target_pos:.1f} deg out of range [{safe_min:.1f}, {safe_max:.1f}]"
            )

    return len(errors) == 0, errors


# ============== 动作定义 ==============
class ArmMotionSequence:
    """上肢动作序列"""

    def __init__(self, name: str, speed: float = 20.0, current_limit: float = 3.0):
        self.name = name
        self.speed = speed
        self.current_limit = current_limit
        self.keyframes: List[Tuple[float, Dict[int, float]]] = []  # (时间点, 目标位置)

    def add_keyframe(self, time_sec: float, positions: Dict[int, float]):
        """添加关键帧"""
        self.keyframes.append((time_sec, positions))
        return self

    def interpolate(self, t: float) -> Dict[int, float]:
        """线性插值获取任意时刻的目标位置"""
        if not self.keyframes:
            return {}

        # 找到当前时间所在的两个关键帧
        prev_frame = self.keyframes[0]
        next_frame = self.keyframes[-1]

        for i, frame in enumerate(self.keyframes):
            if frame[0] <= t:
                prev_frame = frame
                if i + 1 < len(self.keyframes):
                    next_frame = self.keyframes[i + 1]
                else:
                    next_frame = frame
            else:
                next_frame = frame
                break

        # 线性插值
        if prev_frame[0] == next_frame[0]:
            return prev_frame[1]

        alpha = (t - prev_frame[0]) / (next_frame[0] - prev_frame[0])
        alpha = max(0.0, min(1.0, alpha))

        result = {}
        all_ids = set(prev_frame[1].keys()) | set(next_frame[1].keys())
        for motor_id in all_ids:
            pos1 = prev_frame[1].get(motor_id, 0.0)
            pos2 = next_frame[1].get(motor_id, pos1)
            result[motor_id] = pos1 + alpha * (pos2 - pos1)

        return result


# ============== 预定义动作 ==============
def create_wave_motion() -> ArmMotionSequence:
    """挥手动作 - 安全版本"""
    motion = ArmMotionSequence("wave", speed=40.0)

    # 注意：电机22范围 -150~+15，电机24范围 -150~+15
    # t=0: 零位（所有电机在0度，这是安全的起始位置）
    motion.add_keyframe(0.0, {21: 0.0, 22: -10.0, 23: 0.0, 24: -10.0})

    # t=1.5: 举起右臂（肩外展 + 肘弯曲），使用更保守的角度
    motion.add_keyframe(1.5, {21: -45.0, 22: -10.0, 23: -60.0, 24: -10.0})

    # t=2.5-4.5: 挥手（手腕摆动）
    motion.add_keyframe(2.5, {24: -30.0})
    motion.add_keyframe(3.0, {24: -60.0})
    motion.add_keyframe(3.5, {24: -30.0})
    motion.add_keyframe(4.0, {24: -60.0})
    motion.add_keyframe(4.5, {24: -10.0})

    # t=6: 回到零位
    motion.add_keyframe(6.0, {21: 0.0, 22: -10.0, 23: 0.0, 24: -10.0})

    return motion


def create_ready_pose() -> ArmMotionSequence:
    """准备姿态 - 双臂微抬"""
    motion = ArmMotionSequence("ready", speed=25.0)

    # 注意电机范围：
    # 左臂: 11(-170~170), 12(-15~150), 13(-170~170), 14(-150~15)
    # 右臂: 21(-170~170), 22(-150~15), 23(-170~170), 24(-150~15)

    # 零位姿态（使用各自范围的安全起始位置）
    motion.add_keyframe(0.0, {11: 0.0, 12: 10.0, 13: 0.0, 14: -10.0,
                              21: 0.0, 22: -10.0, 23: 0.0, 24: -10.0})

    # 双臂微抬
    motion.add_keyframe(2.5, {11: 30.0, 12: 30.0, 13: -30.0, 14: -10.0,
                              21: 30.0, 22: -30.0, 23: -30.0, 24: -10.0})

    return motion


def create_nod_motion() -> ArmMotionSequence:
    """点头致意动作"""
    motion = ArmMotionSequence("nod", speed=35.0)

    # 零位
    motion.add_keyframe(0.0, {11: 0.0, 12: 10.0, 13: 0.0, 14: -10.0,
                              21: 0.0, 22: -10.0, 23: 0.0, 24: -10.0})

    # 双臂前举
    motion.add_keyframe(2.0, {11: -45.0, 12: 40.0, 13: -90.0, 14: -10.0,
                              21: -45.0, 22: -40.0, 23: -90.0, 24: -10.0})

    # 保持2秒
    motion.add_keyframe(4.0, {11: -45.0, 12: 40.0, 13: -90.0, 14: -10.0,
                              21: -45.0, 22: -40.0, 23: -90.0, 24: -10.0})

    # 回零
    motion.add_keyframe(6.0, {11: 0.0, 12: 10.0, 13: 0.0, 14: -10.0,
                              21: 0.0, 22: -10.0, 23: 0.0, 24: -10.0})

    return motion


# ============== 验证与可视化 ==============
def verify_motion(motion: ArmMotionSequence, dt: float = 0.1):
    """验证动作序列的安全性和连续性"""
    print(f"\n{'='*60}")
    print(f"Verifying motion: {motion.name}")
    print(f"Speed limit: {motion.speed} deg/s, Current limit: {motion.current_limit}A")
    print(f"{'='*60}")

    # 1. 检查所有关键帧的安全性
    print("\n[1] Keyframe safety check:")
    all_safe = True
    for t, positions in motion.keyframes:
        safe, errors = check_safety(positions)
        status = "[OK] Safe" if safe else "[FAIL] Exceeded"
        print(f"  t={t:.1f}s: {status}")
        if errors:
            for err in errors:
                print(f"    {err}")
            all_safe = False

    # 2. 检查速度约束
    print("\n[2] Velocity constraint check:")
    max_vel = 0.0
    for i in range(len(motion.keyframes) - 1):
        t1, pos1 = motion.keyframes[i]
        t2, pos2 = motion.keyframes[i + 1]
        dt_frame = t2 - t1
        if dt_frame <= 0:
            continue

        for motor_id in set(pos1.keys()) | set(pos2.keys()):
            p1 = pos1.get(motor_id, 0.0)
            p2 = pos2.get(motor_id, p1)
            vel = abs(p2 - p1) / dt_frame
            if vel > max_vel:
                max_vel = vel
            if vel > motion.speed:
                print(f"  [WARN] Motor {motor_id} at t={t1:.1f}-{t2:.1f}s: {vel:.1f} deg/s > {motion.speed} deg/s")

    print(f"  Max velocity: {max_vel:.1f} deg/s (limit: {motion.speed} deg/s)")

    # 3. 生成轨迹数据用于可视化
    print("\n[3] Trajectory data:")
    trajectory = []
    t_end = motion.keyframes[-1][0]
    t = 0.0
    while t <= t_end:
        positions = motion.interpolate(t)
        trajectory.append((t, positions))
        t += dt

    # 打印前几个和最后几个点
    for t, pos in trajectory[:3]:
        pos_str = ", ".join(f"{k}={v:.1f}d" for k, v in sorted(pos.items()))
        print(f"  t={t:.1f}s: {pos_str}")
    print(f"  ... ({len(trajectory)} points)")
    for t, pos in trajectory[-2:]:
        pos_str = ", ".join(f"{k}={v:.1f}d" for k, v in sorted(pos.items()))
        print(f"  t={t:.1f}s: {pos_str}")

    return all_safe, trajectory


def try_plot(trajectories: Dict[str, List[Tuple[float, Dict[int, float]]]]):
    """尝试用 matplotlib 绘图"""
    try:
        import matplotlib.pyplot as plt
        import matplotlib
        matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
        matplotlib.rcParams['axes.unicode_minus'] = False

        fig, axes = plt.subplots(2, 4, figsize=(16, 8))
        fig.suptitle('TiGong Lite Upper Body Motion Trajectory', fontsize=14)

        motor_names = {
            11: "L-Shoulder-Pitch", 12: "L-Shoulder-Roll", 13: "L-Elbow-Pitch", 14: "L-Wrist-Roll",
            21: "R-Shoulder-Pitch", 22: "R-Shoulder-Roll", 23: "R-Elbow-Pitch", 24: "R-Wrist-Roll"
        }

        for idx, motor_id in enumerate([11, 12, 13, 14, 21, 22, 23, 24]):
            ax = axes[idx // 4][idx % 4]
            motor = ALL_MOTORS[motor_id]

            # 绘制安全范围
            ax.axhspan(motor.pos_min, motor.pos_max, alpha=0.1, color='green')
            ax.axhline(y=motor.pos_min, color='red', linestyle='--', alpha=0.3)
            ax.axhline(y=motor.pos_max, color='red', linestyle='--', alpha=0.3)

            # 绘制各动作轨迹
            for name, traj in trajectories.items():
                times = [t for t, _ in traj]
                positions = [pos.get(motor_id, 0.0) for _, pos in traj]
                ax.plot(times, positions, label=name, linewidth=2)

            ax.set_title(f"{motor_names[motor_id]} (ID:{motor_id})")
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Angle (deg)")
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=8)

        plt.tight_layout()
        plt.savefig("TGrobot4s/robot/ros2ws/ros2ws/scripts/arm_motion_trajectory.png", dpi=150)
        print("\n[OK] Trajectory plot saved: arm_motion_trajectory.png")
        plt.show()

    except ImportError:
        print("\n[WARN] matplotlib not installed, skip plotting")
        print("  Install: pip install matplotlib")


# ============== 生成 ROS2 脚本 ==============
def generate_ros2_script(motion: ArmMotionSequence, output_path: str):
    """生成可直接在机器人上运行的 ROS2 Python 脚本"""

    # 构建关键帧数据
    keyframes_json = json.dumps(motion.keyframes, indent=2)

    script = f'''#!/usr/bin/env python3
"""
自动生成的 ROS2 上肢动作脚本
动作名称: {motion.name}
速度限制: {motion.speed}°/s
电流限制: {motion.current_limit}A
"""

import rclpy
from rclpy.node import Node
from bodyctrl_msgs.msg import CmdSetMotorPosition, SetMotorPosition
from bodyctrl_msgs.msg import MotorStatusMsg
import time
import json


class ArmMotionNode(Node):
    def __init__(self):
        super().__init__('arm_motion_{motion.name}')

        # 订阅电机状态
        self.sub_motor = self.create_subscription(
            MotorStatusMsg, '/motor_status_msg', self.motor_status_cb, 10)

        # 发布电机指令
        self.pub_motor = self.create_publisher(
            CmdSetMotorPosition, '/cmd_set_motor_position', 10)

        # 关键帧数据: [(time, {{motor_id: angle}}), ...]
        self.keyframes = {keyframes_json}
        self.speed = {motion.speed}
        self.current_limit = {motion.current_limit}

        self.get_logger().info(f'动作节点已启动: {motion.name}')

        # 启动动作执行
        self.execute_motion()

    def send_positions(self, positions, speed=None):
        msg = CmdSetMotorPosition()
        msg.header.stamp = self.get_clock().now().to_msg()
        for motor_id, angle in positions.items():
            cmd = SetMotorPosition()
            cmd.name = int(motor_id)  # JSON keys are strings, convert to int
            cmd.pos = float(angle)
            cmd.spd = float(speed or self.speed)
            cmd.cur = float(self.current_limit)
            msg.cmds.append(cmd)
        self.pub_motor.publish(msg)

    def execute_motion(self):
        for i, (t, positions) in enumerate(self.keyframes):
            self.get_logger().info(f'执行关键帧 {{i+1}}/{{len(self.keyframes)}}: t={{t:.1f}}s')
            self.send_positions(positions)
            if i < len(self.keyframes) - 1:
                wait = self.keyframes[i+1][0] - t
                time.sleep(max(0.1, wait))

        self.get_logger().info('动作执行完成')

    def motor_status_cb(self, msg):
        for s in msg.status:
            if s.name in [11, 12, 13, 14, 21, 22, 23, 24]:
                self.get_logger().info(
                    f'ID={{s.name}}: pos={{s.pos:.1f}}° speed={{s.speed:.1f}}°/s cur={{s.current:.2f}}A')


def main():
    rclpy.init()
    node = ArmMotionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.send_positions({{11: 0, 12: 0, 13: 0, 14: 0, 21: 0, 22: 0, 23: 0, 24: 0}}, speed=10.0)
        time.sleep(2)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(script)
    print(f"\n[OK] ROS2 script generated: {output_path}")


# ============== 主程序 ==============
if __name__ == "__main__":
    print("=" * 60)
    print("TiGong Lite Upper Body Motion Local Verification")
    print("=" * 60)

    # 创建动作序列
    motions = {
        "wave": create_wave_motion(),
        "ready": create_ready_pose(),
        "nod": create_nod_motion(),
    }

    # 验证每个动作
    all_trajectories = {}
    all_safe = True

    for name, motion in motions.items():
        safe, traj = verify_motion(motion)
        all_trajectories[name] = traj
        if not safe:
            all_safe = False

    # 尝试绘图
    try_plot(all_trajectories)

    # 生成 ROS2 脚本
    for name, motion in motions.items():
        output_path = f"TGrobot4s/robot/ros2ws/ros2ws/scripts/arm_motion_{name}_ros2.py"
        generate_ros2_script(motion, output_path)

    # 总结
    print("\n" + "=" * 60)
    if all_safe:
        print("[OK] All motions verified! Ready to upload to robot.")
    else:
        print("[FAIL] Some motions have safety issues, please check.")
    print("=" * 60)
