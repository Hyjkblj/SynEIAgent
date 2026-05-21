#!/usr/bin/env python3
"""
自动生成的 ROS2 上肢动作脚本
动作名称: ready
速度限制: 25.0°/s
电流限制: 3.0A
"""

import rclpy
from rclpy.node import Node
from bodyctrl_msgs.msg import CmdSetMotorPosition, SetMotorPosition
from bodyctrl_msgs.msg import MotorStatusMsg
import time
import json


class ArmMotionNode(Node):
    def __init__(self):
        super().__init__('arm_motion_ready')

        # 订阅电机状态
        self.sub_motor = self.create_subscription(
            MotorStatusMsg, '/motor_status_msg', self.motor_status_cb, 10)

        # 发布电机指令
        self.pub_motor = self.create_publisher(
            CmdSetMotorPosition, '/cmd_set_motor_position', 10)

        # 关键帧数据: [(time, {motor_id: angle}), ...]
        self.keyframes = [
  [
    0.0,
    {
      "11": 0.0,
      "12": 10.0,
      "13": 0.0,
      "14": -10.0,
      "21": 0.0,
      "22": -10.0,
      "23": 0.0,
      "24": -10.0
    }
  ],
  [
    2.5,
    {
      "11": 30.0,
      "12": 30.0,
      "13": -30.0,
      "14": -10.0,
      "21": 30.0,
      "22": -30.0,
      "23": -30.0,
      "24": -10.0
    }
  ]
]
        self.speed = 25.0
        self.current_limit = 3.0

        self.get_logger().info(f'动作节点已启动: ready')

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
            self.get_logger().info(f'执行关键帧 {i+1}/{len(self.keyframes)}: t={t:.1f}s')
            self.send_positions(positions)
            if i < len(self.keyframes) - 1:
                wait = self.keyframes[i+1][0] - t
                time.sleep(max(0.1, wait))

        self.get_logger().info('动作执行完成')

    def motor_status_cb(self, msg):
        for s in msg.status:
            if s.name in [11, 12, 13, 14, 21, 22, 23, 24]:
                self.get_logger().info(
                    f'ID={s.name}: pos={s.pos:.1f}° speed={s.speed:.1f}°/s cur={s.current:.2f}A')


def main():
    rclpy.init()
    node = ArmMotionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.send_positions({11: 0, 12: 0, 13: 0, 14: 0, 21: 0, 22: 0, 23: 0, 24: 0}, speed=10.0)
        time.sleep(2)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
